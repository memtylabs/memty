"""The vault: where facts live.

``ledger`` is the SQLite store (facts, rules, summaries, raw archive, audit,
inbox and receipt tables).  ``paths`` resolves the default vault location,
``migrate`` imports older vaults, and ``tokens``/``vectors`` are the
dependency-free helpers the store relies on.
"""
