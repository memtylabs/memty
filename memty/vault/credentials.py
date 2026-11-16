"""Recognise credentials so they are never stored as shareable facts.

A chat answer pasted into "Save to Memty" can carry an API key or a password.
The ledger runs every fact through :func:`looks_like_credential` and stores a
match as SECRET, whatever sensitivity the caller asked for, so the privacy
gate keeps it on the device.

Two things are checked:

* The **value**: vendor key formats, private-key headers, passwords embedded in
  URLs, and explicit ``password: ...`` / ``DB_PASSWORD=...`` style assignments.
* The **title**: extraction turns "Admin password: Tr0ub4dor&3" into the title
  ``admin_password`` and the value ``Tr0ub4dor&3``, so the value alone looks
  harmless. A title naming a password, PIN, key or token makes a bare
  secret-looking value SECRET; a title naming a login or credentials does so
  when the value holds a generated-looking string such as ``S3cr3t!Pass``.

The patterns favour precision: ordinary prose that only *mentions* a key
("Rotate the API key monthly"), placeholders (``secret = None``), rules
("Password: must be 12 characters") and public identifiers (commit hashes,
UUIDs) are left alone.
"""

from __future__ import annotations

import re

_PATTERNS = [
    re.compile(r"\bsk-(?:proj-|ant-[a-z0-9]+-|live-|test-)?[A-Za-z0-9_-]{20,}"),     # OpenAI / Anthropic
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"),                     # Stripe secret keys
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}|\bgithub_pat_[A-Za-z0-9_]{40,}"),      # GitHub
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}"),                                     # GitLab
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),                                  # AWS access key id
    re.compile(r"\b(?:akia|asia)(?=[0-9a-z]*\d)[0-9a-z]{16}\b", re.I),             # the same, lowercased
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),                                 # Slack
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}"),                                        # Google API key
    re.compile(r"\bhf_[A-Za-z0-9]{30,}"),                                          # Hugging Face
    re.compile(r"\beyJ[\w-]{8,}\.eyJ[\w-]{8,}\.[\w-]{8,}"),                        # JWT
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),                             # PEM / OpenSSH
    re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@]+:[^\s@/]+@", re.I),                # user:password@host
]

# Words that name a secret. English plus the common Spanish, German, French and
# Portuguese words for "password".
_SECRET_ALTERNATIVES = (r"password|passwd|passphrase|passcode|pwd|pin|secret|api[ _-]?key|access[ _-]?key|"
                        r"(?:access|auth|bearer|refresh|session)[ _-]?token|private[ _-]?key|client[ _-]?secret|"
                        r"contrase[ñn]a|passwort|mot[ _-]de[ _-]passe|senha")
_SECRET_WORDS = r"(?:" + _SECRET_ALTERNATIVES + r")"
# A keyword starts after anything but a letter or digit, so OPENAI_API_KEY and
# DB_PASSWORD count while "spin" or "topic" do not. "STRIPE_SECRET_KEY" style
# names may end in _KEY or _TOKEN.
_KEYWORD = r"(?<![A-Za-z0-9])(?:pass|" + _SECRET_ALTERNATIVES + r")(?:[ _-](?:key|token))?"
# Values that only say "nothing is set here".
_PLACEHOLDER = r"(?:none|null|nil|true|false|undefined|empty|n/?a|tbd|todo|unset|not[ _-]set)\b"
# A whole word that looks generated rather than written: letters and digits
# mixed, at least 8 characters, and not a path, URL or email address.
_GENERATED = r"(?=[^\s/@]*\d)(?=[^\s/@]*[A-Za-z])[^\s/@]{8,}(?=$|[\s\"',;)])"

_PATTERNS += [
    # "password: hunter2", "API_KEY=abcd1234", "OPENAI_API_KEY=..." (not "secret = None")
    re.compile(_KEYWORD + r"\s*[:=]\s*[\"']?(?!" + _PLACEHOLDER + r")\S{4,}", re.I),
    # "my API key is 8f14e45f..." (prose form: the value must look generated, not a word)
    re.compile(_KEYWORD + r"\s+is\s+[\"']?(?=\S*\d)\S{6,}", re.I),
    # "token: 9a8b7c6d5e4f3a2b" (a bare "token" only with a generated-looking value)
    re.compile(r"(?<![A-Za-z0-9])token\s*[:=]\s*[\"']?" + _GENERATED, re.I),
]

# Titles that name a secret: a single-word value under them is the secret itself.
_SECRET_TITLE = re.compile(r"(?<![A-Za-z0-9])" + _SECRET_WORDS + r"(?![A-Za-z])", re.I)
# Titles that hint at credentials: the value must also hold a generated-looking string.
_LOGIN_TITLE = re.compile(r"(?<![A-Za-z0-9])(?:token|login|sign[ _-]?in|credentials?|creds)(?![A-Za-z])", re.I)
_GENERATED_RE = re.compile(r"(?<![^\s\"'(])" + _GENERATED)
_PLACEHOLDER_RE = re.compile(r"^" + _PLACEHOLDER + r"$", re.I)


def _title_says_secret(slot: str, text: str) -> bool:
    if _SECRET_TITLE.search(slot):
        single = text.strip("\"'` ")
        if (len(single) >= 4 and not any(ch.isspace() for ch in single)
                and not _PLACEHOLDER_RE.match(single)):
            return True  # "Admin password" -> "Tr0ub4dor&3", "Door PIN" -> "4821"
        return bool(_GENERATED_RE.search(text))
    if _LOGIN_TITLE.search(slot):
        return bool(_GENERATED_RE.search(text))  # "DB login" -> "admin / S3cr3t!Pass"
    return False


def looks_like_credential(value: str, slot: str | None = None) -> bool:
    """True when a fact appears to hold a password, key or token.

    ``slot`` is the fact's title (for example ``admin_password``). Pass it
    whenever there is one: extraction often moves the word "password" out of
    the value and into the title.
    """
    text = str(value or "")
    if any(pattern.search(text) for pattern in _PATTERNS):
        return True
    return bool(slot) and _title_says_secret(str(slot), text)
