"""Localhost HTTP bridge so browser assistants can use the local Memty vault.

``memty serve --port 8765`` binds strictly to ``127.0.0.1``. A localhost
server is reachable by *every* web page the user opens, so it is locked down:

* **Pairing token**: every data route needs ``Authorization: Bearer <token>``.
  The token lives beside the vault (``<db>.web-token``, owner-only). The
  extension pairs itself through ``POST /pair`` (trust on first use): the first
  browser-extension origin to ask is remembered, and only that origin can fetch
  the token again. ``memty serve --new-token`` rotates the token and forgets it.
* **Origin allow-list**: requests from web pages (``https://...``) are refused;
  only browser-extension origins (or an explicit ``--allow-origin``) are accepted.
* **Host check**: the ``Host`` header must be ``127.0.0.1``/``localhost`` on our
  port, which defeats DNS-rebinding attacks.
* **JSON only**: writes need ``Content-Type: application/json``, which a page
  cannot send cross-origin without a (refused) preflight.

Capsules are compiled for the calling assistant as a *cloud* provider, so the
ledger's sensitivity rules apply: CONFIDENTIAL values are redacted, SECRET facts
are refused, and redaction maps are never sent to the browser.
"""
from __future__ import annotations

import hashlib
import hmac
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time
from urllib import request as urlrequest
from urllib.parse import parse_qs, urlsplit

from ...context.privacy import LocalRoutingRequired
from ...context.render import render_plain_with_count, slot_label
from ...extraction.atomic_facts import MAX_INPUT_CHARS, extract_facts
from ...vault.ledger import (LOCAL_PROVIDERS, LockedSlot, TombstonedSlot, _CONTEXT_SLOT_SUFFIX,
                             _normalize_slot)
from ...vault.tokens import estimate_tokens
from ...trust.receipts import log_blocked, log_served

DEFAULT_PORT = 8765
WEB_CAPSULE_TOKENS = 350
# Compile with headroom, then trim the readable text to the real budget, so the
# compiler's XML section caps never hide facts that would fit as plain lines.
TEXT_COMPILE_BUDGET = 1500
PRIVATE = {"INTERNAL", "CONFIDENTIAL", "SECRET"}
MAX_BODY = 256 * 1024
MAX_SAVE = 25
EXTENSION_SCHEMES = ("chrome-extension://", "moz-extension://", "safari-web-extension://")
SAVE_BATCH_PREFIX = "save_"
CONTEXT_BATCH = re.compile(r"save_(?:[0-9a-f]{16}|[0-9a-f]{24})$")
# Saves made before batch ids existed: facts written this close to the newest one
# count as the same save.
LEGACY_BATCH_WINDOW_MS = 5_000


def latest_batch(facts: list[dict]) -> list[dict]:
    """The facts from the most recent save.

    One Save click comes back in the order it was saved; facts without a batch id
    (older saves, CLI writes) come back newest first, so trimming drops the oldest.
    """
    if not facts:
        return []
    when = lambda f: int(f["updated_at"] or 0)  # noqa: E731
    newest = max(facts, key=when)
    source = str(newest.get("source_id") or "")
    if source.startswith(SAVE_BATCH_PREFIX):
        return sorted((f for f in facts if f.get("source_id") == source), key=when)
    cutoff = when(newest) - LEGACY_BATCH_WINDOW_MS
    return sorted((f for f in facts if when(f) >= cutoff
                   and not str(f.get("source_id") or "").startswith(SAVE_BATCH_PREFIX)),
                  key=when, reverse=True)


