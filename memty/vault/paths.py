"""Default vault location and small factory helpers."""

from __future__ import annotations

import os
from pathlib import Path

from .ledger import MemtyLedger


def default_vault_path() -> Path:
    """Return ``~/.memty/ledger.sqlite3`` unless the user overrides it."""
    configured = os.getenv("MEMTY_VAULT_PATH") or os.getenv("MEMTY_DB")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".memty" / "ledger.sqlite3"


def default_user_id() -> str:
    return os.getenv("MEMTY_USER", "local")


def open_ledger(user_id: str | None = None, *, path: str | Path | None = None,
                trusted_providers: list[str] | tuple[str, ...] | set[str] | None = None) -> MemtyLedger:
    """Open a SQLite vault for one user."""
    return MemtyLedger(path or default_vault_path(), user_id or default_user_id(),
                       trusted_providers=trusted_providers)
