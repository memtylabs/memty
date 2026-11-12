"""Days 24-25: project scan, agent proposal inbox, and context receipts."""
import asyncio
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import Implementation

from memty.vault.ledger import MemtyLedger
from memty.extraction.project_scan import _MiniToml, apply_scan, env_key_names, parse_toml, scan_project
from memty.vault.tokens import estimate_tokens
from memty.trust.receipts import log_blocked, log_served
from memty.trust.render import format_inbox, format_report
from memty.integrations.browser.bridge import BridgeServer, load_or_create_token
from tests.test_memty_week3 import EXT, PerCallLedger

PYPROJECT = '''
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "billing-api"
version = "1.4.2"
description = "Invoices and payouts"   # trailing comment
requires-python = ">=3.11"
license = { text = "Apache-2.0" }
dependencies = [
  "fastapi>=0.110",
  "sqlalchemy[asyncio]~=2.0",
  'redis>=5',
]

[project.optional-dependencies]
dev = ["pytest>=8", "ruff"]

[project.scripts]
billing = "billing.cli:main"

[tool.ruff]
line-length = 100
'''

PACKAGE_JSON = {
    "name": "billing-web", "version": "0.3.0", "type": "module", "private": True,
    "scripts": {"dev": "vite", "build": "vite build", "test": "vitest"},
    "dependencies": {"react": "^18.3.0", "react-dom": "^18.3.0"},
    "devDependencies": {"typescript": "^5.5.0", "vite": "^5.4.0", "vitest": "^2.0.0"},
    "engines": {"node": ">=20"},
}

CARGO = '''
[package]
name = "ledger-core"
version = "0.9.0"
edition = "2021"

[dependencies]
tokio = { version = "1", features = ["full"] }
serde = "1"

[[bin]]
name = "ledger"
'''

DOCKERFILE = '''
FROM python:3.12-slim AS build
ARG PIP_TOKEN=ghp_supersecretbuildtoken
ENV DATABASE_URL=postgres://admin:hunter2@db/prod
RUN pip install --index-url https://user:$PIP_TOKEN@pypi.example/simple .
FROM gcr.io/distroless/python3
COPY --from=build /app /app
WORKDIR /app
EXPOSE 8080 9090/tcp
CMD ["serve", "--api-key", "sk-live-dockercmdsecret"]
'''

ENV_EXAMPLE = '''
# Copy to .env
STRIPE_SECRET_KEY=sk_live_examplevalueleaked
export DATABASE_URL="postgres://admin:hunter2@localhost/billing"
  REDIS_URL = redis://localhost:6379
# COMMENTED_OUT=yes
NOT A VARIABLE
'''

SECRET_VALUES = ("sk_live_examplevalueleaked", "hunter2", "ghp_supersecretbuildtoken",
                 "sk-live-dockercmdsecret", "redis://localhost:6379", "postgres://")