def context_groups(facts: list[dict]) -> list[dict]:
    """Group browser saves; older ungrouped facts stay separate."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for fact in facts:
        source = str(fact.get("source_id") or "")
        context_id = source if CONTEXT_BATCH.fullmatch(source) else "legacy_" + fact["id"]
        groups.setdefault((fact["namespace"], context_id), []).append(fact)
    result = []
    for (namespace, context_id), items in groups.items():
        def order(fact):
            match = _CONTEXT_SLOT_SUFFIX.search(fact["slot"])
            return (int(match.group(2), 16) if match else 256,
                    int(fact["updated_at"] or 0), fact["slot"])
        items.sort(key=order)
        new_format = any(_CONTEXT_SLOT_SUFFIX.search(fact["slot"]) for fact in items)
        timestamp = max(int(fact["created_at" if new_format else "updated_at"] or 0) for fact in items)
        sort_time = (int(context_id[5:21], 16) if new_format and len(context_id) == 29
                     else timestamp * 1_000_000)
        if new_format and len(context_id) == 29:
            timestamp = sort_time // 1_000_000
        result.append({"id": context_id, "namespace": namespace, "updated_at": timestamp,
                       "sort_time": sort_time, "facts": items})
    return sorted(result, key=lambda group: (-group["sort_time"], group["namespace"], group["id"]))


def context_preview(facts: list[dict], provider: str) -> str:
    """Describe a context without exposing restricted or private values."""
    provider = provider.casefold()
    for fact in facts:
        allowed = {item.casefold() for item in fact["allowed_providers"]}
        blocked = {item.casefold() for item in fact["blocked_providers"]}
        if (fact["sensitivity"] != "PUBLIC" or fact["ephemeral_redaction"] or provider in blocked
                or (allowed and provider not in allowed)):
            continue
        value = " ".join(fact["value"].split())
        if len(value) > 100:
            value = value[:100].rsplit(" ", 1)[0] + "…"
        return f"{slot_label(fact['slot'])}: {value}"
    return "Private context"


def web_provider(value) -> str:
    """The provider name a browser caller asked for, which can never be a local model.

    The capsule goes into a cloud chat box, so letting the caller say "ollama"
    would switch the privacy gate to local mode and release SECRET facts.
    """
    provider = str(value or "").strip() or "web"
    if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", provider):
        raise ValueError("invalid provider")
    if provider.casefold() in LOCAL_PROVIDERS:
        raise ValueError("a web assistant cannot use a local provider name")
    return provider


def token_path(db: str | Path) -> Path:
    db = Path(db).expanduser()
    return db.with_name(db.name + ".web-token")


def vault_identity(db: str | Path) -> str:
    """Identify a local vault without exposing its path on the health endpoint."""
    return hashlib.sha256(os.path.normcase(str(Path(db).expanduser().resolve())).encode("utf-8")).hexdigest()


def state_path(db: str | Path) -> Path:
    db = Path(db).expanduser()
    return db.with_name(db.name + ".web-bridge.json")


def paired_path(db: str | Path) -> Path:
    db = Path(db).expanduser()
    return db.with_name(db.name + ".web-paired.json")


PAIR_WINDOW_SECONDS = 120
MAX_PAIRED = 5


def _read_paired(db: str | Path) -> dict:
    try:
        value = json.loads(paired_path(db).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def paired_origins(db: str | Path) -> list[str]:
    return [str(item) for item in _read_paired(db).get("origins", [])]


def pairing_open(db: str | Path) -> bool:
    return float(_read_paired(db).get("open_until", 0)) > time.time()


def _write_paired(db: str | Path, origins: list[str], open_until: float = 0) -> None:
    path = paired_path(db)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump({"origins": origins, "open_until": open_until}, stream)
    os.replace(temp, path)


def open_pairing(db: str | Path, seconds: int = PAIR_WINDOW_SECONDS) -> float:
    """Let one more browser extension pair during the next ``seconds`` (``memty pair``).

    Needs a local terminal, so a web page or another extension can't open it.
    The running bridge reads this file on every pairing request: no restart needed.
    """
    until = time.time() + seconds
    _write_paired(db, paired_origins(db), until)
    return until


def load_or_create_token(db: str | Path, *, rotate: bool = False) -> str:
    """Return the pairing token, creating an owner-only token file if needed."""
    path = token_path(db)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rotate:
        try:
            token = path.read_text(encoding="utf-8").strip()
            if len(token) >= 32:
                return token
        except OSError:
            pass
    token = secrets.token_urlsafe(32)
    if rotate:  # a new token also forgets which extension was paired
        try:
            paired_path(db).unlink()
        except OSError:
            pass
    temp = path.with_name(path.name + f".{os.getpid()}.tmp")
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(token + "\n")
    os.replace(temp, path)
    return token


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, ledger, token: str, *, port: int = DEFAULT_PORT,
                 allowed_origins: list[str] | None = None, quiet: bool = True,
                 db: str | Path | None = None):
        self.ledger = ledger
        self.token = token
        self.db = db or getattr(ledger, "path", None)
        self.pair_lock = threading.Lock()
        self.allowed_origins = {o.rstrip("/") for o in (allowed_origins or [])}
        self.quiet = quiet
        # Never configurable: the bridge must not be reachable from the network.
        super().__init__(("127.0.0.1", port), BridgeHandler)

    def server_bind(self) -> None:
        # HTTPServer.server_bind calls socket.getfqdn(), a reverse-DNS lookup that can
        # stall for 30+ seconds (seen on macOS). A loopback-only bridge needs no hostname.
        import socketserver
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]

    @property
    def port(self) -> int:
        return self.server_address[1]

    def origin_allowed(self, origin: str | None) -> bool:
        if origin is None:
            return True  # Not a browser cross-origin request (CLI, curl); token still required.
        origin = origin.rstrip("/")
        if self.allowed_origins:
            return origin in self.allowed_origins
        return origin.startswith(EXTENSION_SCHEMES)


class BridgeHandler(BaseHTTPRequestHandler):
    server: BridgeServer
    server_version = "memty-bridge"
    sys_version = ""

    # -- plumbing -----------------------------------------------------
    def log_message(self, format, *args):  # noqa: A002 - stdlib signature
        if not self.server.quiet:  # Never logs bodies, tokens, or query strings.
            sys.stderr.write("%s %s\n" % (self.command, urlsplit(self.path).path))

    def _send(self, status: int, body: dict, origin_ok: bool = True) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Vary", "Origin")
        origin = self.headers.get("Origin")
        if origin and origin_ok:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status: int, error: str, message: str, **extra) -> None:
        self._send(status, {"error": error, "message": message, **extra})

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        return host in {f"127.0.0.1:{self.server.port}", f"localhost:{self.server.port}"}

    def _guard(self, *, auth: bool = True) -> bool:
        if not self._host_ok():
            self._send(HTTPStatus.FORBIDDEN, {"error": "bad_host",
                       "message": "Use http://127.0.0.1:%d" % self.server.port}, origin_ok=False)
            return False
        if not self.server.origin_allowed(self.headers.get("Origin")):
            self._send(HTTPStatus.FORBIDDEN, {"error": "origin_not_allowed",
                       "message": "Only the Memty browser extension may call this bridge."}, origin_ok=False)
            return False
        if auth:
            supplied = self.headers.get("Authorization", "")
            expected = "Bearer " + self.server.token
            if not hmac.compare_digest(supplied.encode(), expected.encode()):
                self._error(HTTPStatus.UNAUTHORIZED, "unauthorized",
                            "Missing or wrong pairing token. Run: memty serve --show-token")
                return False
        return True

    def _json_body(self) -> dict | None:
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            self._error(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, "json_required", "Send application/json.")
            return None
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        if length < 0 or length > MAX_BODY:
            # Drain (bounded) so Windows does not reset the socket before the 413 arrives.
            remaining = min(max(length, 0), 16 * MAX_BODY)
            while remaining > 0 and (chunk := self.rfile.read(min(remaining, 65536))):
                remaining -= len(chunk)
            self.close_connection = True
            self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "too_large", "Request body is too large.")
            return None
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = None
        if not isinstance(body, dict):
            self._error(HTTPStatus.BAD_REQUEST, "bad_json", "Body must be a JSON object.")
            return None
        return body

    # -- verbs ----------------------------------------------------------
    def do_OPTIONS(self):  # CORS preflight
        origin = self.headers.get("Origin")
        if not self._host_ok() or origin is None or not self.server.origin_allowed(origin):
            self._send(HTTPStatus.FORBIDDEN, {"error": "origin_not_allowed"}, origin_ok=False)
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")
        if self.headers.get("Access-Control-Request-Private-Network"):
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        url = urlsplit(self.path)
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        if url.path == "/health":
            if self._guard(auth=False):
                self._send(HTTPStatus.OK, {"ok": True, "service": "memty"})
            return
        if not self._guard():
            return
        try:
            if url.path == "/capsule":
                self._capsule(query)
            elif url.path == "/contexts":
                self._contexts(query)
            elif url.path == "/identity":
                if self.server.db is None:
                    raise ValueError("bridge vault is unavailable")
                user = getattr(self.server.ledger, "user_id", "local")
                self._send(HTTPStatus.OK, {"vault": vault_identity(self.server.db),
                                           "user": user if isinstance(user, str) else "local",
                                           "pid": os.getpid()})
            elif url.path == "/facts":
                self._list_facts(query)
            elif url.path == "/namespaces":
                counts: dict[str, int] = {}
                for fact in self.server.ledger.list():
                    counts[fact["namespace"]] = counts.get(fact["namespace"], 0) + 1
                self._send(HTTPStatus.OK, {"namespaces": sorted(counts), "counts": counts})
            else:
                self._error(HTTPStatus.NOT_FOUND, "not_found", "Unknown route.")
        except ValueError as error:
            self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(error))

    def do_POST(self):
        url = urlsplit(self.path)
        if url.path == "/pair":
            if self._guard(auth=False):
                self._pair()
            return
        if not self._guard():
            return
        body = self._json_body()
        if body is None:
            return
        try:
            if url.path == "/extract":
                text = str(body.get("text", ""))
                if not text.strip() or len(text) > MAX_INPUT_CHARS:
                    raise ValueError(f"text must be 1-{MAX_INPUT_CHARS} characters")
                self._send(HTTPStatus.OK, extract_facts(text))
            elif url.path == "/facts":
                self._save(body)
            elif url.path == "/facts/update":
                self._update(body)
            elif url.path == "/facts/delete":
                self._delete(body)
            else:
                self._error(HTTPStatus.NOT_FOUND, "not_found", "Unknown route.")
        except ValueError as error:
            self._error(HTTPStatus.BAD_REQUEST, "invalid_request", str(error))

    # -- routes ---------------------------------------------------------
    def _pair(self) -> None:
        """Hand the token to the browser extension without copy-pasting (trust on first use)."""
        origin = (self.headers.get("Origin") or "").rstrip("/")
        if not origin.startswith(EXTENSION_SCHEMES):
            self._error(HTTPStatus.FORBIDDEN, "origin_not_allowed", "Only a browser extension can pair.")
            return
        if self.server.db is None:
            self._error(HTTPStatus.CONFLICT, "pairing_unavailable",
                        "Pair manually: paste `memty serve --show-token` into the extension options.")
            return
        with self.server.pair_lock:
            origins = paired_origins(self.server.db)
            if origins and origin not in origins:
                if not pairing_open(self.server.db):
                    self._error(HTTPStatus.FORBIDDEN, "pairing_required",
                                "This browser isn't connected to Memty yet. In a terminal, run: "
                                "memty pair. Then click Try again.")
                    return
                # The user opened a pairing window: add this browser, then close the window.
                _write_paired(self.server.db, (origins + [origin])[-MAX_PAIRED:])
            elif not origins:
                _write_paired(self.server.db, [origin])
        self._send(HTTPStatus.OK, {"token": self.server.token, "port": self.server.port})

    def _capsule(self, query: dict) -> None:
        namespace = query.get("namespace", "").strip()
        if not namespace:
            raise ValueError("namespace is required")
        tokens = int(query.get("tokens", WEB_CAPSULE_TOKENS))
        context_id = query.get("context", "").strip()
        limit = 2000 if context_id else 600
        if not 1 <= tokens <= limit:
            raise ValueError(f"tokens must be between 1 and {limit}")
        provider = web_provider(query.get("provider"))
        style = query.get("format", "text")
        if style not in {"text", "xml"}:
            raise ValueError("format must be text or xml")
        if context_id:
            if style != "text":
                raise ValueError("a selected context needs format=text")
            group = next((item for item in context_groups(self.server.ledger.list(namespace=namespace))
                          if item["id"] == context_id), None)
            if group is None:
                self._error(HTTPStatus.NOT_FOUND, "context_not_found", "This context changed or was deleted. Choose it again.")
                return
            try:
                result = self.server.ledger.context_selected(
                    namespace, [fact["id"] for fact in group["facts"]], provider=provider, token_budget=tokens)
            except LocalRoutingRequired:
                log_blocked(self.server.ledger, "web", provider, namespace=namespace)
                self._error(HTTPStatus.CONFLICT, "local_routing_required",
                            "A SECRET fact in this context cannot be sent to a web assistant.")
                return
            fact_ids = result.pop("fact_ids", None) or []
            if result.get("text"):
                log_served(self.server.ledger, "web", provider, result, namespace=namespace,
                           fact_ids=fact_ids)
            self._send(HTTPStatus.OK, {**result, "namespace": namespace, "provider": provider,
                                       "context": context_id})
            return
        question = query.get("query", "").strip()
        # With no question to rank by, hand over only the most recent save: mixing
        # every earlier save into one paste confuses the chat assistant.
        scope = query.get("scope", "latest" if style == "text" and not question else "all")
        if scope not in {"latest", "all"}:
            raise ValueError("scope must be latest or all")
        if scope == "latest" and style != "text":
            raise ValueError("scope=latest needs format=text")
        try:
            result = self.server.ledger.context(
                question, provider=provider, namespace=namespace,
                token_budget=TEXT_COMPILE_BUDGET if style == "text" else tokens, strict_namespace=True)
        except LocalRoutingRequired as error:
            log_blocked(self.server.ledger, "web", provider, namespace=namespace)
            self._error(HTTPStatus.CONFLICT, "local_routing_required",
                        "A SECRET fact matched; it cannot be sent to a web assistant.",
                        namespace=error.namespace, slot=error.slot)
            return
        eligible = result.get("eligible_count", 0)
        if scope == "latest":
            # Keep the compiler's privacy decisions (redacted values, refused facts),
            # just narrowed to the latest save and shown in the order it was saved.
            order = {f["id"]: i for i, f in enumerate(latest_batch(
                self.server.ledger.list(namespace=namespace)))}
            eligible = len(order)
            kept = sorted((c for c in result["citations"] if c.get("id") in order),
                          key=lambda c: order[c["id"]])
            result = {**result, "citations": kept, "text": result["text"] if kept else ""}
        # Chat assistants read plain "Title: value" lines far better than XML slots.
        if style == "text" and result["text"]:
            text, included = render_plain_with_count(result, tokens)
        else:
            text = result["text"]
            included = result.get("injected_count", 0) if style == "xml" else 0
        if text:
            # render_plain trims from the end, so the served facts are the first `included`.
            served_ids = [item["id"] for item in result["citations"] if "id" in item][:included]
            log_served(self.server.ledger, "web", provider, result, namespace=namespace,
                       tokens=estimate_tokens(text), fact_ids=served_ids,
                       redacted=text.count("[private]") if style == "text" else None)
        # Redaction maps hold the real CONFIDENTIAL values: never send them to a browser.
        self._send(HTTPStatus.OK, {"text": text, "approx_tokens": estimate_tokens(text),
                                   "namespace": namespace, "provider": provider,
                                   "facts": included, "omitted": max(0, eligible - included),
                                   "redacted": (text.count("[private]") if style == "text" else
                                                len(result.get("redactions") or {}))})

    def _contexts(self, query: dict) -> None:
        namespace = query.get("namespace", "").strip() or None
        provider = web_provider(query.get("provider"))
        groups = context_groups(self.server.ledger.list(namespace=namespace))
        self._send(HTTPStatus.OK, {"contexts": [
            {"id": group["id"], "namespace": group["namespace"], "updated_at": group["updated_at"],
             "count": len(group["facts"]), "preview": context_preview(group["facts"], provider)}
            for group in groups]})

    # -- user-controlled fact management (view, edit, delete) -----------
    @staticmethod
    def _namespace(value) -> str:
        namespace = str(value or "").strip()
        if not namespace:
            raise ValueError("namespace is required")
        return namespace

    def _list_facts(self, query: dict) -> None:
        namespace = self._namespace(query.get("namespace"))
        facts = []
        for fact in self.server.ledger.list(namespace=namespace):
            private = fact["sensitivity"] in PRIVATE
            facts.append({
                "slot": fact["slot"],
                # Private values never reach the browser; they can still be replaced or deleted.
                "value": None if private else fact["value"],
                "private": private, "sensitivity": fact["sensitivity"],
                "source": "you" if fact["verification_state"] != "EXTRACTED" else "saved from chat",
                "updated_at": fact["updated_at"],
            })
        facts.sort(key=lambda item: -int(item["updated_at"] or 0))
        self._send(HTTPStatus.OK, {"namespace": namespace, "facts": facts})

    def _update(self, body: dict) -> None:
        """A user edit: written as USER_CONFIRMED, so chat extraction never overwrites it."""
        namespace = self._namespace(body.get("namespace"))
        slot = str(body.get("slot", "")).strip()
        new_slot = str(body.get("new_slot") or slot).strip()
        value = body.get("value")
        current = next((f for f in self.server.ledger.list(namespace=namespace) if f["slot"] == slot), None)
        suffix = _CONTEXT_SLOT_SUFFIX.search(slot) if current else None
        if suffix and new_slot != slot:
            new_slot = _normalize_slot(new_slot)[:49] + suffix.group(0)
        if value is None or not str(value).strip():
            if current is None:
                raise ValueError("value is required")
            value = current["value"]  # rename or privacy change: keep the stored value server-side
        if "private" in body and not body["private"] and current and current["sensitivity"] == "SECRET":
            # Declassifying a secret from the browser would let the browser read it back.
            raise ValueError("a secret can only be made public from the terminal: memty remember")
        if "private" in body:
            sensitivity = ((current["sensitivity"] if current and current["sensitivity"] in PRIVATE else "CONFIDENTIAL")
                           if body["private"] else "PUBLIC")
        else:
            sensitivity = current["sensitivity"] if current else "PUBLIC"
        record = self.server.ledger.record(namespace, new_slot, str(value), confidence=1.0,
                                           verification_state="USER_CONFIRMED", sensitivity=sensitivity,
                                           source_id=current.get("source_id") if current else None,
                                           allowed_providers=current.get("allowed_providers") if current else None,
                                           blocked_providers=current.get("blocked_providers") if current else None,
                                           ephemeral_redaction=current.get("ephemeral_redaction", False) if current else False,
                                           create_only=bool(suffix and new_slot != slot))
        if current is not None and record["slot"] != slot:
            self.server.ledger.forget(namespace, slot)  # renamed: remove the old title
        self._send(HTTPStatus.OK, {"namespace": namespace, "slot": record["slot"],
                                   "version": record.get("version"),
                                   "private": record["sensitivity"] in PRIVATE})

    def _delete(self, body: dict) -> None:
        namespace = self._namespace(body.get("namespace"))
        slot = str(body.get("slot", "")).strip()
        if not slot:
            raise ValueError("slot is required")
        # forget() tombstones the slot and purges its history; chat extraction can't bring it back.
        result = self.server.ledger.forget(namespace, slot)
        self._send(HTTPStatus.OK, {"namespace": namespace, "slot": slot, "deleted": result is not None})

    def _save(self, body: dict) -> None:
        namespace = str(body.get("namespace", "")).strip()
        facts = body.get("facts")
        if not namespace or not isinstance(facts, list) or not 1 <= len(facts) <= MAX_SAVE:
            raise ValueError(f"namespace and 1-{MAX_SAVE} facts are required")
        # confirmed: the user reviewed (and possibly edited) each fact and clicked Save,
        # so it is their own statement and replaces an older value for the same title.
        # Without it, facts stay EXTRACTED: they never overwrite user-confirmed slots
        # and never resurrect slots the user forgot.
        confirmed = body.get("confirmed") is True
        separate = body.get("separate_context") is True
        if separate and not confirmed:
            raise ValueError("a separate context must be reviewed and confirmed")
        if separate:
            self._send(HTTPStatus.OK, self.server.ledger.record_context(namespace, facts))
            return
        # A save never lowers a slot's sensitivity: a new value for a private slot stays private.
        try:
            existing = {f["slot"]: f["sensitivity"] for f in self.server.ledger.list(namespace=namespace)}
        except ValueError:
            existing = {}  # invalid namespace: each fact reports the error below
        # Every fact from one Save click shares a batch id, so the capsule can hand
        # the chat just the latest save instead of mixing it with older ones.
        batch = SAVE_BATCH_PREFIX + secrets.token_hex(8)
        saved, skipped = [], []
        for item in facts:
            slot = str(item.get("slot", "")) if isinstance(item, dict) else ""
            value = str(item.get("value", "")) if isinstance(item, dict) else ""
            try:
                if confirmed:  # keep a private fact private when its value is updated
                    normalized = _normalize_slot(slot)
                    record = self.server.ledger.record(
                        namespace, slot, value, confidence=1.0, verification_state="USER_CONFIRMED",
                        sensitivity=existing.get(normalized, "PUBLIC"), source_id=batch)
                else:
                    record = self.server.ledger.record(
                        namespace, slot, value, confidence=0.7, verification_state="EXTRACTED",
                        sensitivity=existing.get(_normalize_slot(slot), "PUBLIC"), source_id=batch)
                saved.append({"slot": record["slot"], "version": record.get("version")})
            except (LockedSlot, TombstonedSlot) as error:
                skipped.append({"slot": slot, "reason": type(error).__name__, "message": str(error)})
            except ValueError as error:
                skipped.append({"slot": slot, "reason": "invalid", "message": str(error)})
        self._send(HTTPStatus.OK, {"namespace": namespace, "saved": saved, "skipped": skipped})


# ---------------------------------------------------------------------------
def health(port: int, timeout: float = 1.0) -> bool:
    try:
        with urlrequest.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as response:
            return json.loads(response.read()).get("service") == "memty"
    except (OSError, ValueError):
        return False


def bridge_identity(db, port: int, timeout: float = 1.0) -> dict | None:
    """Verify a running bridge using the existing vault's pairing token."""
    try:
        token = token_path(db).read_text(encoding="utf-8").strip()
        req = urlrequest.Request(f"http://127.0.0.1:{port}/identity",
                                 headers={"Authorization": "Bearer " + token})
        with urlrequest.urlopen(req, timeout=timeout) as response:
            body = json.loads(response.read())
        return body if body.get("vault") == vault_identity(db) else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def serve(db, user_id, *, port: int = DEFAULT_PORT, allowed_origins=None, quiet=True) -> None:
    from ...runtime.daemon import DaemonLedger
    token = load_or_create_token(db)
    ledger = DaemonLedger(db, user_id)  # Shares the one memtyd process with MCP and CLI.
    with BridgeServer(ledger, token, port=port, allowed_origins=allowed_origins, quiet=quiet,
                      db=db) as server:
        state_path(db).write_text(json.dumps({"pid": os.getpid(), "port": server.port}), encoding="utf-8")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            try:
                state_path(db).unlink()
            except OSError:
                pass


