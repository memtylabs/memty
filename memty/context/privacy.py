"""The privacy gate: what a provider may see, and what must stay on the device.

Three rules, applied by the compiler to every fact before it is injected:

* **SECRET** facts never leave the device.  If one matches a request from a
  cloud provider, :class:`LocalRoutingRequired` is raised and nothing is sent.
* **Provider lists**: a provider on a fact's block list never sees it; when a
  fact has an allow list, only those providers see it.  INTERNAL facts are
  shown only to local or trusted providers (or ones on the allow list).
* **CONFIDENTIAL** values (and any fact marked ``ephemeral_redaction``) are
  replaced by a placeholder for untrusted providers.
"""

from __future__ import annotations

from typing import Any

from ..vault.ledger import LOCAL_PROVIDERS


class LocalRoutingRequired(RuntimeError):
    """A matched SECRET fact may not leave the device.

    The caller (router/SDK) should switch to the suggested local provider and
    compile the context again.  No secret value is included on the exception.
    """

    def __init__(self, provider: str, *, namespace: str | None = None,
                 slot: str | None = None, suggested_provider: str = "ollama"):
        self.provider = provider
        self.namespace = namespace
        self.slot = slot
        self.suggested_provider = suggested_provider
        target = f"{namespace}.{slot}" if namespace and slot else "a secret slot"
        super().__init__(
            f"SECRET memory matched {target}; provider '{provider}' is not local. "
            f"Route this request to '{suggested_provider}'."
        )

    def as_dict(self) -> dict[str, Any]:
        return {"error": "local_routing_required", "provider": self.provider,
                "suggested_provider": self.suggested_provider,
                "namespace": self.namespace, "slot": self.slot}


def provider_flags(provider: str, trusted_providers) -> tuple[str, bool, bool]:
    """Return ``(provider_key, local, trusted)`` for a provider identifier."""
    provider_key = str(provider).casefold()
    local = provider_key in LOCAL_PROVIDERS
    return provider_key, local, local or provider_key in trusted_providers


def provider_allowed(fact: dict[str, Any], provider_key: str, trusted: bool) -> bool:
    """Apply the fact's block list, allow list and INTERNAL rule."""
    blocked = {item.casefold() for item in fact["blocked_providers"]}
    if provider_key in blocked:
        return False
    allowed = {item.casefold() for item in fact["allowed_providers"]}
    if allowed and provider_key not in allowed:
        return False
    if fact["sensitivity"] == "INTERNAL" and not trusted and provider_key not in allowed:
        return False
    return True


def needs_redaction(fact: dict[str, Any], provider_key: str, trusted: bool) -> bool:
    """True when the value must be replaced by a placeholder for this provider."""
    allowed = {item.casefold() for item in fact["allowed_providers"]}
    fact_trusted = trusted or provider_key in allowed
    return bool(fact["ephemeral_redaction"]) or (
        fact["sensitivity"] == "CONFIDENTIAL" and not fact_trusted)
