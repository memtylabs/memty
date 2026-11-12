"""Week 4: cross-client setup and bounded MCP source access."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from memty.integrations.mcp.connect import connect_clients
from memty.vault.ledger import MemtyLedger


class ClientSetupTests(unittest.TestCase):
    def test_codex_and_vscode_use_official_installers_without_direct_config_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = {"Codex CLI": root / "config.toml", "VS Code": root / "mcp.json"}
            calls = []

            def run(argv, **kwargs):
                calls.append(argv)
                if argv[:3] == ["codex", "mcp", "get"]:
                    return subprocess.CompletedProcess(argv, 1, "", "not found")
                return subprocess.CompletedProcess(argv, 0, "", "")

            with patch("memty.integrations.mcp.connect.subprocess.run", side_effect=run), \
                 patch("pathlib.Path.write_text", side_effect=AssertionError("direct config write")):
                result = connect_clients(paths, codex_cli="codex", code_cli="code",
                                         claude_cli=None, executable="/python")["clients"]
            self.assertEqual(result["Codex CLI"]["status"], "connected")
            self.assertEqual(result["VS Code"]["status"], "install_prompt_opened")
            self.assertIn(["codex", "mcp", "add", "memty", "--", "/python", "-m", "memty", "mcp"], calls)
            vscode = next(argv for argv in calls if argv[:2] == ["code", "--add-mcp"])
            self.assertEqual(json.loads(vscode[2]), {"name": "memty", "type": "stdio",
                                                     "command": "/python", "args": ["-m", "memty", "mcp"]})
            self.assertFalse(any(path.exists() for path in paths.values()))


class MCPDrillTests(unittest.TestCase):
    def test_two_mcp_clients_share_one_daemon_and_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ledger.sqlite3"

            async def connect_as(provider):
                env = dict(os.environ, MEMTY_DB=str(db), MEMTY_PROVIDER=provider)
                return StdioServerParameters(command=sys.executable, args=["-m", "memty", "mcp"], env=env)

            async def exercise():
                async with stdio_client(await connect_as("codex")) as (reader_a, writer_a):
                    async with ClientSession(reader_a, writer_a) as first:
                        await first.initialize()
                        saved = await first.call_tool("memty_sync", {"namespace": "project.api",
                                                                      "set_slots": {"editor": "VS Code"}})
                        self.assertFalse(saved.isError)
                        from memty.runtime.daemon import status
                        pid = status(db)["pid"]
                        async with stdio_client(await connect_as("cursor")) as (reader_b, writer_b):
                            async with ClientSession(reader_b, writer_b) as second:
                                await second.initialize()
                                recalled = await second.call_tool("memty_sync", {"namespace": "project.api"})
                                self.assertFalse(recalled.isError)
                                self.assertIn("VS Code", str(recalled.content))
                                self.assertEqual(status(db)["pid"], pid)
            try:
                asyncio.run(exercise())
            finally:
                from memty.runtime.daemon import stop
                stop(db)

    def test_local_drill_is_bounded_and_tombstones_are_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "ledger.sqlite3"
            with MemtyLedger(db) as ledger:
                ledger.record("project.api", "decision", "Token bucket", source_raw="A" * 4500)
            env = dict(os.environ, MEMTY_DB=str(db), MEMTY_PROVIDER="local")

            async def exercise():
                params = StdioServerParameters(command=sys.executable, args=["-m", "memty", "mcp"], env=env)
                async with stdio_client(params) as (reader, writer):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        result = await session.call_tool("memty_drill", {"namespace": "project.api", "slot": "decision"})
                        self.assertFalse(result.isError)
                        body = json.loads(result.content[0].text)
                        self.assertEqual(len(body["source"]), 4000)
                        self.assertTrue(body["truncated"])
                        result = await session.call_tool("memty_sync", {"namespace": "project.api",
                                                                          "action": "forget", "slot": "decision"})
                        self.assertFalse(result.isError)
                        result = await session.call_tool("memty_drill", {"namespace": "project.api", "slot": "decision"})
                        self.assertIn("not_found", str(result.content))
            try:
                asyncio.run(exercise())
            finally:
                from memty.runtime.daemon import stop
                stop(db)


if __name__ == "__main__":
    unittest.main()
