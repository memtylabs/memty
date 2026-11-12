"""Integration coverage for concurrent storage and the MCP bridge."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from memty.integrations.mcp.connect import connect_clients
from memty.vault.ledger import MemtyLedger
from memty.vault.tokens import estimate_tokens


class WeekTwoTests(unittest.TestCase):
    def test_parallel_connections_and_pragmas(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ledger.sqlite3"
            with MemtyLedger(path) as ledger:
                with ledger._connect() as db:
                    self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "wal")
                    self.assertEqual(db.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
                    self.assertEqual(db.execute("PRAGMA synchronous").fetchone()[0], 1)
            def worker(i):
                with MemtyLedger(path) as ledger:
                    for j in range(15):
                        ledger.record("parallel", f"slot_{i}_{j}", "value")
                        ledger.context("value", provider="local", namespace="parallel")
            with ThreadPoolExecutor(max_workers=5) as pool:
                list(pool.map(worker, range(5)))
            with MemtyLedger(path) as ledger:
                self.assertEqual(ledger.stats()["active_facts"], 75)

    def test_independent_processes_share_ledger(self):
        import subprocess, sys
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "ledger.sqlite3")
            with MemtyLedger(path):
                pass
            code = """import sys
from memty.vault.ledger import MemtyLedger
with MemtyLedger(sys.argv[1]) as ledger:
    for i in range(20):
        ledger.record('processes', 'p' + sys.argv[2] + '_' + str(i), 'value')
        ledger.context('value', provider='local', namespace='processes')
