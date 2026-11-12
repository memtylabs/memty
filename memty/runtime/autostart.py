"""Start the Memty web bridge automatically when the user logs in.

Per-user only and reversible (``memty serve --no-autostart``); never needs admin:

* Windows: ``HKCU\\...\\CurrentVersion\\Run`` value, launched with ``pythonw`` (no console).
* macOS: ``~/Library/LaunchAgents/dev.memty.bridge.plist``.
* Linux: ``~/.config/autostart/memty-bridge.desktop`` (XDG autostart).
"""
from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys
from xml.sax.saxutils import escape

NAME = "MemtyBridge"
LABEL = "dev.memty.bridge"


def _python() -> str:
    exe = Path(sys.executable)
    if os.name == "nt":  # pythonw runs without opening a console window
        windowless = exe.with_name(exe.name.lower().replace("python.exe", "pythonw.exe"))
        if windowless.exists():
            return str(windowless)
    return str(exe)


def command(db: str | Path, user: str, port: int) -> list[str]:
    return [_python(), "-m", "memty", "--db", str(Path(db).expanduser().resolve()), "--user", user,
            "serve", "--port", str(port)]


def _mac_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _linux_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "autostart" / "memty-bridge.desktop"


def install(db: str | Path, user: str, port: int) -> dict:
    args = command(db, user, port)
    if os.name == "nt":
        import winreg
        line = subprocess.list2cmdline(args)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, NAME, 0, winreg.REG_SZ, line)
        return {"autostart": "installed", "where": rf"HKCU\...\Run\{NAME}"}
    if sys.platform == "darwin":
        path = _mac_path()
        items = "".join(f"<string>{escape(arg)}</string>" for arg in args)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            f'<plist version="1.0"><dict><key>Label</key><string>{LABEL}</string>'
            f"<key>ProgramArguments</key><array>{items}</array>"
            "<key>RunAtLoad</key><true/></dict></plist>\n", encoding="utf-8")
        return {"autostart": "installed", "where": str(path)}
    path = _linux_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[Desktop Entry]\nType=Application\nName=Memty bridge\n"
                    f"Exec={shlex.join(args)}\nX-GNOME-Autostart-enabled=true\nNoDisplay=true\n",
                    encoding="utf-8")
    return {"autostart": "installed", "where": str(path)}


def uninstall() -> dict:
    if os.name == "nt":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                                winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, NAME)
        except FileNotFoundError:
            return {"autostart": "not_installed"}
        return {"autostart": "removed"}
    path = _mac_path() if sys.platform == "darwin" else _linux_path()
    try:
        path.unlink()
    except FileNotFoundError:
        return {"autostart": "not_installed"}
    return {"autostart": "removed", "where": str(path)}
