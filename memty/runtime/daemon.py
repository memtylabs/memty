"""Single local daemon per ledger, with authenticated loopback IPC."""
from __future__ import annotations

import argparse
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import socketserver
import subprocess
import sys
import tempfile
import time

from ..context.privacy import LocalRoutingRequired
from ..vault.paths import default_user_id, default_vault_path
from ..vault.ledger import LockedSlot, MemtyLedger, TombstonedSlot

METHODS = frozenset({"record", "record_context", "find", "forget", "context", "context_selected", "stats", "list", "set_summary", "summary",
                     "summarize_namespace", "set_constraint", "list_constraints", "delete_constraint",
                     "archive_raw", "drill_down", "history", "propose", "proposals",
                     "resolve_proposal", "log_receipt", "receipts", "report"})
MAX_MESSAGE = 16 * 1024 * 1024
_children = []


def _paths(db):
    path = Path(db).expanduser().resolve()
    return path, path.with_name(path.name + ".daemon.json"), path.with_name(path.name + ".daemon.lock")


def _lock(file):
    if os.name == "nt":
        import msvcrt
        file.seek(0)
        if not file.read(1):
            file.write(b"0")
            file.flush()
        file.seek(0)
        msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _exchange(endpoint, request, timeout=30):
    payload = json.dumps({**request, "token": endpoint["token"]}, ensure_ascii=False).encode("utf-8") + b"\n"
    if len(payload) > MAX_MESSAGE:
        raise ValueError("daemon request exceeds size limit")
    with socket.create_connection(("127.0.0.1", int(endpoint["port"])), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(payload)
        with sock.makefile("rb") as stream:
            data = stream.readline(MAX_MESSAGE + 1)
    if not data or len(data) > MAX_MESSAGE:
        raise RuntimeError("invalid daemon response")
    result = json.loads(data)
    if not result.get("ok"):
        error = result.get("error", {})
        kind = error.get("type")
        if kind == "LocalRoutingRequired":
            raise LocalRoutingRequired(error["provider"], namespace=error.get("namespace"),
                                       slot=error.get("slot"), suggested_provider=error["suggested_provider"])
        cls = {"ValueError": ValueError, "LockedSlot": LockedSlot,
               "TombstonedSlot": TombstonedSlot}.get(kind, RuntimeError)
        raise cls(error.get("message", "daemon request failed"))
    return result.get("result")


def _endpoint(path):
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict) or not isinstance(obj.get("token"), str):
            return None
        return obj
    except (OSError, ValueError):
        return None


def _ping(path):
    endpoint = _endpoint(path)
    if endpoint:
        try:
            _exchange(endpoint, {"method": "ping"}, timeout=1)
            return endpoint
        except (OSError, ValueError, KeyError, RuntimeError):
            pass
    return None