"""
            processes = [subprocess.Popen([sys.executable, "-c", code, path, str(i)],
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                         for i in range(4)]
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                self.assertEqual(process.returncode, 0, (stdout, stderr))
            with MemtyLedger(path) as ledger:
                self.assertEqual(ledger.stats()["active_facts"], 80)

    def test_daemon_shared_by_cli_clients_and_restart(self):
        import subprocess, sys
        from memty.runtime.daemon import status, stop
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "daemon.sqlite3")
            try:
                processes = [subprocess.Popen(
                    [sys.executable, "-m", "memty", "--db", path, "remember", "shared",
                     "slot_" + str(i), "value"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    for i in range(4)]
                for process in processes:
                    out, err = process.communicate(timeout=35)
                    self.assertEqual(process.returncode, 0, (out, err))
                first = status(path)
                self.assertTrue(first["running"])
                proc = subprocess.run([sys.executable, "-m", "memty", "--db", path, "stats"],
                                      capture_output=True, text=True, timeout=15)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(json.loads(proc.stdout)["active_facts"], 4)
                self.assertEqual(status(path)["pid"], first["pid"])
                self.assertTrue(stop(path)["stopped"])
                self.assertFalse(status(path)["running"])
                proc = subprocess.run([sys.executable, "-m", "memty", "--db", path, "stats"],
                                      capture_output=True, text=True, timeout=20)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(json.loads(proc.stdout)["active_facts"], 4)
                self.assertTrue(status(path)["running"])
            finally:
                stop(path)

    def test_daemon_rejects_unauthenticated_requests(self):
        from memty.runtime.daemon import _exchange, ensure_daemon, stop
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "daemon.sqlite3")
            try:
                endpoint = ensure_daemon(path)
                with self.assertRaisesRegex(RuntimeError, "credentials"):
                    _exchange({**endpoint, "token": "wrong"}, {"method": "stats"})
            finally:
                stop(path)

    def test_daemon_saves_and_recalls_one_numbered_context(self):
        from memty.runtime.daemon import DaemonLedger, stop
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "daemon.sqlite3")
            ledger = DaemonLedger(path)
            try:
                saved = ledger.record_context("work.project", [
                    {"slot": "editor", "value": "VS Code"},
                    {"slot": "language", "value": "Python"},
                ])
                ids = [ledger.find("work.project", fact["slot"])["id"] for fact in saved["saved"]]
                capsule = ledger.context_selected("work.project", ids, provider="openai", token_budget=2000)
                self.assertEqual(capsule["text"].splitlines(), ["[Memty context]", "1. Editor: VS Code",
                                                                  "2. Language: Python", "[/Memty]"])
            finally:
                stop(path)

    def _client_home(self, tmp):
        home = Path(tmp)
        paths = {
            "Claude Desktop": home / "appdata" / "Claude" / "claude_desktop_config.json",
            "Claude Code": home / ".claude.json",
            "Cursor": home / ".cursor" / "mcp.json",
            "Windsurf": home / ".codeium" / "windsurf" / "mcp_config.json",
        }
        return home, paths

    @staticmethod
    def _snapshot(root):
        return {p: (p.read_bytes() if p.is_file() else None, p.stat().st_mtime_ns)
                for p in Path(root).rglob("*")}

    def test_connect_never_writes_any_client_file(self):
        from unittest.mock import patch
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            _, paths = self._client_home(tmp)
            # Valid, invalid, BOM, and wrong-shaped files: none may be touched.
            content = {"Claude Desktop": b'{"mcpServers": {"other": {"command": "node"}}}',
                       "Claude Code": b'{"secret": "do-not-print"}',
                       "Cursor": b'\xef\xbb\xbf{"mcpServers": {}}',
                       "Windsurf": b"{invalid"}
            for name, data in content.items():
                paths[name].parent.mkdir(parents=True, exist_ok=True)
                paths[name].write_bytes(data)
            before = self._snapshot(tmp)
            opened = []
            with patch("memty.integrations.mcp.connect.subprocess.run",
                       side_effect=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", "")), \
                 patch("memty.integrations.mcp.connect._open_url", side_effect=opened.append), \
                 patch("os.replace", side_effect=AssertionError("replace config")), \
                 patch("pathlib.Path.write_text", side_effect=AssertionError("write config")), \
                 patch("pathlib.Path.write_bytes", side_effect=AssertionError("write config")):
                report = connect_clients(paths, claude_cli="claude", executable="/py")
            self.assertEqual(before, self._snapshot(tmp))
            self.assertNotIn("do-not-print", json.dumps(report))
            result = report["clients"]
            self.assertEqual(result["Claude Code"]["status"], "connected")
            self.assertEqual(result["Cursor"]["status"], "install_prompt_opened")
            self.assertEqual(opened, [result["Cursor"]["link"]])
            for name in ("Claude Desktop", "Windsurf"):
                self.assertEqual(result[name]["status"], "manual_step")
                self.assertEqual(result[name]["entry"]["mcpServers"]["memty"],
                                 {"command": "/py", "args": ["-m", "memty", "mcp"]})
            self.assertIn("Memty never writes", report["note"])

    def test_cursor_link_matches_documented_format(self):
        import base64
        from urllib.parse import parse_qs, urlsplit
        from memty.integrations.mcp.connect import cursor_install_link
        link = cursor_install_link({"command": "C:\\Py 3\\python.exe", "args": ["-m", "memty", "mcp"]})
        parts = urlsplit(link)
        self.assertEqual((parts.scheme, parts.netloc, parts.path),
                         ("cursor", "anysphere.cursor-deeplink", "/mcp/install"))
        query = parse_qs(parts.query)
        self.assertEqual(query["name"], ["memty"])
        self.assertEqual(json.loads(base64.b64decode(query["config"][0])),
                         {"command": "C:\\Py 3\\python.exe", "args": ["-m", "memty", "mcp"]})

    def test_connect_uses_claude_cli_and_reports_existing_entries(self):
        from unittest.mock import patch
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            _, paths = self._client_home(tmp)
            paths["Claude Code"].write_text(json.dumps({"mcpServers": {"memty": {
                "type": "stdio", "command": "/old", "args": ["-m", "memty", "mcp"], "env": {}}}}),
                encoding="utf-8")
            paths["Cursor"].parent.mkdir()
            paths["Cursor"].write_text(json.dumps({"mcpServers": {"memty": {
                "command": "/py", "args": ["-m", "memty", "mcp"]}}}), encoding="utf-8")
            calls = []

            def fake_run(cmd, **kwargs):
                calls.append(cmd)
                return subprocess.CompletedProcess(cmd, 0, "", "")
            with patch("memty.integrations.mcp.connect.subprocess.run", side_effect=fake_run), \
                 patch("memty.integrations.mcp.connect._open_url", side_effect=AssertionError("opened")):
                result = connect_clients(paths, claude_cli="claude", executable="/py",
                                         clients=["claude code", "Cursor"])["clients"]
            self.assertEqual(set(result), {"Claude Code", "Cursor"})
            self.assertEqual(result["Claude Code"]["status"], "updated")
            self.assertEqual(result["Cursor"]["status"], "already_connected")
            self.assertEqual(calls, [
                ["claude", "mcp", "remove", "--scope", "user", "memty"],
                ["claude", "mcp", "add", "--scope", "user", "memty", "--", "/py", "-m", "memty", "mcp"],
            ])

            calls.clear()
            with patch("memty.integrations.mcp.connect.subprocess.run", side_effect=fake_run):
                same = connect_clients(paths, claude_cli="claude", executable="/old",
                                       clients=["Claude Code"])["clients"]
                plan = connect_clients(paths, claude_cli="claude", executable="/new",
                                       clients=["Claude Code"], dry_run=True)
            self.assertEqual(same["Claude Code"]["status"], "already_connected")
            self.assertEqual(plan["clients"]["Claude Code"]["status"], "would_update")
            self.assertEqual(calls, [])

            failing = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom")
            with patch("memty.integrations.mcp.connect.subprocess.run", side_effect=failing):
                broken = connect_clients(paths, claude_cli="claude", executable="/new",
                                         clients=["Claude Code"])["clients"]["Claude Code"]
            self.assertEqual((broken["status"], broken["error"]), ("error", "boom"))
            self.assertIn("claude mcp add", broken["command"])

    def test_connect_cli_end_to_end_leaves_home_unchanged(self):
        import os, subprocess, sys
        with tempfile.TemporaryDirectory() as tmp:
            home, paths = self._client_home(tmp)
            for name in ("Cursor", "Windsurf"):
                paths[name].parent.mkdir(parents=True)
                paths[name].write_text('{"mcpServers": {"keep": {"command": "x"}}}', encoding="utf-8")
            empty_bin = home / "bin"
            empty_bin.mkdir()  # no `claude` on PATH, so nothing outside tmp can run
            env = dict(os.environ, HOME=tmp, USERPROFILE=tmp, PATH=str(empty_bin),
                       APPDATA=str(home / "appdata"), LOCALAPPDATA=str(home / "local"),
                       XDG_CONFIG_HOME=str(home / "appdata"))
            before = self._snapshot(tmp)

            def run(*args):
                return subprocess.run([sys.executable, "-m", "memty", "connect", *args], env=env,
                                      capture_output=True, text=True, timeout=15)
            dry = run("--dry-run")
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertEqual(json.loads(dry.stdout)["clients"]["Cursor"]["status"],
                             "would_open_install_prompt")
            done = run("--no-open")
            self.assertEqual(done.returncode, 0, done.stderr)
            report = json.loads(done.stdout)["clients"]
            self.assertEqual(report["Cursor"]["status"], "manual_step")
            self.assertTrue(report["Cursor"]["link"].startswith("cursor://"))
            self.assertEqual(report["Windsurf"]["status"], "manual_step")
            self.assertEqual(report["Claude Code"]["status"], "not_detected")
            self.assertEqual(report["Claude Desktop"]["status"], "not_detected")
            self.assertEqual(before, self._snapshot(tmp))

    def test_real_mcp_stdio_session(self):
        import os, sys
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, MEMTY_DB=str(Path(tmp) / "ledger.sqlite3"))
            async def exercise():
                params = StdioServerParameters(command=sys.executable, args=["-m", "memty", "mcp"], env=env)
                async with stdio_client(params) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        self.assertEqual([tool.name for tool in tools.tools],
                                         ["memty_sync", "memty_propose", "memty_drill"])
                        for tool in tools.tools:  # the MCP Context is injected, never a tool argument
                            self.assertNotIn("ctx", tool.inputSchema.get("properties", {}))
                        templates = await session.list_resource_templates()
                        self.assertEqual(str(templates.resourceTemplates[0].uriTemplate), "memty://capsule/{namespace}")
                        result = await session.call_tool("memty_sync", {"namespace": "one", "action": "remember", "slot": "color", "value": "blue"})
                        self.assertFalse(result.isError)
                        updated = await session.call_tool("memty_sync", {"namespace": "one", "set_slots": {
                            "editor": "VS Code", "language": "Python"}})
                        self.assertFalse(updated.isError)
                        self.assertIn("VS Code", str(updated.content))
                        denied = await session.call_tool("memty_drill", {"namespace": "one", "slot": "editor"})
                        self.assertIn("local_only", str(denied.content))
                        import subprocess
                        from memty.runtime.daemon import status
                        first_pid = status(env["MEMTY_DB"])["pid"]
                        cli = subprocess.run([sys.executable, "-m", "memty", "stats"],
                                             env=env, capture_output=True, text=True, timeout=15)
                        self.assertEqual(cli.returncode, 0, cli.stderr)
                        self.assertEqual(json.loads(cli.stdout)["active_facts"], 3)
                        self.assertEqual(status(env["MEMTY_DB"])["pid"], first_pid)
                        await session.call_tool("memty_sync", {"namespace": "two", "action": "remember", "slot": "color", "value": "red"})
                        resource = await session.read_resource("memty://capsule/one")
                        capsule = json.loads(resource.contents[0].text)
                        self.assertIn("blue", capsule["text"])
                        self.assertNotIn("red", capsule["text"])
                        self.assertLessEqual(estimate_tokens(capsule["text"]), 120)
                        resource = await session.read_resource("memty://capsule/empty")
                        self.assertNotIn("blue", resource.contents[0].text)
            try:
                asyncio.run(exercise())
            finally:
                from memty.runtime.daemon import stop
                stop(env["MEMTY_DB"])

if __name__ == "__main__":
    unittest.main()
