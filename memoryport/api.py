"""Loopback-only HTTP API for the local memory vault.

This API is intended for a local UI or trusted desktop bridge. External agents
should use the approval-only MCP interface instead of receiving write access.
"""

from __future__ import annotations

import hmac
import os
import contextvars
import hashlib
from pathlib import Path
import re
from typing import Any

from .factory import open_ledger
from .ledger import MemoryLedger
from .extractor import MemoryExtractor

try:
    from fastapi import Depends, FastAPI, Header, HTTPException
    from fastapi.responses import Response
except ImportError as error:
    raise RuntimeError("HTTP API support requires: pip install 'memty[server]'") from error


_request_user: contextvars.ContextVar[str] = contextvars.ContextVar("memty_vault_user", default="local")


def _ledger() -> MemoryLedger:
    return open_ledger(_request_user.get())


async def _authorized(authorization: str | None = Header(default=None),
                      x_memty_user: str | None = Header(default=None),
                      x_nexor_user: str | None = Header(default=None)) -> None:
    secret = os.getenv("MEMTY_VAULT_API_TOKEN") or os.getenv("NEXOR_VAULT_API_TOKEN", "")
    if len(secret) < 32:
        raise HTTPException(503, "Configure a random MEMTY_VAULT_API_TOKEN of at least 32 characters.")
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not hmac.compare_digest(supplied.encode(), secret.encode()):
        raise HTTPException(401, "Invalid local vault token.")
    multi_user = os.getenv("MEMTY_VAULT_MULTIUSER", os.getenv("NEXOR_VAULT_MULTIUSER", "false")).casefold() == "true"
    user_id = x_memty_user or x_nexor_user
    if multi_user and not user_id:
        raise HTTPException(400, "X-Memty-User is required in multi-user mode.")
    if user_id:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", user_id):
            raise HTTPException(400, "Invalid vault user identifier.")
        if not multi_user:
            raise HTTPException(403, "Multi-user mode is disabled.")
        _request_user.set(user_id)
    else:
        _request_user.set(os.getenv("MEMTY_VAULT_USER", os.getenv("NEXOR_VAULT_USER", "local")))


app = FastAPI(title="Memty Memory Vault", version="1.0.0", dependencies=[Depends(_authorized)])


