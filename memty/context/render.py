"""Plain-text capsules for chat assistants (browser bridge, ``memty clip``).

Chat UIs read ``Title: value`` lines far better than namespaced XML slots, so
the compiled ``<memty_state>`` citations are re-rendered here.  Redaction
placeholders become ``[private]``; values are never un-redacted.
"""

from __future__ import annotations

import re
from typing import Any

from ..vault.ledger import _CONTEXT_SLOT_SUFFIX
from ..vault.tokens import estimate_tokens

_REDACTED = re.compile(r"<MEMTY_REDACTED_SLOT_\d+>")
_HASH_SLOT = re.compile(r"^(?:note|fact)_[0-9a-f]{6,}$")
_COUNTER = re.compile(r"_\d+$")


def slot_label(slot: str) -> str:
    """``deploy_target_2`` -> ``Deploy target``; hashed note slots become ``Note``."""
    slot = _CONTEXT_SLOT_SUFFIX.sub("", slot)
    if _HASH_SLOT.match(slot):
        return "Note"
    label = _COUNTER.sub("", slot).replace("_", " ").replace(".", " ").strip()
    return label[:1].upper() + label[1:]


def render_plain(result: dict[str, Any], namespace: str | None = None,
                 token_budget: int | None = None) -> str:
    """Render a compiled capsule as ``Title: value`` lines, trimmed to ``token_budget``.

    Citations arrive best-first, so trimming drops the least relevant facts.
    """
    return render_plain_with_count(result, token_budget)[0]


def render_plain_with_count(result: dict[str, Any], token_budget: int | None = None) -> tuple[str, int]:
    """Render a capsule and count facts that fit, including grouped fact parts."""
    citations = list(result.get("citations") or [])
    text = _render_plain(citations)
    while token_budget and citations and estimate_tokens(text) > token_budget:
        citations.pop()
        text = _render_plain(citations)
    return text, sum(1 for item in citations if item.get("type") != "summary")


def _render_plain(citations: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    grouped: dict[str, list[str]] = {}
    for item in citations:
        if item.get("type") == "summary":
            lines.append("Summary: " + " ".join(str(item["value"]).split()))
            continue
        value = _REDACTED.sub("[private]", " ".join(str(item.get("value", "")).split()))
        grouped.setdefault(slot_label(str(item.get("slot", ""))), []).append(value)
    for label, values in grouped.items():
        if label == "Note":
            lines.extend(f"Note: {value}" for value in values)
        else:
            lines.append(f"{label}: {'; '.join(values)}")
    return "\n".join(lines)
