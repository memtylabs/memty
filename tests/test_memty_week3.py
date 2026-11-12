"""Week 3: localhost web bridge, local fact extraction, and memty clip."""
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from memty.extraction.atomic_facts import extract_facts, extract_heuristic
from memty.vault.ledger import MemtyLedger
from memty.vault.tokens import estimate_tokens
from memty.integrations.browser.bridge import (BridgeServer, load_or_create_token, open_pairing, paired_origins,
                               token_path)

EXT = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


class ExtractTests(unittest.TestCase):
    def test_titles_prefer_acronyms_entities_and_inline_identifiers(self):
        facts = extract_heuristic("- You pointed out a critical issue: MCP tools and JSON responses burn extra tokens.\n"
                                  "- The `memty_sync` function carries the MCP schema.\n"
                                  "- Use Redis for the rate limiter.")
        self.assertEqual(facts[0]["slot"], "mcp_json_tokens")
        self.assertIn("memty_sync", facts[1]["slot"])
        self.assertIn("mcp", facts[1]["slot"])
        self.assertIn("redis", facts[2]["slot"])
        self.assertNotIn("pointed_out_critical", [f["slot"] for f in facts])

    def test_bullets_and_key_values_become_valid_slots(self):
        answer = """Here is the plan:

- **Database**: PostgreSQL 16 on [Neon](https://neon.tech) [1]
- Deploy target: Fly.io
* The API uses FastAPI and runs on port 8000.
1. Deadline: March 3
- Database: SQLite for tests
- What should we do next?
- Deploy target: Fly.io
"""
        facts = extract_heuristic(answer)
        by_slot = {f["slot"]: f["value"] for f in facts}
        self.assertEqual(by_slot["database"], "PostgreSQL 16 on Neon (https://neon.tech)")
        self.assertEqual(by_slot["database_2"], "SQLite for tests")
        self.assertEqual(by_slot["deploy_target"], "Fly.io")
        self.assertEqual(by_slot["deadline"], "March 3")
        self.assertIn("The API uses FastAPI and runs on port 8000.", by_slot.values())
        self.assertFalse(any(v.endswith("?") for v in by_slot.values()))
        self.assertEqual(len(facts), 5)  # duplicate "Deploy target" dropped
        with tempfile.TemporaryDirectory() as tmp, MemtyLedger(Path(tmp) / "v.sqlite3") as ledger:
            for fact in facts:  # every proposed slot/value is accepted by the ledger
                ledger.record("work.project", fact["slot"], fact["value"])

    def test_code_from_answers_is_not_saved_as_facts(self):
        # Regression: Gemini answers produced conn="sqlite3.connect(...)" and namespace="str".
        answer = """Here is how to fix it:
def open(self, namespace: str):
    conn = sqlite3.connect(self.dbpath, timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn
namespace: str
items: list[str] | None = None
db_path: os.path.join(home, ".memty")
const port = 8765;
// comment: not a fact
```python
x: int
```
- Timeout: 5 seconds avoids lock errors
- Database: PostgreSQL 16 (Neon)
- Use connect() with a timeout
"""
        facts = {f["slot"]: f["value"] for f in extract_heuristic(answer)}
        self.assertEqual(facts.pop("timeout"), "5 seconds avoids lock errors")
        self.assertEqual(facts.pop("database"), "PostgreSQL 16 (Neon)")
        self.assertEqual(list(facts.values()), ["Use connect() with a timeout"])

    def test_headings_paths_and_pasted_capsules_are_not_facts(self):
        # Regression: Gemini answers produced file_1="memty-extension/manifest.json" and
        # note_x="The 2-File Chrome Extension Bridge (Perplexity, ChatGPT, Claude, Gemini)".
        answer = """[Memty context for work.project: facts I saved earlier.]
- Editor: Old value from the capsule
[/Memty]
<memty_state v="1" provider="google"><slots>
work.project.x="also old"
</slots></memty_state>
- The 2-File Chrome Extension Bridge (Perplexity, ChatGPT, Claude, Gemini)
- File 1: memty-extension/manifest.json
- File 2: memty-extension/content.js
- Deploy target: Fly.io
- Done
- The bridge only listens on 127.0.0.1 for safety.
"""
        facts = {f["slot"]: f["value"] for f in extract_heuristic(answer)}
        self.assertEqual(facts, {
            "deploy_target": "Fly.io",
            "bridge_listens_safety": "The bridge only listens on 127.0.0.1 for safety.",
            "files": "memty-extension/manifest.json, memty-extension/content.js",
        })

    def test_code_blocks_are_summarized_not_copied(self):
        answer = """Use this schema:
```python
# memty/db.py
class Ledger:
    def connect(self):
        return sqlite3.connect(self.path)
    def record(self, slot, value):
        pass
```
```sql
CREATE TABLE IF NOT EXISTS atomic_facts (id TEXT);
```
- Storage: SQLite in WAL mode
"""
        facts = {f["slot"]: f["value"] for f in extract_heuristic(answer)}
        self.assertEqual(facts.pop("storage"), "SQLite in WAL mode")
        self.assertEqual(sorted(facts.values()), [
            "Python code in memty/db.py defines connect, record, Ledger",
            "SQL code defines atomic_facts",
        ])
        selected = "function findEditor() {\n  return null;\n}\nconst place = () => {\n  editor = findEditor();\n};"
        self.assertEqual([f["value"] for f in extract_heuristic(selected)],
                         ["JavaScript code defines findEditor, place"])
        self.assertEqual(extract_heuristic("x = 1\ny = 2\nz = x + y"), [])

    def test_prose_fallback_and_caps(self):
        facts = extract_heuristic("Paris is the capital of France. It has about two million residents. Ok.")
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]["value"], "Paris is the capital of France. It has about two million residents.")
        long = "- " + " ".join(["word"] * 200)
        self.assertLessEqual(estimate_tokens(extract_heuristic(long)[0]["value"]), 40)
        many = "\n".join(f"- fact number {i}" for i in range(40))
        self.assertEqual(len(extract_heuristic(many)), 25)
        self.assertIn("Only the first 25", extract_facts(many)["warnings"][0])

    def test_mixed_prose_and_lists_keep_context_and_distinct_keys(self):
        selection = """The service uses a shared SQLite vault. It remains on the user's computer.

- **Decision**: Use C# for the agent and keep Redis as a backup.
- Retry limit: 3 attempts
- Timeout: 3 attempts
- Time complexity: O(n)
- Rule: status != archived
- If the cache fails, reject requests unless the user approves a fallback.
- Use Redis

Requests must not be sent to the cloud unless the user explicitly approves them.
"""
        facts = extract_facts(selection)["facts"]
        values = {item["slot"]: item["value"] for item in facts}
        self.assertIn("The service uses a shared SQLite vault. It remains on the user's computer.", values.values())
        self.assertEqual(values["decision"], "Use C# for the agent and keep Redis as a backup.")
        self.assertEqual(values["retry_limit"], "3 attempts")
        self.assertEqual(values["timeout"], "3 attempts")
        self.assertEqual(values["time_complexity"], "O(n)")
        self.assertEqual(values["rule"], "status != archived")
        self.assertIn("If the cache fails, reject requests unless the user approves a fallback.", values.values())
        self.assertIn("Use Redis", values.values())
        self.assertIn("Requests must not be sent to the cloud unless the user explicitly approves them.", values.values())

    def test_long_fact_keeps_its_ending_and_reports_limits(self):
        value = ("The service uses a local SQLite database and keeps every confirmed decision in a shared vault "
                 "so the user can continue the same project across editors and assistants while retaining "
                 "the original details including the reason for the choice and its constraints. "
                 "Never send private client details to a cloud provider without explicit approval.")
        result = extract_facts("- Decision: " + value)
        self.assertGreater(len(result["facts"]), 1)
        self.assertEqual(" ".join(f["value"] for f in result["facts"]), value)
        self.assertTrue(all(estimate_tokens(f["value"]) <= 40 for f in result["facts"]))
        self.assertTrue(any("split" in warning for warning in result["warnings"]))
        oversized = extract_facts("- Identifier: " + "x" * 200 + " remains local")
        self.assertTrue(any("too long" in warning for warning in oversized["warnings"]))

    def test_ollama_long_output_is_split_without_cutting_words(self):
        class Reply:
            def read(self):
                return json.dumps({"response": json.dumps({"facts": [{"slot": "decision", "value": value}]})}).encode()
            def __enter__(self): return self
            def __exit__(self, *exc): return False
        value = " ".join(["preserve"] * 55) + " and never send secrets"
        with patch.dict(os.environ, {"MEMTY_OLLAMA_MODEL": "local"}), \
             patch("memty.extraction.atomic_facts.urlrequest.urlopen", return_value=Reply()):
            result = extract_facts("A long decision.")
        self.assertEqual(" ".join(f["value"] for f in result["facts"]), value)
        self.assertTrue(any("split" in warning for warning in result["warnings"]))

    def test_ollama_is_used_when_configured_and_falls_back(self):
        class Reply:
            def __init__(self, data): self.data = data
            def read(self): return self.data
            def __enter__(self): return self
            def __exit__(self, *exc): return False
        payload = json.dumps({"response": json.dumps({"facts": [
            {"slot": "Main Language", "value": "Python"}, {"slot": "x", "value": ""}]})}).encode()
        with patch.dict(os.environ, {"MEMTY_OLLAMA_MODEL": "llama3"}), \
             patch("memty.extraction.atomic_facts.urlrequest.urlopen", return_value=Reply(payload)) as call:
            result = extract_facts("We write everything in Python.")
        self.assertEqual(result, {"facts": [{"slot": "main_language", "value": "Python"}], "method": "ollama"})
        self.assertTrue(call.call_args[0][0].full_url.startswith("http://127.0.0.1:11434/"))
        with patch.dict(os.environ, {"MEMTY_OLLAMA_MODEL": "llama3"}), \
             patch("memty.extraction.atomic_facts.urlrequest.urlopen", side_effect=OSError("refused")):
            self.assertEqual(extract_facts("- Editor: VS Code")["method"], "heuristic")