def make_project(root: Path) -> None:
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    (root / "package.json").write_text(json.dumps(PACKAGE_JSON), encoding="utf-8")
    (root / "Cargo.toml").write_text(CARGO, encoding="utf-8")
    (root / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
    (root / ".env.example").write_text(ENV_EXAMPLE, encoding="utf-8")
    (root / ".env").write_text("REAL_ONLY_IN_DOTENV=never-read-this\n", encoding="utf-8")
    (root / "uv.lock").write_text("", encoding="utf-8")
    (root / "package-lock.json").write_text("{}", encoding="utf-8")


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "Billing Service"
        self.root.mkdir()
        make_project(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_extracts_baseline_facts_without_secret_values(self):
        result = scan_project(self.root)
        facts = {item["slot"]: item["value"] for item in result["facts"]}
        self.assertEqual(result["namespace"], "project.billing-service")
        self.assertEqual(result["llm_tokens"], 0)
        self.assertEqual(result["errors"], [])
        self.assertGreaterEqual(len(facts), 10)
        self.assertEqual(facts["python_package"], "billing-api 1.4.2")
        self.assertEqual(facts["python_requires"], ">=3.11")
        self.assertEqual(facts["python_dependencies"], "fastapi, sqlalchemy, redis")
        self.assertEqual(facts["python_test_framework"], "pytest")
        self.assertEqual(facts["python_package_manager"], "uv")
        self.assertEqual(facts["license"], "Apache-2.0")
        self.assertEqual(facts["node_frameworks"], "TypeScript, React, Vite")
        self.assertEqual(facts["node_test_framework"], "Vitest")
        self.assertEqual(facts["node_package_manager"], "npm")
        self.assertEqual(facts["rust_crate"], "ledger-core 0.9.0")
        self.assertEqual(facts["rust_frameworks"], "Tokio, Serde")
        self.assertEqual(facts["docker_base_images"], "python:3.12-slim, gcr.io/distroless/python3")
        self.assertEqual(facts["docker_exposed_ports"], "8080, 9090/tcp")
        self.assertEqual(facts["env_keys"], "STRIPE_SECRET_KEY, DATABASE_URL, REDIS_URL")
        self.assertEqual(facts["languages"], "Python, TypeScript, Rust")
        everything = json.dumps(result)
        for secret in SECRET_VALUES + ("never-read-this", "REAL_ONLY_IN_DOTENV"):
            self.assertNotIn(secret, everything)
        for value in facts.values():
            self.assertLessEqual(estimate_tokens(value), 40)

    def test_scan_is_fast_and_deterministic(self):
        first = scan_project(self.root)
        second = scan_project(self.root)
        self.assertEqual(first["facts"], second["facts"])
        self.assertLess(second["elapsed_ms"], 250)  # target is <20 ms; CI disks vary

    def test_mini_toml_matches_tomllib_on_manifests(self):
        for text in (PYPROJECT, CARGO, (Path(__file__).parents[1] / "pyproject.toml").read_text("utf-8")):
            self.assertEqual(_MiniToml(text).parse(), parse_toml(text))

    def test_bad_manifest_is_reported_not_fatal(self):
        (self.root / "Cargo.toml").write_text("[package\nname = ", encoding="utf-8")
        result = scan_project(self.root)
        self.assertEqual([error["file"] for error in result["errors"]], ["Cargo.toml"])
        self.assertIn("python_package", {item["slot"] for item in result["facts"]})

    def test_env_key_names_never_return_values(self):
        self.assertEqual(env_key_names(ENV_EXAMPLE), ["STRIPE_SECRET_KEY", "DATABASE_URL", "REDIS_URL"])

    def test_apply_respects_confirmed_and_deleted_slots_and_reports_stale(self):
        with MemtyLedger(Path(self.tmp.name) / "ledger.sqlite3") as ledger:
            ns = "project.billing-service"
            ledger.record(ns, "python_requires", ">=3.12", verification_state="USER_CONFIRMED")
            ledger.record(ns, "license", "MIT")
            ledger.forget(ns, "license")
            scan = scan_project(self.root)
            first = apply_scan(ledger, scan)
            skipped = {item["slot"]: item["reason"] for item in first["skipped"]}
            self.assertEqual(skipped, {"python_requires": "user_confirmed", "license": "deleted_by_user"})
            self.assertEqual(ledger.find(ns, "python_requires")["value"], ">=3.12")
            self.assertTrue(ledger.find(ns, "license")["tombstone"])
            saved = ledger.find(ns, "python_package")
            self.assertEqual(saved["verification_state"], "EXTRACTED")
            self.assertEqual(saved["source_id"], "scan:pyproject.toml")

            again = apply_scan(ledger, scan_project(self.root))
            self.assertEqual(again["saved"] + again["updated"], [])
            self.assertEqual(len(again["unchanged"]), len(first["saved"]))

            (self.root / "Cargo.toml").unlink()
            third = apply_scan(ledger, scan_project(self.root))
            self.assertIn("rust_crate", third["stale"])
            self.assertIn("languages", third["updated"])

    def test_dry_run_writes_nothing(self):
        with MemtyLedger(Path(self.tmp.name) / "ledger.sqlite3") as ledger:
            result = apply_scan(ledger, scan_project(self.root), dry_run=True)
            self.assertTrue(result["saved"])
            self.assertEqual(ledger.list(), [])


class InboxTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = MemtyLedger(Path(self.tmp.name) / "ledger.sqlite3")
        self.ledger.record("project.api", "cache_engine", "Redis", verification_state="USER_CONFIRMED",
                           sensitivity="CONFIDENTIAL", blocked_providers=["perplexity"])

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_new_slot_is_applied_as_extracted(self):
        result = self.ledger.propose("project.api", "queue", "SQS", proposed_by="Cursor")
        self.assertEqual(result["status"], "applied")
        fact = self.ledger.find("project.api", "queue")
        self.assertEqual((fact["value"], fact["verification_state"], fact["source_id"]),
                         ("SQS", "EXTRACTED", "agent:cursor"))
        self.assertEqual(self.ledger.propose("project.api", "queue", "SQS")["status"], "unchanged")

    def test_conflict_with_confirmed_fact_is_staged_not_written(self):
        result = self.ledger.propose("project.api", "cache_engine", "DragonflyDB",
                                     proposed_by="Cursor", reason="docker-compose uses dragonfly")
        self.assertEqual(result["status"], "pending_review")
        self.assertNotIn("Redis", json.dumps(result))  # the existing value is never echoed back
        self.assertEqual(self.ledger.find("project.api", "cache_engine")["value"], "Redis")
        inbox = self.ledger.proposals()
        self.assertEqual(len(inbox), 1)
        self.assertEqual((inbox[0]["previous_value"], inbox[0]["value"], inbox[0]["previous_state"]),
                         ("Redis", "DragonflyDB", "USER_CONFIRMED"))
        text = format_inbox(inbox)
        self.assertIn(f'[{inbox[0]["id"]}] project.api -> cache_engine: "Redis" [confirmed] => '
                      '"DragonflyDB" (Proposed by Cursor)', text)

    def test_duplicates_collapse_and_newer_proposals_supersede(self):
        first = self.ledger.propose("project.api", "cache_engine", "Memcached")
        dup = self.ledger.propose("project.api", "cache_engine", "Memcached")
        self.assertEqual(dup["proposal_id"], first["proposal_id"])
        newer = self.ledger.propose("project.api", "cache_engine", "DragonflyDB")
        self.assertEqual([item["id"] for item in self.ledger.proposals()], [newer["proposal_id"]])
        states = {item["id"]: item["status"] for item in self.ledger.proposals(status=None)}
        self.assertEqual(states[first["proposal_id"]], "SUPERSEDED")

    def test_approve_confirms_value_without_weakening_privacy(self):
        pid = self.ledger.propose("project.api", "cache_engine", "DragonflyDB",
                                  proposed_by="cursor")["proposal_id"]
        result = self.ledger.resolve_proposal(pid, approve=True)
        self.assertEqual(result["status"], "approved")
        fact = self.ledger.find("project.api", "cache_engine")
        self.assertEqual((fact["value"], fact["verification_state"], fact["sensitivity"], fact["version"]),
                         ("DragonflyDB", "USER_CONFIRMED", "CONFIDENTIAL", 2))
        self.assertEqual(fact["blocked_providers"], ["perplexity"])
        self.assertEqual([item["value"] for item in self.ledger.history("project.api", "cache_engine")],
                         ["Redis", "DragonflyDB"])
        with self.assertRaisesRegex(ValueError, "already approved"):
            self.ledger.resolve_proposal(pid, approve=False)
        self.assertEqual(self.ledger.proposals(), [])

    def test_reject_leaves_fact_alone(self):
        pid = self.ledger.propose("project.api", "cache_engine", "DragonflyDB")["proposal_id"]
        self.assertEqual(self.ledger.resolve_proposal(pid, approve=False)["status"], "rejected")
        self.assertEqual(self.ledger.find("project.api", "cache_engine")["value"], "Redis")
        with self.assertRaisesRegex(ValueError, "not found"):
            self.ledger.resolve_proposal(9999, approve=True)

    def test_deleted_slot_needs_approval_and_forget_purges_proposals(self):
        self.ledger.record("project.api", "region", "us-east-1")
        self.ledger.forget("project.api", "region")
        staged = self.ledger.propose("project.api", "region", "eu-west-1")
        self.assertEqual(staged["status"], "pending_review")
        self.assertEqual(self.ledger.proposals()[0]["previous_state"], "DELETED")
        self.ledger.propose("project.api", "cache_engine", "DragonflyDB")
        self.ledger.forget("project.api", "cache_engine")
        remaining = json.dumps(self.ledger.proposals(status=None))
        self.assertNotIn("DragonflyDB", remaining)
        self.assertNotIn("Redis", remaining)
        self.assertIn("eu-west-1", remaining)


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = MemtyLedger(Path(self.tmp.name) / "ledger.sqlite3")
        self.ledger.record("project.api", "framework", "FastAPI", verification_state="USER_CONFIRMED")
        self.ledger.record("project.api", "database", "Postgres 16", verification_state="USER_CONFIRMED",
                           source_raw="We picked Postgres 16 after a long benchmark discussion. " * 40)
        self.ledger.record("project.api", "client", "Acme Corp", sensitivity="CONFIDENTIAL")
        self.ledger.record("project.vault", "root_token", "hvs.do-not-share", sensitivity="SECRET")

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def test_served_capsule_logs_counts_and_slot_names_but_no_values(self):
        result = self.ledger.context("", provider="anthropic", namespace="project.api", strict_namespace=True)
        receipt = log_served(self.ledger, "web", "anthropic", result, namespace="project.api")
        self.assertEqual(receipt["facts_injected"], 3)
        self.assertGreater(receipt["baseline_tokens"], receipt["tokens_injected"])  # includes raw source
        stored = self.ledger.receipts()[0]
        self.assertEqual(stored["redacted"], 1)
        self.assertEqual(stored["verified_facts"], 2)
        self.assertCountEqual(stored["slots_used"],
                              ["project.api.framework", "project.api.database", "project.api.client"])
        everything = json.dumps(self.ledger.receipts()) + json.dumps(self.ledger.report())
        for value in ("FastAPI", "Postgres", "Acme Corp", "hvs.do-not-share"):
            self.assertNotIn(value, everything)
        hits = {fact["slot"]: fact["hit_count"] for fact in self.ledger.list(namespace="project.api")}
        self.assertEqual(hits, {"framework": 1, "database": 1, "client": 1})

    def test_report_aggregates_clients_reuse_savings_and_secrets(self):
        for provider in ("anthropic", "perplexity"):
            result = self.ledger.context("", provider=provider, namespace="project.api", strict_namespace=True)
            log_served(self.ledger, "web", provider, result, namespace="project.api")
        result = self.ledger.context("framework", provider="mcp", namespace="project.api", strict_namespace=True)
        log_served(self.ledger, "mcp", "mcp", result, namespace="project.api", client="Cursor")
        log_blocked(self.ledger, "mcp", "mcp", namespace="project.vault", client="Cursor")
        report = self.ledger.report()
        self.assertEqual(report["capsules_served"], 3)
        self.assertEqual(report["requests"], 4)
        self.assertEqual(report["clients"], {"anthropic": 1, "cursor": 1, "perplexity": 1})
        self.assertEqual(report["distinct_verified_facts_reused"], 2)
        self.assertEqual(report["secret_requests_blocked"], 1)
        self.assertEqual(report["secret_slots_protected"], 1)
        self.assertGreater(report["tokens_saved_estimate"], 0)
        self.assertEqual(report["top_facts"][0]["hits"], 3)
        headline = format_report(report).splitlines()[0]
        self.assertRegex(headline, r"^3 capsules served across Claude, Cursor & Perplexity \| "
                                   r"2 verified facts reused \| ~[\d,]+ tokens saved \| "
                                   r"1 SECRET slot protected$")

    def test_receipt_failures_never_break_serving(self):
        class Broken:
            def log_receipt(self, *args, **kwargs):
                raise RuntimeError("disk full")
        self.assertIsNone(log_served(Broken(), "recall", "local", {"citations": []}))
        self.assertIsNone(log_blocked(Broken(), "recall", "openai"))

    def test_report_since_filters_old_receipts(self):
        result = self.ledger.context("", provider="local", namespace="project.api", strict_namespace=True)
        log_served(self.ledger, "recall", "local", result, namespace="project.api")
        self.assertEqual(self.ledger.report(since_ms=2**62)["capsules_served"], 0)
        self.assertEqual(self.ledger.report()["capsules_served"], 1)


class BridgeReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "ledger.sqlite3"
        self.ledger = MemtyLedger(db)
        self.token = load_or_create_token(db)
        self.server = BridgeServer(PerCallLedger(db), self.token, port=0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.ledger.record("work.project", "editor", "VS Code", verification_state="USER_CONFIRMED")
        self.ledger.record("work.project", "client", "Acme Corp", sensitivity="CONFIDENTIAL")
        self.ledger.record("work.secret", "key", "sk-123", sensitivity="SECRET")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.ledger.close()
        self.tmp.cleanup()

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.port, timeout=10)
        conn.request("GET", path, headers={"Host": f"127.0.0.1:{self.server.port}", "Origin": EXT,
                                           "Authorization": "Bearer " + self.token})
        response = conn.getresponse()
        body = json.loads(response.read())
        conn.close()
        return response.status, body

    def test_browser_capsules_and_blocks_are_receipted(self):
        status, body = self.get("/capsule?namespace=work.project&provider=perplexity")
        self.assertEqual(status, 200, body)
        status, _ = self.get("/capsule?namespace=work.secret&provider=openai")
        self.assertEqual(status, 409)
        blocked, served = self.ledger.receipts(limit=2)
        self.assertEqual((served["channel"], served["client"], served["facts_injected"], served["redacted"]),
                         ("web", "perplexity", body["facts"], 1))
        self.assertEqual(served["tokens_injected"], body["approx_tokens"])
        self.assertEqual((blocked["client"], blocked["secrets_blocked"]), ("openai", 1))

    def test_selected_context_receipt_and_no_internal_ids_sent(self):
        saved = self.ledger.record_context("work.project", [{"slot": "stack", "value": "Django"}])
        status, body = self.get("/capsule?namespace=work.project&provider=openai&tokens=2000&context="
                                + saved["context_id"])
        self.assertEqual(status, 200, body)
        self.assertNotIn("fact_ids", body)
        self.assertEqual(self.ledger.receipts()[0]["facts_injected"], 1)


class PairWrongVaultTests(unittest.TestCase):
    """A bridge for another vault on the port must make `memty pair` fail loudly."""

    def test_pair_refuses_a_bridge_serving_a_different_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp) / "other.sqlite3"
            mine = Path(tmp) / "mine.sqlite3"
            server = BridgeServer(PerCallLedger(other), load_or_create_token(other), port=0)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1]))
                result = subprocess.run(
                    [sys.executable, "-m", "memty", "--db", str(mine), "pair", "--port", str(server.port)],
                    env=env, capture_output=True, text=True, timeout=60)
            finally:
                server.shutdown()
                server.server_close()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Cannot pair", result.stderr)
            self.assertIn("different", result.stderr)
            self.assertNotIn("Pairing is open", result.stdout)


class CliAndMcpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "vault.sqlite3"
        self.env = dict(os.environ, MEMTY_DB=str(self.db), PYTHONPATH=str(Path(__file__).parents[1]))

    def tearDown(self):
        from memty.runtime.daemon import stop
        stop(self.db)
        self.tmp.cleanup()

    def memty(self, *args, cwd=None):
        result = subprocess.run([sys.executable, "-m", "memty", "--db", str(self.db), *args],
                                env=self.env, cwd=cwd, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result.stdout

    def test_scan_recall_report_from_the_cli(self):
        project = Path(self.tmp.name) / "shop"
        project.mkdir()
        make_project(project)
        out = self.memty("scan", str(project))
        self.assertIn("(0 LLM tokens)", out)
        self.assertIn("project.shop:", out)
        self.assertIn("+ python_package = billing-api 1.4.2", out)
        for secret in SECRET_VALUES:
            self.assertNotIn(secret, out)
        self.assertIn("0 saved", self.memty("scan", str(project)))
        recalled = json.loads(self.memty("recall", "python", "--namespace", "project.shop"))
        self.assertTrue(recalled["citations"])
        self.assertIn("1 capsule served across Local", self.memty("report"))
        self.assertIn("recall", self.memty("receipts"))

    def test_init_bootstraps_the_current_project_and_writes_no_model_catalog(self):
        project = Path(self.tmp.name) / "shop"
        project.mkdir()
        make_project(project)
        home = Path(self.tmp.name) / "home"
        env = dict(self.env, HOME=str(home), USERPROFILE=str(home))
        result = subprocess.run([sys.executable, "-m", "memty", "--db", str(self.db), "init"],
                                env=env, cwd=project, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("project.shop:", result.stdout)
        self.assertFalse((home / ".memty" / "models.json").exists())

    def test_model_routing_commands_are_gone(self):
        for command in ("models", "route", "chat", "integration", "router-mcp"):
            result = subprocess.run([sys.executable, "-m", "memty", command], env=self.env,
                                    capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 2, command)
            self.assertIn("invalid choice", result.stderr)

    def test_mcp_propose_lands_in_inbox_with_client_name(self):
        self.memty("remember", "project.api", "cache_engine", "Redis")

        async def exercise():
            params = StdioServerParameters(command=sys.executable, args=["-m", "memty", "mcp"], env=self.env)
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer,
                                         client_info=Implementation(name="cursor", version="1.0")) as session:
                    await session.initialize()
                    staged = await session.call_tool("memty_propose", {
                        "namespace": "project.api", "slot": "cache_engine", "value": "DragonflyDB"})
                    self.assertFalse(staged.isError)
                    self.assertIn("pending_review", str(staged.content))
                    self.assertNotIn("Redis", str(staged.content))
                    capsule = await session.call_tool("memty_sync", {"namespace": "project.api"})
                    self.assertIn("Redis", str(capsule.content))  # unchanged until approved

        asyncio.run(exercise())
        inbox = self.memty("inbox")
        self.assertIn('project.api -> cache_engine: "Redis" [confirmed] => "DragonflyDB" (Proposed by Cursor)',
                      inbox)
        proposal_id = inbox.split("]", 1)[0].lstrip("[")
        self.assertIn("approved", self.memty("approve", proposal_id))
        listing = json.loads(self.memty("list", "--namespace", "project.api"))
        self.assertEqual(listing[0]["value"], "DragonflyDB")
        self.assertEqual(listing[0]["hit_count"], 1)
        receipt = json.loads(self.memty("receipts", "--json"))[0]
        self.assertEqual((receipt["channel"], receipt["client"]), ("mcp", "cursor"))
        self.assertIn("Inbox is empty", self.memty("inbox"))


if __name__ == "__main__":
    unittest.main()
