"""Compact MCP interface to the shared Memty ledger."""
from __future__ import annotations

import os

from ...context.privacy import LocalRoutingRequired
from ...vault.paths import default_user_id, default_vault_path
from ...vault.ledger import LOCAL_PROVIDERS, LockedSlot, MemtyLedger, TombstonedSlot
from ...trust.receipts import log_blocked, log_served

try:  # module level so FastMCP can resolve the ``ctx: Context`` annotation
    from mcp.server.fastmcp import Context
except ImportError:  # pragma: no cover - create_server reports the missing dependency
    Context = None  # type: ignore[assignment,misc]

MAX_SYNC_SLOTS = 25
MAX_DRILL_CHARS = 4000


def create_server(ledger: MemtyLedger):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:
        raise RuntimeError("MCP support requires: pip install memty") from error
    server = FastMCP("Memty", instructions=(
        "Call memty_sync with a namespace to recall memory; resources are not loaded automatically. "
        "Save or forget only on explicit user request. When you verify a durable project fact on "
        "your own (from code, config or the user), call memty_propose: new facts are saved as "
        "extracted, and changes to existing facts wait in the user's inbox for approval. Call "
        "memty_drill only when the user explicitly requests the archived source. Never claim a "
        "change succeeded unless confirmed."
    ))
    # MCP clients may forward results to a remote model; do not treat them as local.
    # Privacy decisions use this configured provider, never the client's self-reported name.
    provider = os.getenv("MEMTY_PROVIDER", "mcp")

    def client_name(ctx: Context | None) -> str | None:
        try:
            info = ctx.session.client_params.clientInfo  # type: ignore[union-attr]
            return str(info.name) or None
        except Exception:  # no ctx, outside a request, or a client that sent no clientInfo
            return None

    def capsule(namespace: str, query: str = "", client: str | None = None) -> dict:
        try:
            result = ledger.context(query, provider=provider, namespace=namespace,
                                    token_budget=120, strict_namespace=True)
        except LocalRoutingRequired as error:
            log_blocked(ledger, "mcp", provider, namespace=namespace, client=client)
            return {"error": "local_routing_required", **error.as_dict()}
        if result["text"]:
            log_served(ledger, "mcp", provider, result, namespace=namespace, client=client)
        return {"text": result["text"], "approx_tokens": result["approx_tokens"]}

    @server.resource("memty://capsule/{namespace}")
    def memty_capsule(namespace: str) -> str:
        """Read the provider-filtered, 120-token namespace capsule."""
        import json
        return json.dumps(capsule(namespace), ensure_ascii=False)

    @server.tool()
    def memty_sync(namespace: str, action: str = "recall", query: str = "",
                   slot: str = "", value: str = "", sensitivity: str = "PUBLIC",
                   set_slots: dict[str, str] | None = None, ctx: Context | None = None) -> dict:
        """Recall a capsule; on explicit request save slots and return the updated capsule."""
        client = client_name(ctx)
        if set_slots is not None:
            if action != "recall" or slot or value:
                raise ValueError("set_slots cannot be combined with action, slot, or value")
            if (not isinstance(set_slots, dict) or not 1 <= len(set_slots) <= MAX_SYNC_SLOTS
                    or not all(isinstance(k, str) and isinstance(v, str) for k, v in set_slots.items())):
                raise ValueError("set_slots must contain 1 to 25 string slot/value pairs")
            saved, skipped = [], []
            for key, item in set_slots.items():
                try:
                    record = ledger.record(namespace, key, item, verification_state="USER_CONFIRMED",
                                           sensitivity=sensitivity)
                    saved.append(record["slot"])
                except (LockedSlot, TombstonedSlot, ValueError) as error:
                    skipped.append({"slot": key, "reason": type(error).__name__})
            return {**capsule(namespace, query, client), "saved": saved, "skipped": skipped}
        if action == "recall":
            return capsule(namespace, query, client)
        if action == "remember":
            record = ledger.record(namespace, slot, value, verification_state="USER_CONFIRMED",
                                   sensitivity=sensitivity)
            return {"status": "saved", "namespace": record["namespace"], "slot": record["slot"]}
        if action == "forget":
            result = ledger.forget(namespace, slot, purge_raw=True)
            return {"status": "forgotten" if result else "not_found", "namespace": namespace, "slot": slot}
        raise ValueError("action must be recall, remember, or forget")

    @server.tool()
    def memty_propose(namespace: str, slot: str, value: str, reason: str = "",
                      sensitivity: str = "PUBLIC", ctx: Context | None = None) -> dict:
        """Propose a fact you learned. New slots are saved as extracted; a change to an
        existing or user-deleted slot is queued for the user's approval (memty inbox)."""
        result = ledger.propose(namespace, slot, value, sensitivity=sensitivity, reason=reason,
                                proposed_by=client_name(ctx) or provider)
        if result["status"] == "pending_review":
            result["message"] = ("Queued for the user's review; the saved value is unchanged "
                                 "until they run memty approve.")
        return result

    @server.tool()
    def memty_drill(namespace: str, slot: str) -> dict:
        """Read archived source for one slot, only for an explicitly requested local model."""
        if provider.casefold() not in LOCAL_PROVIDERS:
            return {"error": "local_only", "message": "Archived source is available only to a local model."}
        fact = ledger.find(namespace, slot)
        if not fact or fact["tombstone"]:
            return {"error": "not_found"}
        raw = ledger.drill_down(fact_id=fact["id"])
        if raw is None:
            return {"error": "no_archived_source"}
        content = raw["raw_content"]
        return {"namespace": namespace, "slot": slot,
                "source": content[:MAX_DRILL_CHARS], "truncated": len(content) > MAX_DRILL_CHARS}

    return server


def main() -> None:
    from ...runtime.daemon import DaemonLedger
    ledger = DaemonLedger(default_vault_path(), default_user_id())
    try:
        create_server(ledger).run(transport="stdio")
    finally:
        ledger.close()


if __name__ == "__main__":
    main()