@app.get("/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "format": MemoryLedger.FORMAT}


@app.get("/v1/memories")
def list_memories(history: bool = False, status: str | None = None) -> list[dict[str, Any]]:
    records = _ledger().list(include_history=history)
    newer = {record.get("supersedes_id"): record["id"] for record in records if record.get("supersedes_id")}
    for record in records:
        if record["status"] == "SUPERSEDED":
            record["superseded_by_id"] = newer.get(record["id"])
    if status:
        records = [record for record in records if record["status"] == status.upper()]
    return records


@app.post("/v1/memories")
def create_memory(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return _ledger().record(
            payload.get("namespace", "personal.general"), payload["slot_key"], payload["value"],
            confidence=1.0, verification_state="USER_CONFIRMED",
            sensitivity_tier=payload.get("sensitivity_tier", "PERSONAL"),
            allowed_providers=payload.get("allowed_providers"),
            blocked_providers=payload.get("blocked_providers"),
            ephemeral_redaction=bool(payload.get("ephemeral_redaction", False)),
            source_conversation_id=payload.get("source_conversation_id"),
            source_message=payload.get("source_message"),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(400, str(error)) from error


@app.post("/v1/extract")
def extract_memories(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload.get("user_message"), str) or not isinstance(payload.get("memories"), list):
        raise HTTPException(400, "user_message and a memories list are required.")
    extractor = MemoryExtractor(_ledger(), lambda _prompt: {"memories": payload["memories"]})
    try:
        return extractor.ingest_turn(payload["user_message"], str(payload.get("assistant_response", "")),
                                     conversation_id=payload.get("conversation_id"), model_id=payload.get("model_id"))
    except (TypeError, ValueError) as error:
        raise HTTPException(400, str(error)) from error


@app.delete("/v1/memories/{memory_id}")
def delete_memory(memory_id: str) -> dict[str, Any]:
    result = _ledger().delete(memory_id)
    if result is None:
        raise HTTPException(404, "Memory not found.")
    return result


@app.patch("/v1/memories/{memory_id}")
def edit_memory(memory_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = _ledger().edit(memory_id, value=payload.get("value"), pinned=payload.get("pinned"))
    if result is None:
        raise HTTPException(404, "Active memory not found.")
    return result


@app.post("/v1/context")
def compile_context(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        return _ledger().context(payload.get("query", ""), provider=payload["provider"],
                                 token_budget=int(payload.get("token_budget", 900)),
                                 as_of=payload.get("as_of"), namespace=payload.get("namespace"))
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(400, str(error)) from error


@app.get("/v1/memories/{namespace}/{slot_key}/as-of")
def memory_as_of(namespace: str, slot_key: str, at: str, known_at: str | None = None) -> dict[str, Any] | None:
    try:
        return _ledger().as_of(namespace, slot_key, at, known_at=known_at)
    except ValueError as error:
        raise HTTPException(400, str(error)) from error


@app.get("/v1/proposals")
def list_proposals() -> list[dict[str, Any]]:
    return _ledger().proposals()


@app.post("/v1/proposals")
def propose_memory(payload: dict[str, Any]) -> dict[str, str]:
    try:
        policy = payload.get("policy") or {}
        proposal_id = _ledger().propose(payload["namespace"], payload["slot_key"], payload["value"], **policy)
        return {"proposal_id": proposal_id, "status": "PENDING_CONFIRMATION"}
    except (KeyError, TypeError, ValueError) as error:
        raise HTTPException(400, str(error)) from error


@app.post("/v1/proposals/{proposal_id}/approve")
def approve_proposal(proposal_id: str) -> dict[str, Any]:
    result = _ledger().resolve_proposal(proposal_id, approve=True)
    if result is None:
        raise HTTPException(404, "Proposal not found or already resolved.")
    return result


@app.post("/v1/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str) -> dict[str, Any]:
    result = _ledger().resolve_proposal(proposal_id, approve=False)
    if result is None:
        raise HTTPException(404, "Proposal not found or already resolved.")
    return result


@app.post("/v1/vault/export")
def export_vault(payload: dict[str, Any]) -> Response:
    from .vault import encode_nxvault
    try:
        bundle = encode_nxvault(_ledger(), passphrase=payload["passphrase"])
    except (KeyError, TypeError, ValueError, RuntimeError) as error:
        raise HTTPException(400, str(error)) from error
    return Response(bundle, media_type="application/vnd.nexor.nxvault",
                    headers={"Content-Disposition": "attachment; filename=memory.nxvault"})


def main() -> None:
    try:
        import uvicorn
    except ImportError as error:
        raise RuntimeError("HTTP API support requires: pip install 'memty[server]'") from error
    host = os.getenv("MEMTY_VAULT_API_HOST", os.getenv("NEXOR_VAULT_API_HOST", "127.0.0.1"))
    allow_remote = os.getenv("MEMTY_VAULT_ALLOW_REMOTE", os.getenv("NEXOR_VAULT_ALLOW_REMOTE", "false"))
    if host not in {"127.0.0.1", "localhost", "::1"} and allow_remote.casefold() != "true":
        raise RuntimeError("Non-loopback binding requires MEMTY_VAULT_ALLOW_REMOTE=true and a strong API token.")
    uvicorn.run("memty.legacy.api:app", host=host, port=int(os.getenv("MEMTY_VAULT_API_PORT", os.getenv("NEXOR_VAULT_API_PORT", "8765"))),
                log_level="warning")


if __name__ == "__main__":
    main()

