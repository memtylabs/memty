"""Deterministic, dependency-free token accounting for the atomic compiler.

The model tokenizer is intentionally not imported here: Memty must stay a
standard-library package and must produce the same byte-for-byte context on
every machine.  ``estimate_tokens`` is a conservative upper bound for English
and code (it is at least ``ceil(characters / 4)`` and also counts every word
and punctuation mark), so a block that passes the check is very unlikely to
exceed the same budget in a real provider tokenizer.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def estimate_tokens(text: str) -> int:
    """Return a conservative token count for ``text``."""
    if not text:
        return 0
    return max(len(_TOKEN_RE.findall(text)), (len(text) + 3) // 4)


def truncate_tokens(text: str, limit: int) -> str:
    """Return the longest prefix of ``text`` that fits ``limit`` tokens."""
    text = str(text)
    if limit <= 0:
        return ""
    if estimate_tokens(text) <= limit:
        return text
    low, high = 0, len(text)
    while low < high:
        middle = (low + high + 1) // 2
        if estimate_tokens(text[:middle]) <= limit:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip()
