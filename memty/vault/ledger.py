"""Memty's user-owned atomic memory ledger.

Storage is intentionally small and inspectable:

* ``atomic_facts``      canonical slot -> value state (one row per slot)
* ``logical_constraints`` namespace rules applied by the consuming assistant
* ``rolling_summaries`` one capped summary per namespace
* ``raw_drilldown``     raw source text, fetched only by an explicit call
* ``atomic_fact_audit`` previous versions, kept for temporal auditing
* ``fact_proposals``    agent-proposed changes waiting for the user (``memty inbox``)
* ``fact_usage``        per-fact hit counters for served capsules
* ``context_receipts``  one row per served capsule: counts and slot names, never values

The three functional tables are the only tables used by retrieval.  The audit
table is a small append-only safety net for superseded values and is purged on
``forget`` (as are proposals for that slot).  No network calls or model calls
are made by this module.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

from .credentials import looks_like_credential
from .tokens import estimate_tokens, truncate_tokens
from .vectors import pack_vector, unpack_vector

SCHEMA_VERSION = 2
FACT_TOKEN_LIMIT = 40
SUMMARY_TOKEN_LIMIT = 150
DEFAULT_CONTEXT_BUDGET = 600

LOCAL_PROVIDERS = frozenset({"local", "ollama", "local_ollama", "memty_local", "nexor_local"})
_VERIFICATION_STATES = {"USER_CONFIRMED", "SPEC_LOCKED", "EXTRACTED"}
_SENSITIVITY_LEVELS = {"PUBLIC", "INTERNAL", "CONFIDENTIAL", "SECRET"}
_PROVIDER = re.compile(r"^[a-zA-Z0-9_.-]{1,80}$")
_KEY_PART = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_CONTEXT_SLOT_SUFFIX = re.compile(r"__c([0-9a-f]{10})([0-9a-f]{2})$")
_RULE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_TOKEN_TERM = re.compile(r"[\w'-]{2,}", re.UNICODE)
_RECEIPT_CHANNELS = frozenset({"recall", "mcp", "web", "clip"})
_PROPOSAL_STATES = frozenset({"PENDING", "APPROVED", "REJECTED", "SUPERSEDED"})
_SENSITIVITY_RANK = {"PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2, "SECRET": 3}
MAX_RECEIPTS = 50_000


class TombstonedSlot(ValueError):
    """Automatic extraction tried to recreate a slot the user deleted."""


class LockedSlot(ValueError):
    """Automatic extraction tried to overwrite a user-confirmed slot."""


def _utc_now_ms() -> int:
    return int(time.time() * 1000)


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _normalize_namespace(namespace: str) -> str:
    parts = [part.strip().lower() for part in str(namespace).split(".")]
    if not parts or any(not _KEY_PART.fullmatch(part) for part in parts):
        raise ValueError("namespace must contain lowercase dot-separated key parts")
    return ".".join(parts)


def _normalize_slot(slot: str) -> str:
    value = str(slot).strip().lower()
    if not _KEY_PART.fullmatch(value):
        raise ValueError("slot must be a lowercase key using letters, numbers, '_' or '-'")
    return value


@lru_cache(maxsize=8192)
def _terms(text: str) -> frozenset[str]:
    terms: set[str] = set()
    for token in _TOKEN_TERM.findall(str(text).casefold()):
        terms.add(token)
        terms.update(part for part in re.split(r"[_-]+", token) if len(part) >= 2)
    return frozenset(terms)


def _fts_query(terms: set[str] | frozenset[str]) -> str:
    return " OR ".join('"' + term.replace('"', '""') + '"*' for term in sorted(terms))


def _client_name(value: Any, default: str = "unknown") -> str:
    """Normalize a self-reported client name ("Claude Code" -> "claude-code")."""
    name = re.sub(r"[^a-z0-9_.-]+", "-", str(value or "").strip().casefold()).strip("-.")[:80]
    return name or default


def _json_list(value: Any) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


class MemtyLedger:
    """A per-user SQLite vault built around atomic facts and a capped compiler."""

    FORMAT = "memty-atomic-ledger-v1"

    def __init__(self, path: str | Path, user_id: str = "local", *,
                 trusted_providers: list[str] | tuple[str, ...] | set[str] | None = None):
        if not user_id or len(str(user_id)) > 200:
            raise ValueError("user_id must be a non-empty identifier of at most 200 characters")
        self.path = Path(path).expanduser()
        self.user_id = str(user_id)
        self.trusted_providers = frozenset(str(item).casefold() for item in (trusted_providers or ()))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fts = False
        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._connections_lock = threading.Lock()
        self._initialize()

    # ------------------------------------------------------------------
    # Storage lifecycle
    # ------------------------------------------------------------------
    def _new_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA temp_store=MEMORY")
        connection.execute("PRAGMA foreign_keys=ON")
        # Forget means forget: overwrite deleted content instead of leaving it in free pages.
        connection.execute("PRAGMA secure_delete=ON")
        with self._connections_lock:
            self._connections.append(connection)
        return connection

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = self._new_connection()
            self._local.connection = connection
        try:
            yield connection
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise

    def close(self) -> None:
        """Close the current thread's cached connection and all other handles."""
        current = getattr(self._local, "connection", None)
        if current is not None:
            try:
                current.close()
            finally:
                self._local.connection = None
        with self._connections_lock:
            connections, self._connections = self._connections, []
        for connection in connections:
            try:
                connection.close()
            except sqlite3.Error:
                pass

    def __del__(self):  # pragma: no cover - best effort during interpreter shutdown
        try:
            self.close()
        except Exception:
            pass

    def _initialize(self) -> None:
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS atomic_facts (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    slot TEXT NOT NULL,
                    value TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 1.0,
                    verification_state TEXT NOT NULL,
                    sensitivity TEXT NOT NULL DEFAULT 'PUBLIC',
                    source_id TEXT,
                    version INTEGER NOT NULL DEFAULT 1,
                    tombstone INTEGER NOT NULL DEFAULT 0,
                    allowed_providers TEXT NOT NULL DEFAULT '[]',
                    blocked_providers TEXT NOT NULL DEFAULT '[]',
                    ephemeral_redaction INTEGER NOT NULL DEFAULT 0,
                    embedding BLOB,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    UNIQUE(user_id, namespace, slot)
                );
                CREATE INDEX IF NOT EXISTS atomic_facts_namespace
                    ON atomic_facts(user_id, namespace, tombstone, updated_at DESC);
                CREATE INDEX IF NOT EXISTS atomic_facts_recent
                    ON atomic_facts(user_id, tombstone, updated_at DESC);

                CREATE TABLE IF NOT EXISTS logical_constraints (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    rule_id TEXT NOT NULL,
                    if_condition TEXT NOT NULL,
                    then_constraint TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    UNIQUE(user_id, namespace, rule_id)
                );
                CREATE INDEX IF NOT EXISTS logical_constraints_namespace
                    ON logical_constraints(user_id, namespace, updated_at DESC);

                CREATE TABLE IF NOT EXISTS rolling_summaries (
                    user_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    summary_text TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    embedding BLOB,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY (user_id, namespace)
                );
                CREATE INDEX IF NOT EXISTS rolling_summaries_recent
                    ON rolling_summaries(user_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS raw_drilldown (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    raw_content TEXT NOT NULL,
                    sha256_hash TEXT NOT NULL UNIQUE,
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS raw_drilldown_namespace
                    ON raw_drilldown(user_id, namespace, created_at DESC);

                CREATE TABLE IF NOT EXISTS atomic_fact_audit (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    slot TEXT NOT NULL,
                    value TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    verification_state TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    valid_from INTEGER NOT NULL,
                    valid_to INTEGER NOT NULL,
                    recorded_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS atomic_fact_audit_slot
                    ON atomic_fact_audit(user_id, namespace, slot, seq DESC);

                CREATE TABLE IF NOT EXISTS fact_proposals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    namespace TEXT NOT NULL,
                    slot TEXT NOT NULL,
                    value TEXT NOT NULL,
                    previous_value TEXT,
                    previous_state TEXT,
                    sensitivity TEXT NOT NULL DEFAULT 'PUBLIC',
                    proposed_by TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    created_at INTEGER NOT NULL,
                    resolved_at INTEGER
                );
                CREATE INDEX IF NOT EXISTS fact_proposals_status
                    ON fact_proposals(user_id, status, id);
                CREATE INDEX IF NOT EXISTS fact_proposals_slot
                    ON fact_proposals(user_id, namespace, slot, status);

                CREATE TABLE IF NOT EXISTS fact_usage (
                    fact_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    hit_count INTEGER NOT NULL DEFAULT 0,
                    last_hit_at INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS context_receipts (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    client TEXT NOT NULL,
                    namespace TEXT,
                    tokens_injected INTEGER NOT NULL DEFAULT 0,
                    baseline_tokens INTEGER NOT NULL DEFAULT 0,
                    facts_injected INTEGER NOT NULL DEFAULT 0,
                    verified_facts INTEGER NOT NULL DEFAULT 0,
                    redacted INTEGER NOT NULL DEFAULT 0,
                    secrets_blocked INTEGER NOT NULL DEFAULT 0,
                    slots_used TEXT NOT NULL DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS context_receipts_recent
                    ON context_receipts(user_id, seq DESC);
            """)
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            self._fts = self._create_fts(db)

    @staticmethod
    def _create_fts(db: sqlite3.Connection) -> bool:
        try:
            db.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS atomic_facts_fts USING fts5(
                    namespace, slot, value,
                    content='atomic_facts', content_rowid='rowid',
                    tokenize='unicode61'
                );
                CREATE TRIGGER IF NOT EXISTS atomic_facts_fts_ai AFTER INSERT ON atomic_facts BEGIN
                    INSERT INTO atomic_facts_fts(rowid, namespace, slot, value)
                    VALUES (new.rowid, new.namespace, new.slot, new.value);
                END;
                CREATE TRIGGER IF NOT EXISTS atomic_facts_fts_ad AFTER DELETE ON atomic_facts BEGIN
                    INSERT INTO atomic_facts_fts(atomic_facts_fts, rowid, namespace, slot, value)
                    VALUES ('delete', old.rowid, old.namespace, old.slot, old.value);
                END;
                CREATE TRIGGER IF NOT EXISTS atomic_facts_fts_au AFTER UPDATE ON atomic_facts BEGIN
                    INSERT INTO atomic_facts_fts(atomic_facts_fts, rowid, namespace, slot, value)
                    VALUES ('delete', old.rowid, old.namespace, old.slot, old.value);
                    INSERT INTO atomic_facts_fts(rowid, namespace, slot, value)
                    VALUES (new.rowid, new.namespace, new.slot, new.value);
                END;

                CREATE VIRTUAL TABLE IF NOT EXISTS rolling_summaries_fts USING fts5(
                    namespace, summary_text,
                    content='rolling_summaries', content_rowid='rowid',
                    tokenize='unicode61'
                );
                CREATE TRIGGER IF NOT EXISTS rolling_summaries_fts_ai AFTER INSERT ON rolling_summaries BEGIN
                    INSERT INTO rolling_summaries_fts(rowid, namespace, summary_text)
                    VALUES (new.rowid, new.namespace, new.summary_text);
                END;
                CREATE TRIGGER IF NOT EXISTS rolling_summaries_fts_ad AFTER DELETE ON rolling_summaries BEGIN
                    INSERT INTO rolling_summaries_fts(rolling_summaries_fts, rowid, namespace, summary_text)
                    VALUES ('delete', old.rowid, old.namespace, old.summary_text);
                END;
                CREATE TRIGGER IF NOT EXISTS rolling_summaries_fts_au AFTER UPDATE ON rolling_summaries BEGIN
                    INSERT INTO rolling_summaries_fts(rolling_summaries_fts, rowid, namespace, summary_text)
                    VALUES ('delete', old.rowid, old.namespace, old.summary_text);
                    INSERT INTO rolling_summaries_fts(rowid, namespace, summary_text)
                    VALUES (new.rowid, new.namespace, new.summary_text);
                END;
            """)
            return True
        except sqlite3.OperationalError as error:
            if "no such module: fts5" not in str(error).lower():
                raise
            # Some minimal Python builds omit FTS5.  Every query has a
            # deterministic SQL fallback, so the vault still works.
            return False

    # ------------------------------------------------------------------
    # Atomic facts
    # ------------------------------------------------------------------
    @staticmethod
    def _fact(row: sqlite3.Row, *, include_embedding: bool = False) -> dict[str, Any]:
        record = {
            "id": row["id"],
            "namespace": row["namespace"],
            "slot": row["slot"],
            "value": row["value"],
            "confidence": row["confidence"],
            "verification_state": row["verification_state"],
            "sensitivity": row["sensitivity"],
            "source_id": row["source_id"],
            "version": row["version"],
            "tombstone": bool(row["tombstone"]),
            "allowed_providers": _json_list(row["allowed_providers"]),
            "blocked_providers": _json_list(row["blocked_providers"]),
            "ephemeral_redaction": bool(row["ephemeral_redaction"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "has_embedding": bool(row["embedding"]),
        }
        if include_embedding:
            record["embedding"] = unpack_vector(row["embedding"])
        return record

    @staticmethod
    def _audit(db: sqlite3.Connection, row: sqlite3.Row, *, valid_to: int) -> None:
        db.execute("""
            INSERT INTO atomic_fact_audit(
                fact_id,user_id,namespace,slot,value,version,verification_state,
                sensitivity,valid_from,valid_to,recorded_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (row["id"], row["user_id"], row["namespace"], row["slot"], row["value"],
              row["version"], row["verification_state"], row["sensitivity"],
              row["updated_at"], valid_to, valid_to))

    def _drop_unused_raw(self, db: sqlite3.Connection, raw_id: str, *, except_id: str) -> None:
        """Delete an archived source once no other fact points at it."""
        if not str(raw_id).startswith("raw_"):
            return
        still_used = db.execute(
            "SELECT 1 FROM atomic_facts WHERE user_id=? AND source_id=? AND id<>? LIMIT 1",
            (self.user_id, raw_id, except_id)).fetchone()
        if not still_used:
            db.execute("DELETE FROM raw_drilldown WHERE user_id=? AND id=?", (self.user_id, raw_id))

    def record(self, namespace: str, slot: str, value: str, *, confidence: float = 1.0,
               verification_state: str = "EXTRACTED", sensitivity: str = "PUBLIC",
               allowed_providers: list[str] | None = None, blocked_providers: list[str] | None = None,
               ephemeral_redaction: bool = False, source_id: str | None = None,
               source_raw: str | None = None,
               embedding: list[float] | None = None, create_only: bool = False) -> dict[str, Any]:
        """Create or supersede one atomic slot.

        Values are capped at :data:`FACT_TOKEN_LIMIT` tokens.  Replacing a slot
        increments ``version`` and copies the previous value to the audit table.
        A tombstoned slot can only be restored by an explicit user confirmation
        (or a stronger spec lock).
        """
        namespace = _normalize_namespace(namespace)
        slot = _normalize_slot(slot)
        value = str(value).strip()
        if not value:
            raise ValueError("value cannot be empty")
        if estimate_tokens(value) > FACT_TOKEN_LIMIT:
            raise ValueError(f"atomic fact must be at most {FACT_TOKEN_LIMIT} tokens")
        confidence = float(confidence)
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")

        state = str(verification_state).upper()
        state = {"AUTO_EXTRACTED": "EXTRACTED", "PINNED": "SPEC_LOCKED",
                 "PENDING_CONFIRMATION": "EXTRACTED"}.get(state, state)
        if state not in _VERIFICATION_STATES:
            raise ValueError("verification_state must be USER_CONFIRMED, SPEC_LOCKED or EXTRACTED")

        sensitivity = str(sensitivity).upper()
        sensitivity = {"PERSONAL": "INTERNAL"}.get(sensitivity, sensitivity)
        if sensitivity not in _SENSITIVITY_LEVELS:
            raise ValueError("sensitivity must be PUBLIC, INTERNAL, CONFIDENTIAL or SECRET")
        if looks_like_credential(value):
            sensitivity = "SECRET"  # a pasted key or password never becomes shareable

        allowed = sorted({str(item).casefold() for item in (allowed_providers or [])})
        blocked = sorted({str(item).casefold() for item in (blocked_providers or [])})
        if any(not _PROVIDER.fullmatch(item) for item in allowed + blocked):
            raise ValueError("provider names may contain letters, numbers, '.', '_' and '-' only")

        if source_raw is not None:
            source_id = self.archive_raw(namespace, source_raw)

        encoded_embedding = pack_vector(embedding) if embedding is not None else None
        now = _utc_now_ms()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            # Strictly increasing save times: several facts saved in the same millisecond
            # (one browser Save on a fast machine) must still keep the order they were saved in.
            latest = db.execute("SELECT MAX(updated_at) FROM atomic_facts WHERE user_id=?",
                                (self.user_id,)).fetchone()[0]
            if latest is not None and now <= int(latest):
                now = int(latest) + 1
            existing = db.execute(
                "SELECT * FROM atomic_facts WHERE user_id=? AND namespace=? AND slot=?",
                (self.user_id, namespace, slot)).fetchone()
            if existing:
                if create_only:
                    db.execute("ROLLBACK")
                    raise LockedSlot("this slot already exists")
                if existing["tombstone"] and state not in {"USER_CONFIRMED", "SPEC_LOCKED"}:
                    db.execute("ROLLBACK")
                    raise TombstonedSlot("this slot was deleted by the user; automatic extraction cannot restore it")
                if (not existing["tombstone"] and existing["verification_state"] in {"USER_CONFIRMED", "SPEC_LOCKED"}
                        and state == "EXTRACTED"):
                    db.execute("ROLLBACK")
                    raise LockedSlot("a user-confirmed slot cannot be overwritten by automatic extraction")
                same = (
                    not existing["tombstone"]
                    and existing["value"] == value
                    and float(existing["confidence"]) == confidence
                    and existing["verification_state"] == state
                    and existing["sensitivity"] == sensitivity
                    and _json_list(existing["allowed_providers"]) == allowed
                    and _json_list(existing["blocked_providers"]) == blocked
                    and bool(existing["ephemeral_redaction"]) == bool(ephemeral_redaction)
                    and (source_id is None or existing["source_id"] == source_id)
                    and (encoded_embedding is None or existing["embedding"] == encoded_embedding)
                )
                if same:
                    db.execute("ROLLBACK")
                    return self._fact(existing)
                if source_id is None and str(existing["source_id"] or "").startswith("raw_"):
                    source_id = existing["source_id"]  # keep the archived source attached
                elif existing["source_id"] and existing["source_id"] != source_id:
                    self._drop_unused_raw(db, existing["source_id"], except_id=existing["id"])
                self._audit(db, existing, valid_to=now)
                db.execute("""
                    UPDATE atomic_facts
                       SET value=?, confidence=?, verification_state=?, sensitivity=?,
                           source_id=?, version=?, tombstone=0, allowed_providers=?,
                           blocked_providers=?, ephemeral_redaction=?, embedding=?,
                           updated_at=?
                     WHERE id=? AND user_id=?
                """, (value, confidence, state, sensitivity, source_id,
                      int(existing["version"]) + 1, json.dumps(allowed), json.dumps(blocked),
                      int(ephemeral_redaction), encoded_embedding, now,
                      existing["id"], self.user_id))
                memory_id = existing["id"]
            else:
                memory_id = "mem_" + uuid.uuid4().hex
                db.execute("""
                    INSERT INTO atomic_facts(
                        id,user_id,namespace,slot,value,confidence,verification_state,
                        sensitivity,source_id,version,tombstone,allowed_providers,
                        blocked_providers,ephemeral_redaction,embedding,created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """, (memory_id, self.user_id, namespace, slot, value, confidence, state,
                      sensitivity, source_id, 1, 0, json.dumps(allowed), json.dumps(blocked),
                      int(ephemeral_redaction), encoded_embedding, now, now))
            db.execute("COMMIT")
        return self.get(memory_id)  # type: ignore[return-value]

    def record_context(self, namespace: str, facts: list[dict]) -> dict[str, Any]:
        """Atomically save one reviewed selection without replacing another context."""
        namespace = _normalize_namespace(namespace)
        if not isinstance(facts, list) or not 1 <= len(facts) <= 25:
            raise ValueError("a context must contain 1-25 facts")
        prepared = []
        for item in facts:
            if not isinstance(item, dict):
                raise ValueError("each fact must have a title and value")
            slot = _normalize_slot(item.get("slot", ""))
            value = str(item.get("value", "")).strip()
            if len(slot) > 49:
                raise ValueError("fact title must be at most 49 characters")
            if not value or estimate_tokens(value) > FACT_TOKEN_LIMIT:
                raise ValueError(f"each fact must contain 1-{FACT_TOKEN_LIMIT} tokens")
            prepared.append((slot, value))

        ranks = {"PUBLIC": 0, "INTERNAL": 1, "CONFIDENTIAL": 2, "SECRET": 3}
        policies: dict[str, dict[str, Any]] = {}
        saved = []
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT * FROM atomic_facts WHERE user_id=? AND namespace=?",
                              (self.user_id, namespace)).fetchall()
            for row in rows:
                base = _CONTEXT_SLOT_SUFFIX.sub("", row["slot"])
                policy = policies.setdefault(base, {"sensitivity": "PUBLIC", "allowed": None,
                                                    "blocked": set(), "ephemeral": False})
                if ranks[row["sensitivity"]] > ranks[policy["sensitivity"]]:
                    policy["sensitivity"] = row["sensitivity"]
                allowed = set(_json_list(row["allowed_providers"]))
                if allowed:
                    policy["allowed"] = allowed if policy["allowed"] is None else policy["allowed"] & allowed
                policy["blocked"].update(_json_list(row["blocked_providers"]))
                policy["ephemeral"] |= bool(row["ephemeral_redaction"])
            now_ns = time.time_ns()
            batch = "save_" + f"{now_ns:016x}" + uuid.uuid4().hex[:8]
            now = now_ns // 1_000_000
            for index, (slot, value) in enumerate(prepared):
                actual_slot = slot + "__c" + batch[-10:] + f"{index:02x}"
                policy = policies.get(slot, {})
                allowed = policy.get("allowed")
                if allowed is not None and not allowed:
                    allowed = {"__memty_no_provider__"}
                try:
                    db.execute("""
                        INSERT INTO atomic_facts(
                            id,user_id,namespace,slot,value,confidence,verification_state,
                            sensitivity,source_id,version,tombstone,allowed_providers,
                            blocked_providers,ephemeral_redaction,created_at,updated_at
                        ) VALUES(?,?,?,?,?,1.0,'USER_CONFIRMED',?,?,1,0,?,?,?,?,?)
                    """, ("mem_" + uuid.uuid4().hex, self.user_id, namespace, actual_slot, value,
                          "SECRET" if looks_like_credential(value) else policy.get("sensitivity", "PUBLIC"), batch,
                          json.dumps(sorted(allowed)) if allowed is not None else "[]",
                          json.dumps(sorted(policy.get("blocked", ()))),
                          int(policy.get("ephemeral", False)), now, now))
                except sqlite3.IntegrityError as error:
                    raise ValueError("could not create a distinct context; please retry") from error
                saved.append({"slot": actual_slot, "version": 1})
            db.execute("COMMIT")
        return {"namespace": namespace, "context_id": batch, "saved": saved, "skipped": []}

    def get(self, memory_id: str, *, include_embedding: bool = False) -> dict[str, Any] | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM atomic_facts WHERE user_id=? AND id=?",
                             (self.user_id, str(memory_id))).fetchone()
        return self._fact(row, include_embedding=include_embedding) if row else None

    def find(self, namespace: str, slot: str) -> dict[str, Any] | None:
        namespace, slot = _normalize_namespace(namespace), _normalize_slot(slot)
        with self._connect() as db:
            row = db.execute("SELECT * FROM atomic_facts WHERE user_id=? AND namespace=? AND slot=?",
                             (self.user_id, namespace, slot)).fetchone()
        return self._fact(row) if row else None

    @staticmethod
    def _constraint(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "namespace": row["namespace"],
            "rule_id": row["rule_id"],
            "if_condition": row["if_condition"],
            "then_constraint": row["then_constraint"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def set_constraint(self, namespace: str, rule_id: str, if_condition: str,
                       then_constraint: str) -> dict[str, Any]:
        """Create or replace one deterministic namespace rule."""
        namespace = _normalize_namespace(namespace)
        rule_id = str(rule_id).strip().lower()
        if not _RULE_ID.fullmatch(rule_id):
            raise ValueError("rule_id must be a lowercase key using letters, numbers, '_' or '-'")
        if not str(if_condition).strip() or not str(then_constraint).strip():
            raise ValueError("if_condition and then_constraint cannot be empty")
        now = _utc_now_ms()
        with self._connect() as db:
            db.execute("""
                INSERT INTO logical_constraints(
                    id,user_id,namespace,rule_id,if_condition,then_constraint,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(user_id, namespace, rule_id) DO UPDATE SET
                    if_condition=excluded.if_condition,
                    then_constraint=excluded.then_constraint,
                    updated_at=excluded.updated_at
            """, ("rule_" + uuid.uuid4().hex, self.user_id, namespace, rule_id,
                  str(if_condition).strip(), str(then_constraint).strip(), now, now))
            row = db.execute("""
                SELECT * FROM logical_constraints
                 WHERE user_id=? AND namespace=? AND rule_id=?
            """, (self.user_id, namespace, rule_id)).fetchone()
        return self._constraint(row)

    def list_constraints(self, *, namespace: str | None = None) -> list[dict[str, Any]]:
        """List logical rules, optionally scoped to one namespace."""
        params: list[Any] = [self.user_id]
        query = "SELECT * FROM logical_constraints WHERE user_id=?"
        if namespace is not None:
            query += " AND namespace=?"
            params.append(_normalize_namespace(namespace))
        query += " ORDER BY namespace, rule_id"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._constraint(row) for row in rows]

    def delete_constraint(self, namespace: str, rule_id: str) -> bool:
        """Delete one logical rule."""
        namespace = _normalize_namespace(namespace)
        rule_id = str(rule_id).strip().lower()
        if not _RULE_ID.fullmatch(rule_id):
            raise ValueError("rule_id must be a lowercase key using letters, numbers, '_' or '-'")
        with self._connect() as db:
            cursor = db.execute("""
                DELETE FROM logical_constraints
                 WHERE user_id=? AND namespace=? AND rule_id=?
            """, (self.user_id, namespace, rule_id))
        return cursor.rowcount > 0

    def list(self, *, namespace: str | None = None,
             include_tombstones: bool = False) -> list[dict[str, Any]]:
        clauses = ["user_id=?"]
        params: list[Any] = [self.user_id]
        if namespace is not None:
            clauses.append("namespace=?")
            params.append(_normalize_namespace(namespace))
        if not include_tombstones:
            clauses.append("tombstone=0")
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM atomic_facts WHERE " + " AND ".join(clauses)
                + " ORDER BY namespace, slot, id", params).fetchall()
            hits = {row["fact_id"]: row["hit_count"] for row in db.execute(
                "SELECT fact_id, hit_count FROM fact_usage WHERE user_id=?", (self.user_id,))}
        facts = []
        for row in rows:
            fact = self._fact(row)
            fact["hit_count"] = int(hits.get(row["id"], 0))
            facts.append(fact)
        return facts

    def forget(self, namespace: str | None = None, slot: str | None = None, *,
               fact_id: str | None = None, purge_raw: bool = False) -> dict[str, Any] | None:
        """Tombstone a slot, remove its plaintext and purge its audit history."""
        if fact_id is not None:
            current = self.get(fact_id)
        elif namespace is not None and slot is not None:
            current = self.find(namespace, slot)
        else:
            raise ValueError("provide fact_id or both namespace and slot")
        if current is None:
            return None
        if current["tombstone"]:
            return current

        now = _utc_now_ms()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM atomic_facts WHERE user_id=? AND id=?",
                             (self.user_id, current["id"])).fetchone()
            if row is None:
                db.execute("ROLLBACK")
                return None
            # Forget means forget: the audit trail must not retain the value.
            db.execute("DELETE FROM atomic_fact_audit WHERE user_id=? AND fact_id=?",
                       (self.user_id, current["id"]))
            # Proposals hold candidate and previous values for this slot as well.
            db.execute("DELETE FROM fact_proposals WHERE user_id=? AND namespace=? AND slot=?",
                       (self.user_id, row["namespace"], row["slot"]))
            source_id = row["source_id"]
            if purge_raw and source_id:
                self._drop_unused_raw(db, source_id, except_id=current["id"])
                source_id = None
            db.execute("""
                UPDATE atomic_facts
                   SET value='', version=?, tombstone=1, source_id=?, embedding=NULL, updated_at=?
                 WHERE user_id=? AND id=?
            """, (int(row["version"]) + 1, source_id, now, self.user_id, current["id"]))
            db.execute("COMMIT")
            self._scrub(db)
        return self.get(current["id"])

    def _scrub(self, db: sqlite3.Connection) -> None:
        """Remove a forgotten value's leftovers from the search index and the WAL.

        FTS5 keeps deleted terms in older index segments until they are merged,
        and the write-ahead log keeps old page images until a checkpoint.
        """
        try:
            if self._fts:
                db.execute("INSERT INTO atomic_facts_fts(atomic_facts_fts) VALUES('optimize')")
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass  # another connection holds the WAL; the next checkpoint finishes the job

    def history(self, namespace: str, slot: str) -> list[dict[str, Any]]:
        """Return superseded versions plus the current state for one slot."""
        namespace, slot = _normalize_namespace(namespace), _normalize_slot(slot)
        with self._connect() as db:
            rows = db.execute("""
                SELECT value, version, verification_state, sensitivity, valid_from, valid_to
                  FROM atomic_fact_audit
                 WHERE user_id=? AND namespace=? AND slot=?
                 ORDER BY seq
            """, (self.user_id, namespace, slot)).fetchall()
            current = db.execute("SELECT * FROM atomic_facts WHERE user_id=? AND namespace=? AND slot=?",
                                 (self.user_id, namespace, slot)).fetchone()
        result = [dict(row) for row in rows]
        if current:
            result.append({"value": current["value"], "version": current["version"],
                           "verification_state": current["verification_state"],
                           "sensitivity": current["sensitivity"],
                           "valid_from": current["updated_at"], "valid_to": None,
                           "current": True, "tombstone": bool(current["tombstone"])})
        return result

    # ------------------------------------------------------------------
    # Raw drill-down archive
    # ------------------------------------------------------------------
    def archive_raw(self, namespace: str, content: str) -> str:
        """Store raw source text and return its id.  Never injected by default."""
        namespace = _normalize_namespace(namespace)
        content = str(content)
        if not content.strip():
            raise ValueError("raw content cannot be empty")
        if len(content) > 1_000_000:
            raise ValueError("raw content must be at most 1,000,000 characters")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        with self._connect() as db:
            existing = db.execute("SELECT id FROM raw_drilldown WHERE sha256_hash=?", (digest,)).fetchone()
            if existing:
                return existing["id"]
            raw_id = "raw_" + uuid.uuid4().hex
            db.execute("""
                INSERT INTO raw_drilldown(id,user_id,namespace,raw_content,sha256_hash,created_at)
                VALUES(?,?,?,?,?,?)
            """, (raw_id, self.user_id, namespace, content, digest, _utc_now_ms()))
        return raw_id

    def drill_down(self, raw_id: str | None = None, *, fact_id: str | None = None) -> dict[str, Any] | None:
        """Explicitly fetch raw source text.  This is never part of ``context``."""
        if fact_id is not None and raw_id is None:
            fact = self.get(fact_id)
            if not fact:
                return None
            raw_id = fact["source_id"]
        if not raw_id:
            return None
        with self._connect() as db:
            row = db.execute("SELECT * FROM raw_drilldown WHERE user_id=? AND id=?",
                             (self.user_id, str(raw_id))).fetchone()
        if row is None:
            return None
        return {"id": row["id"], "namespace": row["namespace"],
                "raw_content": row["raw_content"], "sha256_hash": row["sha256_hash"],
                "created_at": row["created_at"]}

    # ------------------------------------------------------------------
    # Rolling summaries
    # ------------------------------------------------------------------
    def set_summary(self, namespace: str, text: str, *,
                    embedding: list[float] | None = None) -> dict[str, Any]:
        namespace = _normalize_namespace(namespace)
        text = str(text).strip()
        if not text:
            raise ValueError("summary cannot be empty")
        if estimate_tokens(text) > SUMMARY_TOKEN_LIMIT:
            raise ValueError(f"summary must be at most {SUMMARY_TOKEN_LIMIT} tokens")
        tokens = estimate_tokens(text)
        encoded = pack_vector(embedding) if embedding is not None else None
        now = _utc_now_ms()
        with self._connect() as db:
            db.execute("""
                INSERT INTO rolling_summaries(user_id,namespace,summary_text,token_count,embedding,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(user_id,namespace) DO UPDATE SET
                    summary_text=excluded.summary_text,
                    token_count=excluded.token_count,
                    embedding=excluded.embedding,
                    updated_at=excluded.updated_at
            """, (self.user_id, namespace, text, tokens, encoded, now))
        return {"namespace": namespace, "summary_text": text, "token_count": tokens, "updated_at": now}

    def summarize_namespace(self, namespace: str, *, max_tokens: int = SUMMARY_TOKEN_LIMIT,
                            summarize=None) -> dict[str, Any] | None:
        """Build a deterministic compact summary from this namespace's active facts.

        Pass ``summarize`` (a callable receiving a list of fact dicts) to replace
        the deterministic fallback with a user-controlled summarizer.
        """
        namespace = _normalize_namespace(namespace)
        if max_tokens < 1 or max_tokens > SUMMARY_TOKEN_LIMIT:
            raise ValueError(f"max_tokens must be between 1 and {SUMMARY_TOKEN_LIMIT}")
        facts = self.list(namespace=namespace)
        if not facts:
            return None
        if summarize is not None:
            text = str(summarize(facts)).strip()
        else:
            lines: list[str] = []
            used = 0
            for fact in facts:
                line = f"{fact['slot']}={fact['value']}"
                cost = estimate_tokens(line)
                if used + cost > max_tokens:
                    continue
                lines.append(line)
                used += cost
            text = "; ".join(lines)
        text = truncate_tokens(text, max_tokens)
        return self.set_summary(namespace, text)

    def summary(self, namespace: str) -> dict[str, Any] | None:
        namespace = _normalize_namespace(namespace)
        with self._connect() as db:
            row = db.execute("SELECT * FROM rolling_summaries WHERE user_id=? AND namespace=?",
                             (self.user_id, namespace)).fetchone()
        if row is None:
            return None
        return {"namespace": row["namespace"], "summary_text": row["summary_text"],
                "token_count": row["token_count"], "has_embedding": bool(row["embedding"]),
                "updated_at": row["updated_at"]}

    # ------------------------------------------------------------------
    # Retrieval candidates (used by ContextCompiler)
    # ------------------------------------------------------------------
    def candidate_facts(self, db: sqlite3.Connection, terms: set[str], namespace: str | None,
                        semantic_ids: set[str], query_embedding: list[float] | None) -> list[sqlite3.Row]:
        rows: dict[str, sqlite3.Row] = {}
        if namespace:
            for row in db.execute("""
                SELECT * FROM atomic_facts
                 WHERE user_id=? AND namespace=? AND tombstone=0
                 ORDER BY updated_at DESC LIMIT 96
            """, (self.user_id, namespace)):
                rows[row["id"]] = row
        if terms and self._fts:
            try:
                for row in db.execute("""
                    SELECT f.* FROM atomic_facts_fts
                    JOIN atomic_facts f ON f.rowid=atomic_facts_fts.rowid
                   WHERE atomic_facts_fts MATCH ? AND f.user_id=? AND f.tombstone=0
                   ORDER BY bm25(atomic_facts_fts) LIMIT 32
                """, (_fts_query(terms), self.user_id)):
                    rows[row["id"]] = row
            except sqlite3.OperationalError:
                pass
        if semantic_ids:
            ids = [item for item in list(semantic_ids)[:48] if isinstance(item, str)]
            if ids:
                placeholders = ",".join("?" for _ in ids)
                for row in db.execute(
                    f"SELECT * FROM atomic_facts WHERE user_id=? AND tombstone=0 AND id IN ({placeholders})",
                    (self.user_id, *ids)):
                    rows[row["id"]] = row
        if query_embedding:
            for row in db.execute("""
                SELECT * FROM atomic_facts
                 WHERE user_id=? AND tombstone=0 AND embedding IS NOT NULL
                 ORDER BY updated_at DESC LIMIT 512
            """, (self.user_id,)):
                rows[row["id"]] = row
        if not rows:
            for row in db.execute("""
                SELECT * FROM atomic_facts
                 WHERE user_id=? AND tombstone=0
                 ORDER BY updated_at DESC LIMIT 96
            """, (self.user_id,)):
                rows[row["id"]] = row
        return list(rows.values())

    def candidate_summaries(self, db: sqlite3.Connection, terms: set[str], namespace: str | None,
                            query_embedding: list[float] | None) -> list[sqlite3.Row]:
        rows: dict[str, sqlite3.Row] = {}
        if namespace:
            row = db.execute("SELECT * FROM rolling_summaries WHERE user_id=? AND namespace=?",
                             (self.user_id, namespace)).fetchone()
            if row:
                rows[row["namespace"]] = row
        if terms and self._fts:
            try:
                for row in db.execute("""
                    SELECT s.* FROM rolling_summaries_fts
                    JOIN rolling_summaries s ON s.rowid=rolling_summaries_fts.rowid
                   WHERE rolling_summaries_fts MATCH ? AND s.user_id=?
                   ORDER BY bm25(rolling_summaries_fts) LIMIT 8
                """, (_fts_query(terms), self.user_id)):
                    rows[row["namespace"]] = row
            except sqlite3.OperationalError:
                pass
        if query_embedding:
            for row in db.execute("""
                SELECT * FROM rolling_summaries
                 WHERE user_id=? AND embedding IS NOT NULL
                 ORDER BY updated_at DESC LIMIT 64
            """, (self.user_id,)):
                rows[row["namespace"]] = row
        if not rows:
            for row in db.execute("""
                SELECT * FROM rolling_summaries
                 WHERE user_id=? ORDER BY updated_at DESC LIMIT 8
            """, (self.user_id,)):
                rows[row["namespace"]] = row
        return list(rows.values())

    def namespace_has_sensitive(self, db: sqlite3.Connection, namespace: str) -> bool:
        return db.execute("""
            SELECT 1 FROM atomic_facts
             WHERE user_id=? AND namespace=? AND tombstone=0
               AND sensitivity IN ('CONFIDENTIAL','SECRET') LIMIT 1
        """, (self.user_id, namespace)).fetchone() is not None

    # ------------------------------------------------------------------
    # Public compiler facade
    # ------------------------------------------------------------------
    def context(self, query: str, *, provider: str, token_budget: int = DEFAULT_CONTEXT_BUDGET,
                namespace: str | None = None,
                semantic_scores: dict[str, float] | None = None,
                query_embedding: list[float] | None = None,
                strict_namespace: bool = False) -> dict[str, Any]:
        """Compile a deterministic ``<memty_state>`` block within ``token_budget``."""
        from ..context.compiler import ContextCompiler
        return ContextCompiler(self).compile(
            query, provider=provider, token_budget=token_budget, namespace=namespace,
            semantic_scores=semantic_scores, query_embedding=query_embedding,
            strict_namespace=strict_namespace)

    def context_selected(self, namespace: str, fact_ids: list[str], *, provider: str,
                         token_budget: int = 2000) -> dict[str, Any]:
        """Compile only the specified facts in order, applying the normal privacy gate."""
        from ..context.compiler import ContextCompiler
        return ContextCompiler(self).compile_selected(namespace, fact_ids, provider=provider,
                                                       token_budget=token_budget)

    def rehydrate(self, text: str, redactions: dict[str, str]) -> str:
        """Put redacted values back into provider output before showing the user."""
        for placeholder, original in (redactions or {}).items():
            text = text.replace(placeholder, original)
        return text

    def rehydrate_stream(self, chunks: Iterator[str], redactions: dict[str, str]) -> Iterator[str]:
        """Rehydrate streamed provider chunks without losing split placeholders."""
        replacements = {
            str(placeholder): str(original)
            for placeholder, original in (redactions or {}).items()
            if str(placeholder)
        }
        if not replacements:
            yield from chunks
            return

        pending = ""
        keep = max(len(placeholder) for placeholder in replacements) - 1
        for chunk in chunks:
            pending += str(chunk)
            if len(pending) <= keep:
                continue
            safe, pending = pending[:-keep], pending[-keep:] if keep else ""
            yield self.rehydrate(safe, replacements)
        if pending:
            yield self.rehydrate(pending, replacements)

    # ------------------------------------------------------------------
    # Agent proposal inbox
    # ------------------------------------------------------------------
    @staticmethod
    def _proposal(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "namespace": row["namespace"], "slot": row["slot"],
                "value": row["value"], "previous_value": row["previous_value"],
                "previous_state": row["previous_state"], "sensitivity": row["sensitivity"],
                "proposed_by": row["proposed_by"], "reason": row["reason"],
                "status": row["status"], "created_at": row["created_at"],
                "resolved_at": row["resolved_at"]}

    def propose(self, namespace: str, slot: str, value: str, *, proposed_by: str = "agent",
                sensitivity: str = "PUBLIC", reason: str = "") -> dict[str, Any]:
        """Let an agent suggest a fact without letting it overwrite the user's memory.

        * Same value as the active fact: nothing happens (``unchanged``).
        * Brand-new slot: saved as ``EXTRACTED`` (low trust; it can never
          override a confirmed fact) and reported as ``applied``.
        * Any change to an existing or deleted slot: staged in the inbox as
          ``pending_review`` until the user runs ``memty approve`` or ``reject``.

        The result never echoes the existing value, which may be confidential.
        """
        namespace, slot = _normalize_namespace(namespace), _normalize_slot(slot)
        value = str(value).strip()
        if not value:
            raise ValueError("value cannot be empty")
        if estimate_tokens(value) > FACT_TOKEN_LIMIT:
            raise ValueError(f"atomic fact must be at most {FACT_TOKEN_LIMIT} tokens")
        sensitivity = str(sensitivity).upper()
        if sensitivity not in _SENSITIVITY_LEVELS:
            raise ValueError("sensitivity must be PUBLIC, INTERNAL, CONFIDENTIAL or SECRET")
        if looks_like_credential(value):
            sensitivity = "SECRET"
        proposed_by = _client_name(proposed_by, "agent")
        reason = " ".join(str(reason or "").split())[:200]
        base = {"namespace": namespace, "slot": slot, "proposed_by": proposed_by}

        current = self.find(namespace, slot)
        if current and not current["tombstone"] and current["value"] == value:
            return {**base, "status": "unchanged"}
        if current is None:
            try:
                self.record(namespace, slot, value, verification_state="EXTRACTED",
                            sensitivity=sensitivity, source_id="agent:" + proposed_by,
                            create_only=True)
                return {**base, "status": "applied", "verification_state": "EXTRACTED"}
            except LockedSlot:  # created concurrently: review it like any other change
                current = self.find(namespace, slot)

        now = _utc_now_ms()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            duplicate = db.execute("""
                SELECT id FROM fact_proposals
                 WHERE user_id=? AND namespace=? AND slot=? AND value=? AND status='PENDING'
            """, (self.user_id, namespace, slot, value)).fetchone()
            if duplicate:
                db.execute("ROLLBACK")
                return {**base, "status": "pending_review", "proposal_id": duplicate["id"],
                        "duplicate": True}
            # Only the newest suggestion for a slot stays open.
            db.execute("""
                UPDATE fact_proposals SET status='SUPERSEDED', resolved_at=?
                 WHERE user_id=? AND namespace=? AND slot=? AND status='PENDING'
            """, (now, self.user_id, namespace, slot))
            deleted = bool(current and current["tombstone"])
            cursor = db.execute("""
                INSERT INTO fact_proposals(user_id,namespace,slot,value,previous_value,previous_state,
                                           sensitivity,proposed_by,reason,status,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,'PENDING',?)
            """, (self.user_id, namespace, slot, value,
                  None if not current or deleted else current["value"],
                  "DELETED" if deleted else (current["verification_state"] if current else None),
                  sensitivity, proposed_by, reason, now))
            proposal_id = cursor.lastrowid
            db.execute("COMMIT")
        return {**base, "status": "pending_review", "proposal_id": proposal_id}

    def proposals(self, *, status: str | None = "PENDING", limit: int = 100) -> list[dict[str, Any]]:
        """List proposals, oldest first (``status=None`` lists every state)."""
        params: list[Any] = [self.user_id]
        query = "SELECT * FROM fact_proposals WHERE user_id=?"
        if status is not None:
            status = str(status).upper()
            if status not in _PROPOSAL_STATES:
                raise ValueError("status must be PENDING, APPROVED, REJECTED or SUPERSEDED")
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY id LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._proposal(row) for row in rows]

    def resolve_proposal(self, proposal_id: int, *, approve: bool) -> dict[str, Any]:
        """Approve (save as USER_CONFIRMED) or reject one pending proposal."""
        try:
            proposal_id = int(proposal_id)
        except (TypeError, ValueError) as error:
            raise ValueError("proposal id must be a number") from error
        with self._connect() as db:
            row = db.execute("SELECT * FROM fact_proposals WHERE user_id=? AND id=?",
                             (self.user_id, proposal_id)).fetchone()
        if row is None:
            raise ValueError(f"proposal {proposal_id} not found")
        if row["status"] != "PENDING":
            raise ValueError(f"proposal {proposal_id} is already {row['status'].lower()}")
        fact = None
        if approve:
            current = self.find(row["namespace"], row["slot"])
            sensitivity = row["sensitivity"]
            allowed = blocked = None
            ephemeral = False
            if current:
                # Approving a new value never weakens the slot's existing privacy policy.
                if _SENSITIVITY_RANK[current["sensitivity"]] > _SENSITIVITY_RANK[sensitivity]:
                    sensitivity = current["sensitivity"]
                allowed, blocked = current["allowed_providers"], current["blocked_providers"]
                ephemeral = current["ephemeral_redaction"]
            fact = self.record(row["namespace"], row["slot"], row["value"],
                               verification_state="USER_CONFIRMED", sensitivity=sensitivity,
                               allowed_providers=allowed, blocked_providers=blocked,
                               ephemeral_redaction=ephemeral,
                               source_id="agent:" + row["proposed_by"])
        now = _utc_now_ms()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE fact_proposals SET status=?, resolved_at=? WHERE user_id=? AND id=?",
                       ("APPROVED" if approve else "REJECTED", now, self.user_id, proposal_id))
            db.execute("COMMIT")
        result = {"id": proposal_id, "status": "approved" if approve else "rejected",
                  "namespace": row["namespace"], "slot": row["slot"], "value": row["value"]}
        if fact is not None:
            result["version"] = fact["version"]
        return result

    # ------------------------------------------------------------------
    # Context receipts
    # ------------------------------------------------------------------
    def log_receipt(self, channel: str, provider: str, *, fact_ids: list[str] | None = None,
                    tokens_injected: int = 0, namespace: str | None = None,
                    client: str | None = None, redacted: int = 0,
                    secrets_blocked: int = 0) -> dict[str, Any]:
        """Record that a capsule was served: counts and slot names only, never values.

        ``baseline_tokens`` approximates what the same request would cost
        without the compiler: every active fact in the touched namespaces plus
        their archived raw sources, at ~4 characters per token.  It is a
        conservative local estimate, not a provider measurement.
        """
        channel = str(channel).casefold()
        if channel not in _RECEIPT_CHANNELS:
            raise ValueError("channel must be recall, mcp, web or clip")
        provider = _client_name(provider, "unknown")
        client = _client_name(client, provider) if client else provider
        namespace = _normalize_namespace(namespace) if namespace else None
        ids = list(dict.fromkeys(item for item in (fact_ids or []) if isinstance(item, str)))[:64]
        tokens_injected = max(0, int(tokens_injected))
        now = _utc_now_ms()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows: list[sqlite3.Row] = []
            if ids:
                placeholders = ",".join("?" for _ in ids)
                rows = db.execute(f"""
                    SELECT id, namespace, slot, verification_state FROM atomic_facts
                     WHERE user_id=? AND id IN ({placeholders})
                """, (self.user_id, *ids)).fetchall()
            for row in rows:
                db.execute("""
                    INSERT INTO fact_usage(fact_id,user_id,hit_count,last_hit_at) VALUES(?,?,1,?)
                    ON CONFLICT(fact_id) DO UPDATE SET hit_count=hit_count+1,
                                                       last_hit_at=excluded.last_hit_at
                """, (row["id"], self.user_id, now))
            baseline = 0
            namespaces = sorted({row["namespace"] for row in rows})
            if namespaces:
                placeholders = ",".join("?" for _ in namespaces)
                fact_chars = db.execute(f"""
                    SELECT COALESCE(SUM(LENGTH(namespace)+LENGTH(slot)+LENGTH(value)+4),0) AS n
                      FROM atomic_facts
                     WHERE user_id=? AND tombstone=0 AND namespace IN ({placeholders})
                """, (self.user_id, *namespaces)).fetchone()["n"]
                raw_chars = db.execute(f"""
                    SELECT COALESCE(SUM(LENGTH(raw_content)),0) AS n FROM raw_drilldown
                     WHERE user_id=? AND id IN (
                        SELECT source_id FROM atomic_facts
                         WHERE user_id=? AND tombstone=0 AND source_id IS NOT NULL
                           AND namespace IN ({placeholders}))
                """, (self.user_id, self.user_id, *namespaces)).fetchone()["n"]
                baseline = (int(fact_chars) + int(raw_chars) + 3) // 4
            slots = [f"{row['namespace']}.{row['slot']}" for row in rows]
            verified = sum(1 for row in rows
                           if row["verification_state"] in {"USER_CONFIRMED", "SPEC_LOCKED"})
            cursor = db.execute("""
                INSERT INTO context_receipts(user_id,created_at,channel,provider,client,namespace,
                    tokens_injected,baseline_tokens,facts_injected,verified_facts,redacted,
                    secrets_blocked,slots_used)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (self.user_id, now, channel, provider, client, namespace, tokens_injected,
                  baseline, len(rows), verified, max(0, int(redacted)),
                  max(0, int(secrets_blocked)), json.dumps(slots)))
            seq = int(cursor.lastrowid or 0)
            if seq and seq % 1000 == 0:
                db.execute("DELETE FROM context_receipts WHERE user_id=? AND seq<=?",
                           (self.user_id, seq - MAX_RECEIPTS))
            db.execute("COMMIT")
        return {"seq": seq, "channel": channel, "client": client, "facts_injected": len(rows),
                "tokens_injected": tokens_injected, "baseline_tokens": baseline,
                "secrets_blocked": max(0, int(secrets_blocked))}

    def receipts(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """Most recent receipts first."""
        with self._connect() as db:
            rows = db.execute("""
                SELECT * FROM context_receipts WHERE user_id=? ORDER BY seq DESC LIMIT ?
            """, (self.user_id, max(1, min(int(limit), 1000)))).fetchall()
        result = []
        for row in rows:
            item = {key: row[key] for key in row.keys() if key not in {"user_id", "slots_used"}}
            item["slots_used"] = _json_list(row["slots_used"])
            result.append(item)
        return result

    def report(self, *, since_ms: int | None = None) -> dict[str, Any]:
        """Aggregate receipts into the trust summary printed by ``memty report``."""
        since = max(0, int(since_ms or 0))
        with self._connect() as db:
            totals = db.execute("""
                SELECT COUNT(*) AS requests,
                       COALESCE(SUM(CASE WHEN facts_injected>0 THEN 1 ELSE 0 END),0) AS served,
                       COALESCE(SUM(facts_injected),0) AS facts,
                       COALESCE(SUM(verified_facts),0) AS verified,
                       COALESCE(SUM(tokens_injected),0) AS injected,
                       COALESCE(SUM(baseline_tokens),0) AS baseline,
                       COALESCE(SUM(MAX(baseline_tokens-tokens_injected,0)),0) AS saved,
                       COALESCE(SUM(redacted),0) AS redacted,
                       COALESCE(SUM(secrets_blocked),0) AS blocked,
                       MIN(created_at) AS first_at, MAX(created_at) AS last_at
                  FROM context_receipts WHERE user_id=? AND created_at>=?
            """, (self.user_id, since)).fetchone()
            clients = db.execute("""
                SELECT client, COUNT(*) AS n FROM context_receipts
                 WHERE user_id=? AND created_at>=? AND facts_injected>0
                 GROUP BY client ORDER BY n DESC, client
            """, (self.user_id, since)).fetchall()
            channels = db.execute("""
                SELECT channel, COUNT(*) AS n FROM context_receipts
                 WHERE user_id=? AND created_at>=? AND facts_injected>0
                 GROUP BY channel ORDER BY n DESC, channel
            """, (self.user_id, since)).fetchall()
            reused = db.execute("""
                SELECT COUNT(*) AS total,
                       COALESCE(SUM(CASE WHEN f.verification_state IN ('USER_CONFIRMED','SPEC_LOCKED')
                                    THEN 1 ELSE 0 END),0) AS verified
                  FROM fact_usage u JOIN atomic_facts f ON f.id=u.fact_id
                 WHERE u.user_id=? AND u.hit_count>0 AND u.last_hit_at>=? AND f.tombstone=0
            """, (self.user_id, since)).fetchone()
            top = db.execute("""
                SELECT f.namespace, f.slot, u.hit_count FROM fact_usage u
                  JOIN atomic_facts f ON f.id=u.fact_id
                 WHERE u.user_id=? AND f.tombstone=0 AND u.last_hit_at>=?
                 ORDER BY u.hit_count DESC, u.last_hit_at DESC LIMIT 5
            """, (self.user_id, since)).fetchall()
            secret_slots = db.execute("""
                SELECT COUNT(*) AS n FROM atomic_facts
                 WHERE user_id=? AND tombstone=0 AND sensitivity='SECRET'
            """, (self.user_id,)).fetchone()["n"]
            pending = db.execute(
                "SELECT COUNT(*) AS n FROM fact_proposals WHERE user_id=? AND status='PENDING'",
                (self.user_id,)).fetchone()["n"]
        return {"capsules_served": int(totals["served"]), "requests": int(totals["requests"]),
                "clients": {row["client"]: row["n"] for row in clients},
                "channels": {row["channel"]: row["n"] for row in channels},
                "fact_injections": int(totals["facts"]),
                "verified_fact_injections": int(totals["verified"]),
                "distinct_facts_reused": int(reused["total"]),
                "distinct_verified_facts_reused": int(reused["verified"]),
                "tokens_injected": int(totals["injected"]),
                "baseline_tokens": int(totals["baseline"]),
                "tokens_saved_estimate": int(totals["saved"]),
                "values_redacted": int(totals["redacted"]),
                "secret_requests_blocked": int(totals["blocked"]),
                "secret_slots_protected": int(secret_slots),
                "pending_proposals": int(pending),
                "top_facts": [{"slot": f"{row['namespace']}.{row['slot']}", "hits": row["hit_count"]}
                              for row in top],
                "first_at": totals["first_at"], "last_at": totals["last_at"],
                "since": since or None}

    # ------------------------------------------------------------------
    # Inspectable stats and explicit close hook
    # ------------------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        with self._connect() as db:
            facts = db.execute("SELECT COUNT(*) AS n FROM atomic_facts WHERE user_id=? AND tombstone=0",
                               (self.user_id,)).fetchone()["n"]
            tombstones = db.execute("SELECT COUNT(*) AS n FROM atomic_facts WHERE user_id=? AND tombstone=1",
                                    (self.user_id,)).fetchone()["n"]
            summaries = db.execute("SELECT COUNT(*) AS n FROM rolling_summaries WHERE user_id=?",
                                   (self.user_id,)).fetchone()["n"]
            constraints = db.execute(
                "SELECT COUNT(*) AS n FROM logical_constraints WHERE user_id=?",
                (self.user_id,)).fetchone()["n"]
            raw = db.execute("SELECT COUNT(*) AS n FROM raw_drilldown WHERE user_id=?",
                             (self.user_id,)).fetchone()["n"]
            audit = db.execute("SELECT COUNT(*) AS n FROM atomic_fact_audit WHERE user_id=?",
                               (self.user_id,)).fetchone()["n"]
            pending = db.execute(
                "SELECT COUNT(*) AS n FROM fact_proposals WHERE user_id=? AND status='PENDING'",
                (self.user_id,)).fetchone()["n"]
            receipts = db.execute("SELECT COUNT(*) AS n FROM context_receipts WHERE user_id=?",
                                  (self.user_id,)).fetchone()["n"]
        return {"path": str(self.path), "user_id": self.user_id, "active_facts": facts,
                "tombstones": tombstones, "constraints": constraints, "summaries": summaries,
                "raw_documents": raw,
                "audit_versions": audit, "pending_proposals": pending, "receipts": receipts,
                "fts5": self._fts}

    def __enter__(self) -> "MemtyLedger":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
