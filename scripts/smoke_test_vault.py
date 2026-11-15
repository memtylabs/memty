"""Small end-to-end smoke test for the local Memty vault."""

from __future__ import annotations

import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memty import LocalRoutingRequired, MemtyLedger, estimate_tokens


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "ledger.sqlite3"
        with MemtyLedger(path) as vault:
            vault.record("project.api", "cache_engine", "DragonflyDB",
                         verification_state="USER_CONFIRMED")
            vault.record("project.api", "rate_limiter",
                         "Token Bucket via Lua, 500 req/min",
                         verification_state="SPEC_LOCKED")
            vault.set_constraint(
                "project.api", "database_queries", "writing database queries",
                "always use async Motor and project only needed fields")
            vault.set_summary(
                "project.api",
                "FastAPI backend with JWT auth and MongoDB Atlas sync.")

            capsule = vault.context(
                "Which cache and rate limiter should I use?",
                provider="claude",
                namespace="project.api",
            )
            assert estimate_tokens(capsule["text"]) <= 600
            assert "DragonflyDB" in capsule["text"]
            assert "Token Bucket" in capsule["text"]

            vault.record("project.api", "internal_host", "db.internal.example",
                         sensitivity="SECRET", verification_state="USER_CONFIRMED")
            try:
                vault.context("internal host", provider="claude")
            except LocalRoutingRequired as error:
                assert error.suggested_provider == "ollama"
            else:
                raise AssertionError("SECRET memory did not force local routing")

            assert "db.internal.example" in vault.context(
                "internal host", provider="ollama")["text"]
            assert vault.stats()["constraints"] == 1

        with MemtyLedger(path) as reopened:
            assert reopened.list_constraints(namespace="project.api")[0]["rule_id"] == "database_queries"
            assert reopened.find("project.api", "cache_engine")["value"] == "DragonflyDB"

    print("Memty vault smoke test passed.")


if __name__ == "__main__":
    main()
