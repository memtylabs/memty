"""The trust control plane: what was served, and what agents proposed.

``receipts`` logs every capsule served (counts and slot names, never values).
``render`` prints ``memty inbox``, ``memty receipts`` and ``memty report``.
The storage for both lives in :mod:`memty.vault.ledger`.
"""
