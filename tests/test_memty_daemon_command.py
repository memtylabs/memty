"""The one-command bridge and MCP server share the same local vault."""
import asyncio
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from memty.runtime.daemon import status, stop
from memty.integrations.browser.bridge import health, stop_background, token_path


class DaemonCommandTests(unittest.TestCase):
    def test_one_command_shares_browser_saves_with_mcp(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "vault.sqlite3"
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            env = dict(os.environ, MEMTY_DB=str(db), MEMTY_VAULT_PATH=str(db), MEMTY_USER="local")
            command = [sys.executable, "-m", "memty", "daemon", "--db", str(db), "--port", str(port)]
            try:
                started = subprocess.run(command, env=env, capture_output=True, text=True, timeout=35)
                self.assertEqual(started.returncode, 0, started.stderr)
                report = json.loads(started.stdout)
                self.assertTrue(report["daemon"]["running"])
                self.assertTrue(report["bridge"]["running"])
                first_pid = report["daemon"]["pid"]
                again = subprocess.run(command, env=env, capture_output=True, text=True, timeout=20)
                self.assertEqual(again.returncode, 0, again.stderr)
                self.assertTrue(json.loads(again.stdout)["bridge"]["already_running"])

                connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                body = json.dumps({"namespace": "project.api", "confirmed": True,
                    "separate_context": True, "facts": [{"slot": "rate_limiter", "value": "Redis token bucket"}]})
                connection.request("POST", "/facts", body=body, headers={
                    "Authorization": "Bearer " + token_path(db).read_text(encoding="utf-8").strip(),
                    "Content-Type": "application/json"})
                response = connection.getresponse()
                result = json.loads(response.read())
                connection.close()
                self.assertEqual(response.status, 200, result)
                self.assertEqual(len(result["saved"]), 1)

                async def mcp_recall():
                    params = StdioServerParameters(command=sys.executable, args=["-m", "memty", "mcp"], env=env)
                    async with stdio_client(params) as (reader, writer):
                        async with ClientSession(reader, writer) as session:
                            await session.initialize()
                            result = await session.call_tool("memty_sync", {"namespace": "project.api", "query": "Redis"})
                            self.assertFalse(result.isError)
                            self.assertIn("Redis token bucket", str(result.content))
                asyncio.run(mcp_recall())
                self.assertEqual(status(db)["pid"], first_pid)
            finally:
                stop_background(db)
                deadline = time.monotonic() + 5
                while health(port) and time.monotonic() < deadline:
                    time.sleep(0.05)
                stop(db)


class StartupTests(unittest.TestCase):
    def test_bridge_binds_without_a_reverse_dns_lookup(self):
        """getfqdn() can stall for 30+ seconds on macOS; the loopback bridge must not call it."""
        from unittest.mock import patch
        from memty.integrations.browser.bridge import BridgeServer
        with patch("socket.getfqdn", side_effect=AssertionError("reverse DNS lookup on bind")):
            server = BridgeServer(object(), "t" * 43, port=0)
        try:
            self.assertEqual(server.server_name, "127.0.0.1")
            self.assertEqual(server.server_address[0], "127.0.0.1")
        finally:
            server.server_close()

    def test_background_processes_never_hold_the_callers_folder(self):
        """Windows locks a process's working directory: memtyd and the bridge run from the drive root."""
        from unittest.mock import MagicMock, patch
        from memty.runtime import daemon
        from memty.integrations.browser import bridge
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "vault" / "ledger.sqlite3"
            db.parent.mkdir()
            child = MagicMock()
            child.poll.return_value = 1
            child.returncode = 1
            with patch.object(daemon.subprocess, "Popen", return_value=child) as popen, \
                    patch.object(daemon, "_ping", return_value=None), \
                    patch.object(daemon.time, "monotonic", side_effect=[0.0, 0.0, 0.0, 99.0, 99.0]):
                with self.assertRaises(RuntimeError):
                    daemon.ensure_daemon(db)
            self.assertEqual(Path(popen.call_args.kwargs["cwd"]), Path(db.resolve().anchor))
            with patch.object(bridge.subprocess, "Popen", return_value=child) as popen, \
                    patch.object(bridge, "health", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "exited with code 1"):
                    bridge.start_background(db, "local", port=1)
            self.assertEqual(Path(popen.call_args.kwargs["cwd"]), Path(db.resolve().anchor))


class SaveOrderTests(unittest.TestCase):
    def test_facts_saved_in_the_same_millisecond_keep_their_order(self):
        """A fast machine saves a whole browser Save within one millisecond; order must survive."""
        from unittest.mock import patch
        from memty.vault import ledger as ledger_module
        from memty.vault.ledger import MemtyLedger
        from memty.integrations.browser.bridge import latest_batch
        with tempfile.TemporaryDirectory() as tmp, MemtyLedger(Path(tmp) / "v.sqlite3") as ledger:
            ledger.record("work", "zebra", "first older fact")
            with patch.object(ledger_module, "_utc_now_ms", return_value=1_800_000_000_000):
                for slot in ["zulu", "alpha", "mike"]:  # deliberately not alphabetical
                    ledger.record("work", slot, slot.upper(), source_id="save_" + "a" * 16)
            facts = ledger.list(namespace="work")
            stamps = sorted(f["updated_at"] for f in facts)
            self.assertEqual(len(set(stamps)), len(stamps))  # strictly increasing
            self.assertEqual([f["slot"] for f in latest_batch(facts)], ["zulu", "alpha", "mike"])


if __name__ == "__main__":
    unittest.main()
