"""Recognise credentials so they are never stored as shareable facts.

A chat answer pasted into "Save to Memty" can carry an API key or a password.
The ledger runs every value through :func:`looks_like_credential` and stores a
match as SECRET, whatever sensitivity the caller asked for, so the privacy
gate keeps it on the device.

The patterns favour precision: vendor key formats, private-key headers,
passwords embedded in URLs, and explicit ``password: ...`` style assignments.
Ordinary prose that only *mentions* a key ("Rotate the API key monthly") and
public identifiers (commit hashes, UUIDs) are left alone.
"""

from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"\bsk-(?:proj-|ant-[a-z0-9]+-|live-|test-)?[A-Za-z0-9_-]{20,}"),     # OpenAI / Anthropic
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"),                     # Stripe secret keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}"),      # GitHub
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"),                                     # GitLab
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),                                  # AWS access key id
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),                                 # Slack
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),                                        # Google API key
    re.compile(r"\bhf_[A-Za-z0-9]{30,}"),                                          # Hugging Face
    re.compile(r"\beyJ[\w-]{8,}\.eyJ[\w-]{8,}\.[\w-]{8,}"),                        # JWT
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),                             # PEM / OpenSSH
    re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:[^\s@/]+@", re.I),                # user:password@host
]

_KEYWORD = (r"\b(?:pass(?:word|wd|phrase|code)?|pwd|pin|secret|api[ _-]?key|access[ _-]?key|"
            r"(?:access|auth|bearer|refresh|session)[ _-]?token|private[ _-]?key|client[ _-]?secret)")
_PATTERNS += [
    # "password: hunter2", "API_KEY=abcd1234"
    re.compile(_KEYWORD + r"\s*[:=]\s*[\"']?\S{4,}", re.I),
    # "my API key is 8f14e45f..." (prose form: the value must look generated, not a word)
    re.compile(_KEYWORD + r"\s+is\s+[\"']?(?=\S*\d)\S{6,}", re.I),
]


def looks_like_credential(value: str) -> bool:
    """True when ``value`` appears to contain a password, key or token."""
    text = str(value or "")
    return any(pattern.search(text) for pattern in _PATTERNS)
