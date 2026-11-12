"""Context receipts: record every capsule served, without its values.

Every surface that hands a capsule to an assistant (``memty recall``, ``memty
clip``, MCP, the browser bridge) calls :func:`log_served` or
:func:`log_blocked`.  Logging is best effort: a receipt failure must never stop
the capsule from being served.
"""

from __future__ import annotations

from typing import Any


def _fact_ids(result: dict[str, Any]) -> list[str]:
    if isinstance(result.get("fact_ids"), list):
        return [item for item in result["fact_ids"] if isinstance(item, str)]
    return [item["id"] for item in result.get("citations") or []
            if isinstance(item, dict) and isinstance(item.get("id"), str)]


def log_served(ledger, channel: str, provider: str, result: dict[str, Any], *,
               namespace: str | None = None, client: str | None = None,
               tokens: int | None = None, fact_ids: list[str] | None = None,
               redacted: int | None = None) -> dict[str, Any] | None:
    """Record one served capsule.  Returns the receipt, or None if logging failed."""
    try:
        ids = fact_ids if fact_ids is not None else _fact_ids(result)
        if redacted is None:
            redactions = result.get("redactions")
            redacted = len(redactions) if isinstance(redactions, dict) else int(result.get("redacted") or 0)
        return ledger.log_receipt(
            channel, provider, fact_ids=ids, namespace=namespace, client=client,
            tokens_injected=int(tokens if tokens is not None else result.get("approx_tokens") or 0),
            redacted=int(redacted or 0))
    except Exception:  # never let accounting break serving
        return None


def log_blocked(ledger, channel: str, provider: str, *, namespace: str | None = None,
                client: str | None = None) -> dict[str, Any] | None:
    """Record a request refused because a SECRET fact matched a cloud provider."""
    try:
        return ledger.log_receipt(channel, provider, namespace=namespace, client=client,
                                  secrets_blocked=1)
    except Exception:
        return None