def ensure_daemon(db):
    path, endpoint_path, _ = _paths(db)
    endpoint = _ping(endpoint_path)
    if endpoint:
        return endpoint
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    deadline = time.monotonic() + 15
    next_start = 0.0
    while time.monotonic() < deadline:
        endpoint = _ping(endpoint_path)
        if endpoint:
            return endpoint
        if time.monotonic() >= next_start:
            _children[:] = [child for child in _children if child.poll() is None]
            _children.append(subprocess.Popen(
                [sys.executable, "-m", "memty.runtime.daemon", "serve", "--db", str(path)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=flags, start_new_session=(os.name != "nt"), close_fds=True))
            next_start = time.monotonic() + 1.0
        time.sleep(0.05)
    raise RuntimeError(f"Could not start memtyd for {path}; run memtyd serve --db <path> to diagnose")


class DaemonLedger:
    """Ledger facade that sends operations to the shared process."""
    def __init__(self, db=None, user_id=None, *, trusted_providers=()):
        self.path = _paths(db or default_vault_path())[0]
        self.user_id = user_id or default_user_id()
        self.trusted_providers = list(trusted_providers)

    def __getattr__(self, name):
        if name not in METHODS:
            raise AttributeError(name)
        def invoke(*args, **kwargs):
            endpoint = ensure_daemon(self.path)
            try:
                return _exchange(endpoint, {"method": name, "user": self.user_id,
                                            "trusted": self.trusted_providers,
                                            "args": args, "kwargs": kwargs})
            except ValueError as error:
                if str(error) == "unknown daemon method":
                    # memtyd outlives `pip install --upgrade`; an old process lacks new methods.
                    raise RuntimeError("The running memtyd is older than this memty. "
                                       "Run `memtyd stop` and try again.") from error
                raise
        return invoke

    def close(self):
        pass


class _Server(socketserver.TCPServer):
    allow_reuse_address = False
    timeout = 0.5

    def __init__(self, db, token):
        self.db = db
        self.token = token
        self.running = True
        self.ledgers = {}
        super().__init__(("127.0.0.1", 0), _Handler)

    def dispatch(self, request):
        if not isinstance(request, dict) or not hmac.compare_digest(str(request.get("token", "")), self.token):
            raise PermissionError("invalid daemon credentials")
        method = request.get("method")
        if method == "ping":
            return {"pid": os.getpid(), "db": str(self.db)}
        if method == "stop":
            self.running = False
            return {"stopping": True}
        if method not in METHODS:
            raise ValueError("unknown daemon method")
        user = request.get("user", "local")
        trusted = request.get("trusted", [])
        if not isinstance(user, str) or not isinstance(trusted, list) or not all(isinstance(x, str) for x in trusted):
            raise ValueError("invalid user or trusted providers")
        key = (user, tuple(sorted(trusted)))
        if key not in self.ledgers:
            self.ledgers[key] = MemtyLedger(self.db, user, trusted_providers=trusted)
        args, kwargs = request.get("args", []), request.get("kwargs", {})
        if not isinstance(args, list) or not isinstance(kwargs, dict):
            raise ValueError("invalid method arguments")
        return getattr(self.ledgers[key], method)(*args, **kwargs)


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        self.request.settimeout(10)
        try:
            data = self.rfile.readline(MAX_MESSAGE + 1)
            if not data or len(data) > MAX_MESSAGE:
                raise ValueError("invalid request size")
            result = self.server.dispatch(json.loads(data))
            response = {"ok": True, "result": result}
        except Exception as error:
            details = {"type": type(error).__name__, "message": str(error)}
            if isinstance(error, LocalRoutingRequired):
                details.update(error.as_dict())
            response = {"ok": False, "error": details}
        try:
            self.wfile.write(json.dumps(response, ensure_ascii=False, default=str).encode("utf-8") + b"\n")
        except OSError:
            pass


def serve(db):
    path, endpoint_path, lock_path = _paths(db)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as lock:
        try:
            _lock(lock)
        except OSError:
            return False
        token = secrets.token_urlsafe(32)
        with _Server(path, token) as server:
            # Fail before advertising readiness if the ledger cannot be opened.
            server.ledgers[("local", ())] = MemtyLedger(path, "local")
            fd, temp = tempfile.mkstemp(prefix=".memtyd-", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump({"port": server.server_address[1], "token": token, "pid": os.getpid()}, stream)
                os.replace(temp, endpoint_path)
                while server.running:
                    server.handle_request()
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
                if endpoint_path.exists():
                    endpoint_path.unlink()
                for ledger in server.ledgers.values():
                    ledger.close()
    return True


def status(db):
    path, endpoint_path, _ = _paths(db)
    endpoint = _ping(endpoint_path)
    return {"running": bool(endpoint), "db": str(path), "pid": endpoint.get("pid") if endpoint else None}


def stop(db):
    _, endpoint_path, lock_path = _paths(db)
    endpoint = _ping(endpoint_path)
    if not endpoint:
        return {"stopped": False, "reason": "not_running"}
    _exchange(endpoint, {"method": "stop"})
    # An unresponsive endpoint does not imply that SQLite handles have been
    # closed. Wait until the daemon releases its instance lock as well.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            with open(lock_path, "a+b") as lock:
                _lock(lock)
            return {"stopped": True}
        except OSError:
            time.sleep(0.05)
    return {"stopped": False}


def main():
    parser = argparse.ArgumentParser(prog="memtyd")
    parser.add_argument("action", nargs="?", default="bridge", choices=["bridge", "start", "serve", "status", "stop"])
    parser.add_argument("--db", default=str(default_vault_path()))
    parser.add_argument("--user", default=default_user_id())
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.action == "bridge":
        from ..integrations.browser.bridge import start_background
        ensure_daemon(args.db)
        bridge = start_background(args.db, args.user, port=args.port)
        print(json.dumps({"daemon": status(args.db), "bridge": bridge,
                          "url": f"http://127.0.0.1:{args.port}"}, indent=2))
    elif args.action == "serve":
        if not serve(args.db):
            raise SystemExit("memtyd is already running for this database")
    elif args.action == "start":
        ensure_daemon(args.db)
        print(json.dumps(status(args.db), indent=2))
    elif args.action == "status":
        print(json.dumps(status(args.db), indent=2))
    else:
        print(json.dumps(stop(args.db), indent=2))


if __name__ == "__main__":
    main()