class PerCallLedger:
    """Like DaemonLedger in production: no SQLite handle outlives a request thread."""
    def __init__(self, path):
        self.path = path

    def __getattr__(self, name):
        def call(*args, **kwargs):
            with MemtyLedger(self.path) as ledger:
                return getattr(ledger, name)(*args, **kwargs)
        return call


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = Path(self.tmp.name) / "ledger.sqlite3"
        self.ledger = MemtyLedger(db)
        self.token = load_or_create_token(db)
        self.server = BridgeServer(PerCallLedger(db), self.token, port=0)
        self.port = self.server.port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.ledger.record("work.project", "editor", "VS Code", verification_state="USER_CONFIRMED")
        self.ledger.record("work.project", "client", "Acme Corp", sensitivity="CONFIDENTIAL")
        self.ledger.record("personal", "color", "green")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.ledger.close()
        self.tmp.cleanup()

    def request(self, method, path, body=None, *, token=True, origin=EXT, host=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or f"127.0.0.1:{self.port}"}
        if token:
            h["Authorization"] = "Bearer " + (self.token if token is True else token)
        if origin:
            h["Origin"] = origin
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        conn.request(method, path, body=data, headers=h)
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        return response.status, (json.loads(raw) if raw else None), dict(response.getheaders())

    def test_binds_loopback_only_and_token_file_is_private(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        path = token_path(self.ledger.path)
        self.assertEqual(load_or_create_token(self.ledger.path), self.token)
        if os.name != "nt":
            self.assertEqual(path.stat().st_mode & 0o077, 0)
        self.assertNotEqual(load_or_create_token(self.ledger.path, rotate=True), self.token)

    def test_start_rejects_a_bridge_for_a_different_vault_or_user(self):
        from memty.integrations.browser.bridge import start_background
        same = start_background(self.ledger.path, "local", port=self.port)
        self.assertTrue(same["already_running"])
        with self.assertRaisesRegex(RuntimeError, "different or older"):
            start_background(self.ledger.path, "another-user", port=self.port)
        other = Path(self.tmp.name) / "other.sqlite3"
        with self.assertRaisesRegex(RuntimeError, "different or older"):
            start_background(other, "local", port=self.port)
        self.assertFalse(token_path(other).exists())

    def test_capsule_is_namespace_scoped_redacted_and_within_200_tokens(self):
        status, body, headers = self.request("GET", "/capsule?namespace=work.project&provider=openai")
        self.assertEqual(status, 200, body)
        self.assertIn("VS Code", body["text"])
        self.assertNotIn("green", body["text"])        # other namespace
        self.assertNotIn("Acme Corp", body["text"])    # CONFIDENTIAL for a cloud provider
        self.assertEqual(body["redacted"], 1)
        self.assertNotIn("redactions", body)           # real values never reach the browser
        self.assertNotIn("Acme Corp", json.dumps(body))
        self.assertLessEqual(estimate_tokens(body["text"]), 200)
        self.assertCountEqual(body["text"].splitlines(), ["Client: [private]", "Editor: VS Code"])
        self.assertNotIn("MEMTY_REDACTED", body["text"])
        self.assertEqual(body["facts"], 2)
        self.assertEqual(headers["Access-Control-Allow-Origin"], EXT)
        status, body, _ = self.request("GET", "/capsule?namespace=work.project&provider=openai&format=xml")
        self.assertTrue(body["text"].startswith("<memty_state"))
        status, _, _ = self.request("GET", "/capsule?namespace=work.project&format=html")
        self.assertEqual(status, 400)
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_secret_facts_are_refused(self):
        self.ledger.record("work.project", "api_key", "sk-123", sensitivity="SECRET")
        status, body, _ = self.request("GET", "/capsule?namespace=work.project&provider=perplexity")
        self.assertEqual(status, 409)
        self.assertEqual(body["error"], "local_routing_required")
        self.assertNotIn("sk-123", json.dumps(body))

    def test_capsule_reports_when_saved_facts_do_not_fit(self):
        facts = [{"slot": f"detail_{i}", "value": f"Detail {i} keeps the important condition and its final outcome"}
                 for i in range(8)]
        status, body, _ = self.request("POST", "/facts", {
            "namespace": "work.project", "confirmed": True, "facts": facts})
        self.assertEqual((status, len(body["saved"])), (200, 8))
        status, body, _ = self.request("GET", "/capsule?namespace=work.project&provider=openai&tokens=60")
        self.assertEqual(status, 200)
        self.assertGreater(body["omitted"], 0)
        self.assertEqual(body["facts"] + body["omitted"], 8)
        self.assertLessEqual(estimate_tokens(body["text"]), 60)

    def test_web_pages_and_rebinding_are_blocked(self):
        for origin in ("https://evil.example", "null", "http://127.0.0.1:9999"):
            status, body, headers = self.request("GET", "/capsule?namespace=work.project", origin=origin)
            self.assertEqual((status, body["error"]), (403, "origin_not_allowed"))
            self.assertNotIn("Access-Control-Allow-Origin", headers)
            status, _, headers = self.request("OPTIONS", "/facts", origin=origin, token=False)
            self.assertEqual(status, 403)
            self.assertNotIn("Access-Control-Allow-Origin", headers)
        status, body, _ = self.request("GET", "/capsule?namespace=work.project", host="evil.example:8765")
        self.assertEqual((status, body["error"]), (403, "bad_host"))
        status, body, _ = self.request("GET", "/health", origin="https://evil.example", token=False)
        self.assertEqual(status, 403)

    def test_token_is_required(self):
        for token in (False, "wrong"):
            status, body, _ = self.request("GET", "/capsule?namespace=work.project", token=token)
            self.assertEqual((status, body["error"]), (401, "unauthorized"))
            status, _, _ = self.request("POST", "/facts", {"namespace": "x", "facts": [{}]}, token=token)
            self.assertEqual(status, 401)
        status, body, _ = self.request("GET", "/health", token=False)
        self.assertEqual((status, body), (200, {"ok": True, "service": "memty"}))
        status, body, _ = self.request("GET", "/contexts?provider=openai", token=False)
        self.assertEqual((status, body["error"]), (401, "unauthorized"))

    def test_extension_pairs_itself_once(self):
        status, body, _ = self.request("POST", "/pair", {}, token=False)
        self.assertEqual((status, body["token"]), (200, self.token))
        self.assertEqual(paired_origins(self.ledger.path), [EXT])
        status, body, _ = self.request("POST", "/pair", {}, token=False)  # same extension again
        self.assertEqual(status, 200)
        other = "chrome-extension://zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"
        status, body, _ = self.request("POST", "/pair", {}, token=False, origin=other)
        self.assertEqual((status, body["error"]), (403, "pairing_required"))
        self.assertIn("memty pair", body["message"])
        self.assertNotIn(self.token, json.dumps(body))
        open_pairing(self.ledger.path, 60)  # `memty pair`: the next browser may join
        status, body, _ = self.request("POST", "/pair", {}, token=False, origin=other)
        self.assertEqual((status, body["token"]), (200, self.token))
        self.assertEqual(paired_origins(self.ledger.path), [EXT, other])
        third = "chrome-extension://yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy"
        status, _, _ = self.request("POST", "/pair", {}, token=False, origin=third)
        self.assertEqual(status, 403)  # the window closes after one browser joins
        for origin in ("https://evil.example", None):  # web pages and non-browser callers
            status, body, _ = self.request("POST", "/pair", {}, token=False, origin=origin)
            self.assertEqual(status, 403)
            self.assertNotIn("token", body)
        load_or_create_token(self.ledger.path, rotate=True)  # --new-token forgets the pairing
        self.assertEqual(paired_origins(self.ledger.path), [])

    def test_namespaces_include_counts_for_auto_selection(self):
        status, body, _ = self.request("GET", "/namespaces")
        self.assertEqual(body["counts"], {"personal": 1, "work.project": 2})

    def test_extension_preflight(self):
        status, _, headers = self.request("OPTIONS", "/facts", token=False, headers={
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Private-Network": "true"})
        self.assertEqual(status, 204)
        self.assertEqual(headers["Access-Control-Allow-Origin"], EXT)
        self.assertIn("Authorization", headers["Access-Control-Allow-Headers"])
        self.assertEqual(headers["Access-Control-Allow-Private-Network"], "true")

    def test_newest_facts_fit_even_with_many_older_ones(self):
        # Regression: without a query, ties went A-Z, so a fact saved just now
        # (slot "zz_latest") never fit in the capsule.
        for i in range(40):
            self.ledger.record("work.project", f"older_{i:02d}_fact", f"older fact number {i}")
        time.sleep(0.02)  # timestamps are in milliseconds
        self.ledger.record("work.project", "zz_latest", "saved a minute ago")
        status, body, _ = self.request("GET", "/capsule?namespace=work.project&provider=openai")
        self.assertEqual(status, 200)
        self.assertEqual(body["text"].splitlines()[0], "Zz latest: saved a minute ago")
        self.assertLessEqual(estimate_tokens(body["text"]), 350)
        self.assertGreater(body["facts"], 10)

    def test_capsule_pastes_only_the_latest_save(self):
        # Regression: two separate saves (an algorithm note, then a paper review)
        # were pasted into the chat together, so the assistant mixed both topics.
        status, _, _ = self.request("POST", "/facts", {"namespace": "work.project", "confirmed": True, "facts": [
            {"slot": "space_complexity", "value": "O(1)"},
            {"slot": "time_complexity", "value": "O(n x m)"}]})
        self.assertEqual(status, 200)
        time.sleep(0.02)
        status, _, _ = self.request("POST", "/facts", {"namespace": "work.project", "confirmed": True, "facts": [
            {"slot": "hurt_publication_prospects", "value": "Missing dataset details"},
            {"slot": "make_it_stronger", "value": "Ablations with statistical support"},
            {"slot": "client", "value": "Globex"}]})
        self.assertEqual(status, 200)
        status, body, _ = self.request("GET", "/capsule?namespace=work.project&provider=openai")
        self.assertEqual(status, 200, body)
        self.assertEqual(body["text"].splitlines(), [  # saved order, nothing from the earlier save
            "Hurt publication prospects: Missing dataset details",
            "Make it stronger: Ablations with statistical support",
            "Client: [private]"])                       # still private: it was CONFIDENTIAL
        self.assertEqual((body["facts"], body["redacted"]), (3, 1))
        status, body, _ = self.request("GET", "/capsule?namespace=work.project&provider=openai&scope=all")
        self.assertIn("Space complexity: O(1)", body["text"])  # everything, as before, when asked
        status, body, _ = self.request("GET", "/capsule?namespace=work.project&scope=newest")
        self.assertEqual(status, 400)

    def test_saved_contexts_remain_separate_and_paste_numbered_in_save_order(self):
        def save(decision, other):
            return self.request("POST", "/facts", {"namespace": "work.project", "confirmed": True,
                "separate_context": True, "facts": [
                    {"slot": "decision", "value": decision},
                    {"slot": "decision_2", "value": other}]})
        status, first, _ = save("Use SQLite", "Never use the cloud")
        self.assertEqual((status, len(first["saved"]), first["skipped"]), (200, 2, []))
        status, second, _ = save("Use PostgreSQL", "Store backups locally")
        self.assertEqual((status, len(second["saved"]), second["skipped"]), (200, 2, []))
        self.assertNotEqual(first["context_id"], second["context_id"])
        status, result, _ = self.request("GET", "/contexts?provider=openai")
        self.assertEqual(status, 200)
        matching = [c for c in result["contexts"] if c["id"] in {first["context_id"], second["context_id"]}]
        self.assertEqual([c["id"] for c in matching], [second["context_id"], first["context_id"]])
        self.assertEqual([c["count"] for c in matching], [2, 2])
        for context, expected, absent in ((first, ["Use SQLite", "Never use the cloud"], "PostgreSQL"),
                                          (second, ["Use PostgreSQL", "Store backups locally"], "SQLite")):
            status, capsule, _ = self.request("GET", "/capsule?namespace=work.project&provider=openai"
                f"&format=text&tokens=2000&context={context['context_id']}")
            self.assertEqual(status, 200, capsule)
            self.assertEqual(capsule["text"].splitlines(), ["[Memty context]",
                f"1. Decision: {expected[0]}", f"2. Decision: {expected[1]}", "[/Memty]"])
            self.assertEqual((capsule["facts"], capsule["omitted"]), (2, 0))
            self.assertNotIn(absent, capsule["text"])

    def test_selected_context_privacy_and_other_secret_contexts(self):
        status, public, _ = self.request("POST", "/facts", {"namespace": "work.project", "confirmed": True,
            "separate_context": True, "facts": [{"slot": "topic", "value": "Public architecture"}]})
        self.assertEqual(status, 200)
        status, private, _ = self.request("POST", "/facts", {"namespace": "work.project", "confirmed": True,
            "separate_context": True, "facts": [{"slot": "client", "value": "Private new client"}]})
        self.assertEqual(status, 200)
        self.ledger.record("work.project", "secret_key", "sensitive-secret", sensitivity="SECRET",
                           source_id="save_0123456789abcdef")
        status, groups, _ = self.request("GET", "/contexts?provider=openai")
        self.assertEqual(status, 200)
        self.assertNotIn("Private new client", json.dumps(groups))
        self.assertNotIn("sensitive-secret", json.dumps(groups))
        public_url = ("/capsule?namespace=work.project&provider=openai&tokens=2000&context=" + public["context_id"])
        status, capsule, _ = self.request("GET", public_url)
        self.assertEqual(status, 200, capsule)  # a secret in another context does not block this one
        self.assertIn("Public architecture", capsule["text"])
        private_url = ("/capsule?namespace=work.project&provider=openai&tokens=2000&context=" + private["context_id"])
        status, capsule, _ = self.request("GET", private_url)
        self.assertEqual(status, 200, capsule)
        self.assertIn("[private]", capsule["text"])
        self.assertNotIn("Private new client", json.dumps(capsule))
        status, capsule, _ = self.request("GET", "/capsule?namespace=work.project&provider=openai"
            "&tokens=2000&context=save_0123456789abcdef")
        self.assertEqual((status, capsule["error"]), (409, "local_routing_required"))

    def test_context_pastes_ten_full_numbered_facts(self):
        items = [{"slot": f"detail_{index}", "value":
                  f"Fact {index} describes the architecture and retains its particular condition and final result"}
                 for index in range(10)]
        status, saved, _ = self.request("POST", "/facts", {"namespace": "work.project", "confirmed": True,
            "separate_context": True, "facts": items})
        self.assertEqual((status, len(saved["saved"]), saved["skipped"]), (200, 10, []))
        url = "/capsule?namespace=work.project&provider=openai&tokens=2000&context=" + saved["context_id"]
        status, capsule, _ = self.request("GET", url)
        self.assertEqual((status, capsule["facts"], capsule["omitted"]), (200, 10, 0))
        for index, item in enumerate(items, 1):
            self.assertIn(f"{index}. Detail: {item['value']}", capsule["text"])
        self.assertGreater(estimate_tokens(capsule["text"]), 200)

    def test_context_save_preserves_provider_restrictions_for_reused_titles(self):
        self.ledger.record("work.project", "restricted", "Anthropic only", allowed_providers=["anthropic"])
        status, saved, _ = self.request("POST", "/facts", {"namespace": "work.project", "confirmed": True,
            "separate_context": True, "facts": [{"slot": "restricted", "value": "Also Anthropic only"}]})
        self.assertEqual(status, 200)
        created = self.ledger.find("work.project", saved["saved"][0]["slot"])
        self.assertEqual(created["allowed_providers"], ["anthropic"])
        status, groups, _ = self.request("GET", "/contexts?provider=openai")
        context = next(item for item in groups["contexts"] if item["id"] == saved["context_id"])
        self.assertEqual(context["preview"], "Private context")
        url = "/capsule?namespace=work.project&provider=openai&tokens=2000&context=" + saved["context_id"]
        status, capsule, _ = self.request("GET", url)
        self.assertEqual((status, capsule["text"], capsule["omitted"]), (200, "", 1))

    def test_context_save_is_atomic_when_a_fact_is_invalid(self):
        before = self.ledger.stats()["active_facts"]
        status, body, _ = self.request("POST", "/facts", {"namespace": "work.project", "confirmed": True,
            "separate_context": True, "facts": [{"slot": "first", "value": "Valid fact"},
                {"slot": "second", "value": "word " * 100}]})
        self.assertEqual(status, 400, body)
        self.assertEqual(self.ledger.stats()["active_facts"], before)
        self.assertIsNone(self.ledger.find("work.project", "first"))

    def test_concurrent_saves_with_the_same_titles_do_not_overwrite_each_other(self):
        def save(index):
            return self.request("POST", "/facts", {"namespace": "work.project", "confirmed": True,
                "separate_context": True, "facts": [{"slot": "decision", "value": f"Choice {index}"}]})
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(save, range(4)))
        self.assertTrue(all(status == 200 for status, _, _ in responses), responses)
        ids = {body["context_id"] for _, body, _ in responses}
        self.assertEqual(len(ids), 4)
        status, listed, _ = self.request("GET", "/contexts?provider=openai")
        self.assertEqual(status, 200)
        found = [context for context in listed["contexts"] if context["id"] in ids]
        self.assertEqual(len(found), 4)
        self.assertEqual({context["preview"] for context in found},
                         {f"Decision: Choice {index}" for index in range(4)})

    def test_editing_or_deleting_context_facts_keeps_context_boundaries(self):
        status, saved, _ = self.request("POST", "/facts", {"namespace": "work.project", "confirmed": True,
            "separate_context": True, "facts": [{"slot": "editor", "value": "Zed"},
                                                   {"slot": "language", "value": "Python"}]})
        self.assertEqual(status, 200)
        editor_slot, language_slot = [item["slot"] for item in saved["saved"]]
        status, changed, _ = self.request("POST", "/facts/update", {"namespace": "work.project",
            "slot": editor_slot, "new_slot": "main_editor", "value": "VS Code"})
        self.assertEqual(status, 200, changed)
        url = "/capsule?namespace=work.project&provider=openai&tokens=2000&context=" + saved["context_id"]
        status, capsule, _ = self.request("GET", url)
        self.assertEqual(status, 200, capsule)
        self.assertIn("1. Main editor: VS Code", capsule["text"])
        self.assertIn("2. Language: Python", capsule["text"])
        status, _, _ = self.request("POST", "/facts/delete", {"namespace": "work.project", "slot": language_slot})
        self.assertEqual(status, 200)
        status, capsule, _ = self.request("GET", url)
        self.assertEqual((status, capsule["facts"]), (200, 1))
        self.assertNotIn("Python", capsule["text"])
        status, _, _ = self.request("POST", "/facts/delete", {"namespace": "work.project", "slot": changed["slot"]})
        self.assertEqual(status, 200)
        status, body, _ = self.request("GET", url)
        self.assertEqual((status, body["error"]), (404, "context_not_found"))

    def test_edit_keeps_internal_sensitivity_and_provider_rules(self):
        self.ledger.record("work.project", "restricted", "Original internal fact", sensitivity="INTERNAL",
                           allowed_providers=["anthropic"], blocked_providers=["openai"])
        status, listing, _ = self.request("GET", "/facts?namespace=work.project")
        fact = next(item for item in listing["facts"] if item["slot"] == "restricted")
        self.assertEqual((status, fact["private"], fact["value"]), (200, True, None))
        status, _, _ = self.request("POST", "/facts/update", {"namespace": "work.project", "slot": "restricted",
            "value": "Updated internal fact", "private": True})
        self.assertEqual(status, 200)
        saved = self.ledger.find("work.project", "restricted")
        self.assertEqual((saved["sensitivity"], saved["allowed_providers"], saved["blocked_providers"]),
                         ("INTERNAL", ["anthropic"], ["openai"]))

    def test_legacy_unbatched_facts_are_not_combined_as_one_context(self):
        status, body, _ = self.request("GET", "/contexts?namespace=work.project&provider=openai")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["contexts"]), 2)
        self.assertTrue(all(context["id"].startswith("legacy_") and context["count"] == 1
                            for context in body["contexts"]))

    def test_user_can_view_edit_and_delete_facts(self):
        status, body, _ = self.request("GET", "/facts?namespace=work.project")
        self.assertEqual(status, 200)
        by_slot = {f["slot"]: f for f in body["facts"]}
        self.assertEqual(by_slot["editor"]["value"], "VS Code")
        self.assertEqual((by_slot["client"]["value"], by_slot["client"]["private"]), (None, True))
        self.assertNotIn("Acme Corp", json.dumps(body))           # private values never reach the browser
        # Rename + edit
        status, body, _ = self.request("POST", "/facts/update", {
            "namespace": "work.project", "slot": "editor", "new_slot": "main_editor", "value": "Neovim"})
        self.assertEqual((status, body["slot"]), (200, "main_editor"))
        self.assertIsNone(self.ledger.find("work.project", "editor") and
                          not self.ledger.find("work.project", "editor")["tombstone"] or None)
        self.assertEqual(self.ledger.find("work.project", "main_editor")["verification_state"], "USER_CONFIRMED")
        # Make public without ever sending the private value from the browser
        status, body, _ = self.request("POST", "/facts/update", {
            "namespace": "work.project", "slot": "client", "value": None, "private": False})
        self.assertEqual((status, body["private"]), (200, False))
        self.assertEqual(self.ledger.find("work.project", "client")["value"], "Acme Corp")
        # Delete, and extraction cannot bring it back
        status, body, _ = self.request("POST", "/facts/delete", {"namespace": "work.project", "slot": "client"})
        self.assertEqual((status, body["deleted"]), (200, True))
        status, body, _ = self.request("POST", "/facts", {"namespace": "work.project",
                                                          "facts": [{"slot": "client", "value": "Other"}]})
        self.assertEqual(body["skipped"][0]["reason"], "TombstonedSlot")
        status, body, _ = self.request("GET", "/facts?namespace=work.project")
        self.assertEqual(sorted(f["slot"] for f in body["facts"]), ["main_editor"])

    def test_reviewed_saves_replace_older_values_and_keep_privacy(self):
        self.ledger.record("work.project", "client", "Acme Corp", sensitivity="CONFIDENTIAL",
                           verification_state="USER_CONFIRMED")
        status, body, _ = self.request("POST", "/facts", {"namespace": "work.project", "confirmed": True,
                                                          "facts": [{"slot": "editor", "value": "Zed"},
                                                                    {"slot": "client", "value": "Globex"}]})
        self.assertEqual((status, len(body["saved"]), body["skipped"]), (200, 2, []))
        self.assertEqual(self.ledger.find("work.project", "editor")["value"], "Zed")
        self.assertEqual(self.ledger.find("work.project", "client")["sensitivity"], "CONFIDENTIAL")

    def test_extract_then_save_never_overwrites_confirmed_facts(self):
        status, body, _ = self.request("POST", "/extract", {"text": "- Editor: Vim\n- Framework: Next.js"})
        self.assertEqual(status, 200, body)
        self.assertEqual(body["method"], "heuristic")
        self.assertEqual(self.ledger.stats()["active_facts"], 3)  # extract alone writes nothing
        status, body, _ = self.request("POST", "/facts", {"namespace": "work.project", "facts": body["facts"]})
        self.assertEqual(status, 200, body)
        self.assertEqual([s["slot"] for s in body["saved"]], ["framework"])
        self.assertEqual(body["skipped"][0]["slot"], "editor")      # USER_CONFIRMED stays
        self.assertEqual(self.ledger.find("work.project", "editor")["value"], "VS Code")
        saved = self.ledger.find("work.project", "framework")
        self.assertEqual((saved["value"], saved["verification_state"]), ("Next.js", "EXTRACTED"))

    def test_long_selection_can_be_reviewed_and_saved_without_cutting_the_end(self):
        value = ("The project uses a local SQLite vault shared by every editor and assistant so that the user's "
                 "confirmed decisions remain available across sessions without requiring the user to repeat "
                 "the full architecture every time. Never send private client details to a cloud provider "
                 "without the user's explicit approval.")
        status, proposed, _ = self.request("POST", "/extract", {"text": "- Decision: " + value})
        self.assertEqual(status, 200)
        self.assertGreater(len(proposed["facts"]), 1)
        self.assertTrue(any("split" in warning for warning in proposed["warnings"]))
        status, saved, _ = self.request("POST", "/facts", {
            "namespace": "work.project", "confirmed": True, "facts": proposed["facts"]})
        self.assertEqual((status, len(saved["saved"]), saved["skipped"]), (200, len(proposed["facts"]), []))
        status, listed, _ = self.request("GET", "/facts?namespace=work.project")
        self.assertEqual(status, 200)
        stored = {fact["slot"]: fact["value"] for fact in listed["facts"]}
        self.assertEqual(" ".join(stored[fact["slot"]] for fact in proposed["facts"]), value)

    def test_rejects_bad_requests(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/facts", body=b'{"namespace":"x"}', headers={
            "Host": f"127.0.0.1:{self.port}", "Authorization": "Bearer " + self.token,
            "Content-Type": "text/plain"})  # what a CSRF form/no-cors fetch would send
        self.assertEqual(conn.getresponse().status, 415)
        conn.close()
        status, _, _ = self.request("POST", "/extract", {"text": "x" * 300_000})
        self.assertEqual(status, 413)
        status, _, _ = self.request("POST", "/facts", {"namespace": "Bad Name!", "facts": [{"slot": "a", "value": "b"}]})
        self.assertEqual(status, 200)  # per-fact validation reported, not a crash
        status, body, _ = self.request("GET", "/capsule")
        self.assertEqual((status, body["error"]), (400, "invalid_request"))
        status, body, _ = self.request("GET", "/namespaces")
        self.assertEqual(body["namespaces"], ["personal", "work.project"])