def start_background(db, user_id, *, port: int = DEFAULT_PORT, allowed_origins=None) -> dict:
    if health(port):
        identity = bridge_identity(db, port)
        if not identity or identity.get("user") != user_id:
            raise RuntimeError(f"Port {port} is already used by a different or older Memty bridge; stop it before starting this vault.")
        return {"running": True, "port": port, "already_running": True}
    args = [sys.executable, "-m", "memty", "--db", str(db), "--user", user_id, "serve", "--port", str(port)]
    for origin in allowed_origins or []:
        args += ["--allow-origin", origin]
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    # Keep the bridge's startup errors (the bridge itself never logs bodies or tokens),
    # so a failed start can say why instead of only "run it in the foreground".
    log = log_path(db)
    log.parent.mkdir(parents=True, exist_ok=True)
    log_fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        # Run from the vault's folder: on Windows a process's working directory is locked,
        # so inheriting the caller's (a project folder) would block deleting or renaming it.
        child = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log_fd,
                                 cwd=str(log.parent), creationflags=flags,
                                 start_new_session=(os.name != "nt"), close_fds=True)
    finally:
        os.close(log_fd)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if health(port):
            identity = bridge_identity(db, port)
            if identity and identity.get("user") == user_id:
                return {"running": True, "port": port}
            raise RuntimeError(f"Port {port} is already used by a different or older Memty bridge.")
        if child.poll() is not None:  # it exited: no point waiting for the deadline
            raise RuntimeError(f"memty serve exited with code {child.returncode} before it started on "
                               f"127.0.0.1:{port}.{_log_tail(log)}")
        time.sleep(0.1)
    raise RuntimeError(f"memty serve did not start on 127.0.0.1:{port} within 30 seconds.{_log_tail(log)}")


def log_path(db: str | Path) -> Path:
    db = Path(db).expanduser()
    return db.with_name(db.name + ".web-bridge.log")


def _log_tail(path: Path, lines: int = 15) -> str:
    try:
        tail = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()[-lines:]
    except OSError:
        tail = []
    if not tail:
        return " Run `memty serve` in the foreground to see why."
    return f" Its last output ({path}):\n" + "\n".join(tail)


def stop_background(db) -> dict:
    try:
        state = json.loads(state_path(db).read_text(encoding="utf-8"))
        # A stale state file's pid may now belong to an unrelated process.
        if not health(int(state["port"])):
            return {"stopped": False, "reason": "not_running"}
        os.kill(int(state["pid"]), signal.SIGTERM)
    except (OSError, ValueError, KeyError):
        return {"stopped": False, "reason": "not_running"}
    try:
        state_path(db).unlink()
    except OSError:
        pass
    return {"stopped": True, "pid": state["pid"]}
