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


if __name__ == "__main__":
    unittest.main()