class ClipTests(unittest.TestCase):
    def run_cli(self, db, *args):
        env = dict(os.environ, MEMTY_DB=str(db))
        return subprocess.run([sys.executable, "-m", "memty", *args], env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=30)

    def test_clip_print_and_privacy(self):
        from memty.runtime.daemon import stop
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ledger.sqlite3"
            try:
                self.assertEqual(self.run_cli(db, "remember", "work.project", "editor", "VS Code").returncode, 0)
                self.run_cli(db, "remember", "work.project", "client", "Acme", "--sensitivity", "CONFIDENTIAL")
                out = self.run_cli(db, "clip", "work.project", "--print")
                self.assertEqual(out.returncode, 0, out.stderr)
                self.assertIn("Editor: VS Code", out.stdout.splitlines())
                self.assertNotIn("[Memty", out.stdout)
                xml = self.run_cli(db, "clip", "work.project", "--print", "--format", "xml")
                self.assertIn("<memty_state", xml.stdout)
                self.assertNotIn("Acme", out.stdout)  # clipboard is treated as a cloud destination
                empty = self.run_cli(db, "clip", "nothing.here", "--print")
                self.assertNotEqual(empty.returncode, 0)
                self.run_cli(db, "remember", "work.project", "pw", "hunter2", "--sensitivity", "SECRET")
                secret = self.run_cli(db, "clip", "work.project", "--print")
                self.assertEqual(secret.returncode, 2)
                self.assertNotIn("hunter2", secret.stdout)
            finally:
                stop(db)

    def test_autostart_command_runs_the_bridge(self):
        from memty.runtime import autostart
        args = autostart.command("~/vault.sqlite3", "local", 8765)
        self.assertEqual(args[1:3], ["-m", "memty"])
        self.assertEqual(args[-4:], ["local", "serve", "--port", "8765"])
        self.assertTrue(Path(args[4]).is_absolute())

    def test_extension_installs_from_the_package_and_never_clobbers_other_folders(self):
        from memty.integrations.browser import installer as extension
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "ext"
            result = extension.install(target)
            manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(result["version"], manifest["version"])
            for name in ["background.js", "content.js", "options.html", "options.js", "icons/icon128.png"]:
                self.assertTrue((target / name).exists(), name)
            (target / "stale.js").write_text("old", encoding="utf-8")
            extension.install(target)  # upgrade replaces the folder cleanly
            self.assertFalse((target / "stale.js").exists())
            other = Path(tmp) / "mine"
            other.mkdir()
            (other / "notes.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                extension.install(other)
            self.assertEqual((other / "notes.txt").read_text(encoding="utf-8"), "keep")

    def test_copy_text_uses_platform_tool(self):
        from memty.integrations import clipboard
        with patch("memty.integrations.clipboard.subprocess.run") as run:
            clipboard.copy_text("capsule ✓")
        argv, kwargs = run.call_args[0][0], run.call_args[1]
        if sys.platform == "win32":
            self.assertEqual(argv, ["clip"])
            self.assertEqual(kwargs["input"], "capsule ✓".encode("utf-16"))
        self.assertTrue(kwargs["check"])
        with patch("memty.integrations.clipboard._command", return_value=None):
            with self.assertRaises(RuntimeError):
                clipboard.copy_text("x")


if __name__ == "__main__":
    unittest.main()
