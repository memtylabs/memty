"""Memty: local-first, persistent memory for AI assistants.

One user-owned SQLite vault, served by a single local daemon (``memtyd``) to
MCP clients (Claude Code, Cursor, Codex, VS Code, Windsurf, Claude Desktop),
browser assistants through the Memty Bridge extension, and the clipboard.
"""

from .context.compiler import ContextCompiler
from .context.privacy import LocalRoutingRequired
from .vault.paths import default_user_id, default_vault_path, open_ledger
from .vault.ledger import (DEFAULT_CONTEXT_BUDGET, FACT_TOKEN_LIMIT, SCHEMA_VERSION,
                           SUMMARY_TOKEN_LIMIT, LockedSlot, MemtyLedger, TombstonedSlot)
from .vault.migrate import migrate_from_legacy, migrate_from_memoryport
from .vault.tokens import estimate_tokens, truncate_tokens
from .vault.vectors import cosine, pack_vector, unpack_vector

# ``MemoryLedger`` is kept as an explicit alias for code that used the old
# package name.  The new brand is Memty and ``MemtyLedger`` is preferred.
MemoryLedger = MemtyLedger

__all__ = [
    "ContextCompiler", "DEFAULT_CONTEXT_BUDGET", "FACT_TOKEN_LIMIT", "LocalRoutingRequired",
    "LockedSlot", "MemoryLedger", "MemtyLedger", "SCHEMA_VERSION", "SUMMARY_TOKEN_LIMIT",
    "TombstonedSlot", "cosine", "default_user_id", "default_vault_path", "estimate_tokens",
    "migrate_from_legacy", "migrate_from_memoryport", "open_ledger", "pack_vector",
    "truncate_tokens", "unpack_vector",
]
