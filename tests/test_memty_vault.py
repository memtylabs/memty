"""Acceptance tests for the Memty atomic vault and context compiler."""

from __future__ import annotations

import sqlite3
import statistics
import tempfile
import time
import unittest
from pathlib import Path

from memty import (FACT_TOKEN_LIMIT, LocalRoutingRequired, MemtyLedger,
                   TombstonedSlot, estimate_tokens)


class VaultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "ledger.sqlite3"
        self.ledger = MemtyLedger(self.path)

    def tearDown(self) -> None:
        self.ledger.close()
        self.temp.cleanup()

    # ------------------------------------------------------------------
    # Atomic facts
    # ------------------------------------------------------------------
    def test_schema_has_the_three_functional_tables(self) -> None:
        db = sqlite3.connect(self.path)
        try:
            names = {row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
        finally:
            db.close()
        self.assertTrue({"atomic_facts", "logical_constraints", "rolling_summaries", "raw_drilldown",
                         "atomic_fact_audit"}.issubset(names))
        self.assertTrue({"atomic_facts_fts", "rolling_summaries_fts"}.issubset(names))

    def test_logical_constraints_are_replaceable_and_persistent(self) -> None:
        first = self.ledger.set_constraint(
            "repo.nexor", "database_queries", "writing database queries",
            "always use async Motor and project only needed fields")
        self.assertEqual(first["rule_id"], "database_queries")
        updated = self.ledger.set_constraint(
            "repo.nexor", "database_queries", "writing database queries",
            "use async Motor and project only needed fields")
        self.assertEqual(updated["id"], first["id"])
        self.assertEqual(len(self.ledger.list_constraints(namespace="repo.nexor")), 1)
        self.assertEqual(self.ledger.list_constraints()[0]["then_constraint"],
                         "use async Motor and project only needed fields")
        self.assertTrue(self.ledger.delete_constraint("repo.nexor", "database_queries"))
        self.assertEqual(self.ledger.list_constraints(), [])

    def test_atomic_fact_token_limit(self) -> None:
        self.ledger.record("repo.nexor", "ok", "short fact")
        with self.assertRaises(ValueError):
            self.ledger.record("repo.nexor", "too_long", "word " * (FACT_TOKEN_LIMIT + 1))
        self.assertLessEqual(estimate_tokens(self.ledger.find("repo.nexor", "ok")["value"]),
                             FACT_TOKEN_LIMIT)

    def test_supersede_increments_version_and_audits_old_value(self) -> None:
        first = self.ledger.record("repo.nexor", "primary_db", "Postgres 15",
                                   verification_state="USER_CONFIRMED")
        second = self.ledger.record("repo.nexor", "primary_db", "Postgres 16",
                                    verification_state="USER_CONFIRMED")
        self.assertEqual(first["version"], 1)
        self.assertEqual(second["version"], 2)
        self.assertEqual(second["value"], "Postgres 16")
        history = self.ledger.history("repo.nexor", "primary_db")
        self.assertEqual(history[0]["value"], "Postgres 15")
        self.assertEqual(history[-1]["value"], "Postgres 16")
        self.assertEqual(len(self.ledger.list(namespace="repo.nexor")), 1)

    def test_tombstone_blocks_extraction_but_allows_user_restore(self) -> None:
        self.ledger.record("work.prefs", "editor", "VS Code", verification_state="USER_CONFIRMED")
        forgotten = self.ledger.forget("work.prefs", "editor")
        self.assertTrue(forgotten["tombstone"])
        self.assertEqual(forgotten["value"], "")
        self.assertEqual(self.ledger.list(namespace="work.prefs"), [])
        with self.assertRaises(TombstonedSlot):
            self.ledger.record("work.prefs", "editor", "Sublime", verification_state="EXTRACTED")
        restored = self.ledger.record("work.prefs", "editor", "Sublime",
                                      verification_state="USER_CONFIRMED")
        self.assertFalse(restored["tombstone"])
        self.assertEqual(restored["value"], "Sublime")

    def test_extraction_cannot_overwrite_user_confirmed_slot(self) -> None:
        self.ledger.record("work.prefs", "editor", "VS Code", verification_state="USER_CONFIRMED")
        with self.assertRaises(ValueError):
            self.ledger.record("work.prefs", "editor", "Notepad", verification_state="EXTRACTED")
        self.assertEqual(self.ledger.find("work.prefs", "editor")["value"], "VS Code")

    # ------------------------------------------------------------------
    # Raw drill-down isolation
    # ------------------------------------------------------------------
    def test_raw_text_is_never_injected_and_requires_explicit_fetch(self) -> None:
        raw = "RAW TRANSCRIPT: the private deployment lives at db.internal.example"
        fact = self.ledger.record("repo.nexor", "deployment_host", "db.internal.example",
                                  verification_state="USER_CONFIRMED", source_raw=raw)
        compiled = self.ledger.context("deployment host", provider="local")
        self.assertIn("db.internal.example", compiled["text"])
        self.assertNotIn("RAW TRANSCRIPT", compiled["text"])
        self.assertNotIn("private deployment", compiled["text"])
        fetched = self.ledger.drill_down(fact_id=fact["id"])
        self.assertEqual(fetched["raw_content"], raw)

    def test_raw_archive_deduplicates_by_sha256(self) -> None:
        first = self.ledger.archive_raw("repo.nexor", "same raw text")
        second = self.ledger.archive_raw("repo.nexor", "same raw text")
        self.assertEqual(first, second)
        self.assertEqual(self.ledger.stats()["raw_documents"], 1)

    # ------------------------------------------------------------------
    # Compiler budget
    # ------------------------------------------------------------------
    def test_context_never_exceeds_budget_and_is_under_five_ms_warm(self) -> None:
        for index in range(200):
            self.ledger.record(f"repo.project{index % 10}", f"slot_{index}",
                               f"value number {index} with several extra words here",
                               verification_state="USER_CONFIRMED")
        self.ledger.set_summary("repo.project0", "Project zero uses Python and SQLite.")

        for budget in (40, 120, 600):
            compiled = self.ledger.context("value number project slot", provider="claude",
                                           token_budget=budget)
            self.assertLessEqual(compiled["approx_tokens"], budget, compiled["text"])
            self.assertLessEqual(estimate_tokens(compiled["text"]), budget, compiled["text"])

        compiled = self.ledger.context("value number project slot", provider="claude",
                                       token_budget=600)
        self.assertEqual(compiled["sections"]["summary"], 1)
        self.assertLessEqual(compiled["sections"]["slots"], 32)
        self.assertLessEqual(compiled["sections"]["semantic"], 3)

        samples = []
        for _ in range(30):
            start = time.perf_counter()
            self.ledger.context("value number project slot", provider="claude", token_budget=600)
            samples.append((time.perf_counter() - start) * 1000)
        median = statistics.median(samples)
        self.assertLess(median, 6.0, f"warm compiler median was {median:.2f}ms")

    def test_empty_context_returns_no_header(self) -> None:
        self.ledger.record("repo.nexor", "primary_db", "Postgres 16")
        compiled = self.ledger.context("completely unrelated words", provider="claude")
        self.assertEqual(compiled["text"], "")
        self.assertEqual(compiled["injected_count"], 0)

    # ------------------------------------------------------------------
    # Privacy gate
    # ------------------------------------------------------------------
    def test_secret_forces_local_routing(self) -> None:
        self.ledger.record("user.vault", "api_key", "super-secret-value",
                           sensitivity="SECRET", verification_state="USER_CONFIRMED")
        with self.assertRaises(LocalRoutingRequired) as raised:
            self.ledger.context("api key", provider="claude")
        self.assertEqual(raised.exception.suggested_provider, "ollama")
        local = self.ledger.context("api key", provider="ollama")
        self.assertIn("super-secret-value", local["text"])

    def test_confidential_is_redacted_and_rehydrated(self) -> None:
        self.ledger.record("repo.nexor", "internal_host", "db.internal.example",
                           sensitivity="CONFIDENTIAL", verification_state="USER_CONFIRMED")
        compiled = self.ledger.context("internal host", provider="claude")
        self.assertNotIn("db.internal.example", compiled["text"])
        self.assertIn("<MEMTY_REDACTED_SLOT_1>", compiled["text"])
        self.assertEqual(compiled["redactions"]["<MEMTY_REDACTED_SLOT_1>"], "db.internal.example")
        rehydrated = self.ledger.rehydrate(compiled["text"], compiled["redactions"])
        self.assertIn("db.internal.example", rehydrated)

    def test_confidential_rehydration_supports_split_stream_chunks(self) -> None:
        self.ledger.record("repo.nexor", "internal_host", "db.internal.example",
                           sensitivity="CONFIDENTIAL", verification_state="USER_CONFIRMED")
        compiled = self.ledger.context("internal host", provider="claude")
        placeholder = "<MEMTY_REDACTED_SLOT_1>"
        chunks = [compiled["text"][:compiled["text"].index(placeholder) + 8],
                  compiled["text"][compiled["text"].index(placeholder) + 8:]]
        output = "".join(self.ledger.rehydrate_stream(iter(chunks), compiled["redactions"]))
        self.assertIn("db.internal.example", output)
        self.assertNotIn(placeholder, output)

    def test_confidential_is_plain_for_trusted_provider(self) -> None:
        trusted = MemtyLedger(self.path, trusted_providers=["claude"])
        trusted.record("repo.nexor", "internal_host", "db.internal.example",
                       sensitivity="CONFIDENTIAL", verification_state="USER_CONFIRMED")
        compiled = trusted.context("internal host", provider="claude")
        self.assertIn("db.internal.example", compiled["text"])
        self.assertEqual(compiled["redactions"], {})
        trusted.close()

    def test_provider_allow_and_block_lists(self) -> None:
        self.ledger.record("repo.nexor", "internal_host", "db.internal.example",
                           sensitivity="CONFIDENTIAL", verification_state="USER_CONFIRMED",
                           allowed_providers=["claude"])
        self.assertEqual(self.ledger.context("internal host", provider="openai")["text"], "")
        self.assertIn("db.internal.example",
                      self.ledger.context("internal host", provider="claude")["text"])

        self.ledger.record("repo.nexor", "blocked_host", "blocked.example",
                           verification_state="USER_CONFIRMED", blocked_providers=["claude"])
        self.assertEqual(self.ledger.context("blocked", provider="claude")["text"], "")

    # ------------------------------------------------------------------
    # Semantic snippets and summaries
    # ------------------------------------------------------------------
    def test_query_embedding_adds_semantic_snippet_without_lexical_overlap(self) -> None:
        self.ledger.record("repo.nexor", "primary_db", "Postgres 16",
                           verification_state="USER_CONFIRMED", embedding=[1.0, 0.0])
        self.ledger.record("repo.nexor", "cache", "Redis 7",
                           verification_state="USER_CONFIRMED", embedding=[0.0, 1.0])
        compiled = self.ledger.context("unrelated words", provider="claude",
                                       query_embedding=[1.0, 0.0])
        self.assertIn("Postgres 16", compiled["text"])
        self.assertNotIn("Redis 7", compiled["text"])

    def test_query_embedding_works_with_an_empty_query(self) -> None:
        self.ledger.record("repo.nexor", "primary_db", "Postgres 16",
                           verification_state="USER_CONFIRMED", embedding=[1.0, 0.0])
        compiled = self.ledger.context("", provider="claude", query_embedding=[1.0, 0.0])
        self.assertIn("Postgres 16", compiled["text"])
        self.assertLessEqual(compiled["approx_tokens"], 600)

    def test_summary_is_capped_and_injected(self) -> None:
        self.ledger.record("repo.nexor", "primary_db", "Postgres 16",
                           verification_state="USER_CONFIRMED")
        summary = self.ledger.set_summary("repo.nexor", "Nexor uses Postgres and a local compiler.")
        self.assertLessEqual(summary["token_count"], 150)
        with self.assertRaises(ValueError):
            self.ledger.set_summary("repo.nexor", "word " * 200)
        compiled = self.ledger.context("Postgres compiler", provider="claude")
        self.assertIn("<summary", compiled["text"])
        self.assertIn("Nexor uses Postgres", compiled["text"])

    def test_summary_skipped_for_untrusted_provider_when_namespace_has_secrets(self) -> None:
        self.ledger.record("repo.nexor", "internal_host", "db.internal.example",
                           sensitivity="CONFIDENTIAL", verification_state="USER_CONFIRMED")
        self.ledger.set_summary("repo.nexor", "The internal host is db.internal.example.")
        compiled = self.ledger.context("internal host", provider="claude")
        self.assertNotIn("The internal host", compiled["text"])
        self.assertNotIn("db.internal.example", compiled["text"])

    # ------------------------------------------------------------------
    # Legacy migration
    # ------------------------------------------------------------------
    def test_migration_imports_latest_active_facts_only(self) -> None:
        from memoryport import MemoryLedger

        legacy_path = Path(self.temp.name) / "legacy.sqlite3"
        legacy = MemoryLedger(legacy_path)
        legacy.record("work.preferences", "editor", "VS Code",
                      verification_state="USER_CONFIRMED")
        legacy.record("work.preferences", "editor", "Sublime Text",
                      verification_state="USER_CONFIRMED")
        removed = legacy.record("repo.nexor", "obsolete", "old thing",
                                verification_state="USER_CONFIRMED")
        legacy.delete(removed["id"])
        legacy.record("repo.nexor", "primary_db", "Postgres 16",
                      verification_state="USER_CONFIRMED")
        legacy.close() if hasattr(legacy, "close") else None

        from memty import migrate_from_memoryport

        result = migrate_from_memoryport(legacy_path, self.ledger)
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["skipped_deleted"], 1)
        self.assertEqual(result["skipped_inactive"], 0)

        values = {fact["slot"]: fact for fact in self.ledger.list()}
        self.assertEqual(values["editor"]["value"], "Sublime Text")
        # PERSONAL must not become more restrictive during migration.
        self.assertEqual(values["editor"]["sensitivity"], "PUBLIC")
        self.assertNotIn("obsolete", values)

        compiled = self.ledger.context("Which editor do I use?", provider="claude")
        self.assertIn("Sublime Text", compiled["text"])

    def test_migration_reports_facts_over_the_atomic_limit(self) -> None:
        from memoryport import MemoryLedger

        legacy_path = Path(self.temp.name) / "legacy-long.sqlite3"
        legacy = MemoryLedger(legacy_path)
        legacy.record("repo.nexor", "huge", "word " * 60, verification_state="USER_CONFIRMED")
        legacy.close() if hasattr(legacy, "close") else None

        from memty import migrate_from_memoryport

        result = migrate_from_memoryport(legacy_path, self.ledger)
        self.assertEqual(result["imported"], 0)
        self.assertEqual(result["skipped_long"], 1)
        self.assertTrue(result["skipped"][0]["reason"].startswith("atomic fact must be at most"))


if __name__ == "__main__":
    unittest.main()
