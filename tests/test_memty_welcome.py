"""CLI welcome behavior and backwards-compatible command output."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class WelcomeTests(unittest.TestCase):
    def test_no_arguments_welcomes_without_creating_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "untouched" / "ledger.sqlite3"
            env = dict(os.environ, MEMTY_VAULT_PATH=str(db), MEMTY_DB=str(db))
            result = subprocess.run([sys.executable, "-m", "memty"], env=env,
                                    capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Local memory for AI assistants", result.stdout)
            self.assertIn("user-owned local vault", result.stdout)
            self.assertIn("memty connect", result.stdout)
            self.assertIn("memty --help", result.stdout)
            self.assertFalse(db.parent.exists())

    def test_help_version_and_connect_remain_machine_usable(self):
        def run(*args):
            return subprocess.run([sys.executable, "-m", "memty", *args],
                                  capture_output=True, text=True, timeout=15)
        help_result = run("--help")
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("usage: memty", help_result.stdout)
        version = run("--version")
        self.assertEqual(version.returncode, 0, version.stderr)
        self.assertTrue(version.stdout.startswith("memty "))
        # Isolate client detection from the developer's installed applications.
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, HOME=tmp, USERPROFILE=tmp, PATH=tmp,
                       APPDATA=tmp, LOCALAPPDATA=tmp, XDG_CONFIG_HOME=tmp)
            connect = subprocess.run([sys.executable, "-m", "memty", "connect", "--dry-run", "--json"],
                                     env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(connect.returncode, 0, connect.stderr)
        report = json.loads(connect.stdout)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["server_entry"]["memty"]["args"], ["-m", "memty", "mcp"])
        self.assertFalse(any(item["status"] in {"connected", "updated"}
                             for item in report["clients"].values()))

    def test_connect_output_is_concise_and_actionable(self):
        from io import StringIO
        from contextlib import redirect_stdout
        from memty.cli import _print_connect
        report = {"dry_run": False, "clients": {
            "Claude Code": {"status": "already_connected", "path": "private/path"},
            "Cursor": {"status": "manual_step", "steps": "Confirm in Cursor.", "link": "cursor://install"},
        }, "next_step": "Finish the steps above."}
        output = StringIO()
        with redirect_stdout(output):
            _print_connect(report)
        self.assertIn("Claude Code      Already connected", output.getvalue())
        self.assertIn("Confirm in Cursor.", output.getvalue())
        self.assertIn("cursor://install", output.getvalue())
        self.assertNotIn("private/path", output.getvalue())
        self.assertNotIn('"clients"', output.getvalue())

    def test_connect_manual_setup_keeps_paths_in_json(self):
        from io import StringIO
        from contextlib import redirect_stdout
        from memty.cli import _print_connect
        report = {"dry_run": False, "clients": {
            "Claude Desktop": {"status": "manual_step", "steps": "Add the entry in settings.",
                               "entry": {"memty": {"command": "private/path/python"}}},
            "Claude Code": {"status": "manual_step", "steps": "Install the CLI.",
                            "command": "private/path/python"},
        }, "next_step": "Finish the steps above."}
        output = StringIO()
        with redirect_stdout(output):
            _print_connect(report)
        self.assertNotIn("private/path", output.getvalue())
        self.assertIn("memty connect --dry-run --json", output.getvalue())
        self.assertIn("Add the entry in settings.", output.getvalue())


if __name__ == "__main__":
    unittest.main()
