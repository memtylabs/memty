"""One-way import from the previous Memty temporal SQLite ledger."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .ledger import MemtyLedger

_VERIFICATION_MAP = {
    "AUTO_EXTRACTED": "EXTRACTED",
    "PENDING_CONFIRMATION": "EXTRACTED",
    "EXTRACTED": "EXTRACTED",
    "PINNED": "SPEC_LOCKED",
    "SPEC_LOCKED": "SPEC_LOCKED",
    "USER_CONFIRMED": "USER_CONFIRMED",
}
_SENSITIVITY_MAP = {
    "PUBLIC": "PUBLIC",
    # The old package used PERSONAL as its default and still allowed it to
    # cloud providers.  Map it to PUBLIC so migration does not silently change
    # retrieval behavior; users can raise individual facts later.
    "PERSONAL": "PUBLIC",
    "INTERNAL": "INTERNAL",
    "CONFIDENTIAL": "CONFIDENTIAL",
    "SECRET": "SECRET",
}


def migrate_from_legacy(old_path: str | Path, ledger: MemtyLedger) -> dict[str, Any]:
    """Copy the latest active facts from a legacy event-sourced ledger.

    The old database is opened read-only and is never modified.  Only the newest
    event for each ``(namespace, slot_key)`` is considered; deleted slots stay
    deleted.  Facts longer than the new 40-token atomic limit are skipped and
    reported instead of being silently truncated.
    """
    path = Path(old_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(path)
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(ledger_events)")}
        if not {"namespace", "slot_key", "value", "status"}.issubset(columns):
            raise ValueError("not a previous Memty temporal ledger: required columns are missing")
        rows = connection.execute("""
            SELECT * FROM (
                SELECT e.*, ROW_NUMBER() OVER (
                    PARTITION BY e.namespace, e.slot_key ORDER BY e.seq DESC
                ) AS rn
                  FROM ledger_events e
            ) WHERE rn=1 ORDER BY seq
        """).fetchall()
    finally:
        connection.close()

    imported = skipped_long = skipped_empty = skipped_deleted = skipped_inactive = 0
    skipped_error = 0
    skipped: list[dict[str, str]] = []
    for row in rows:
        status = str(row["status"]).upper()
        if status == "DELETED":
            skipped_deleted += 1
            continue
        if status != "ACTIVE":
            skipped_inactive += 1
            continue
        value = str(row["value"] or "").strip()
        if not value:
            skipped_empty += 1
            continue
        try:
            ledger.record(
                row["namespace"], row["slot_key"], value,
                confidence=float(row["confidence"] if "confidence" in row.keys() else 0.8),
                verification_state=_VERIFICATION_MAP.get(
                    str(row["verification_state"]).upper(), "EXTRACTED"),
                sensitivity=_SENSITIVITY_MAP.get(
                    str(row["sensitivity_tier"]).upper(), "INTERNAL"),
                allowed_providers=_providers(row, "allowed_providers_json"),
                blocked_providers=_providers(row, "blocked_providers_json"),
                ephemeral_redaction=bool(row["ephemeral_redaction"])
                if "ephemeral_redaction" in row.keys() else False,
                source_raw=row["source_quote"] if "source_quote" in row.keys() else None,
            )
            imported += 1
        except ValueError as error:
            if "40 tokens" in str(error):
                skipped_long += 1
            else:
                skipped_error += 1
            skipped.append({"namespace": row["namespace"], "slot": row["slot_key"],
                            "reason": str(error)})
    return {"imported": imported, "skipped_long": skipped_long,
            "skipped_empty": skipped_empty, "skipped_deleted": skipped_deleted,
            "skipped_inactive": skipped_inactive, "skipped_error": skipped_error,
            "skipped": skipped}


# Preserve the former function name for migration scripts already in use.
migrate_from_memoryport = migrate_from_legacy


def _providers(row: sqlite3.Row, column: str) -> list[str]:
    if column not in row.keys():
        return []
    import json
    try:
        values = json.loads(row[column] or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return [str(item) for item in values] if isinstance(values, list) else []
