"""Copy text to the system clipboard using only built-in OS tools."""
from __future__ import annotations

import shutil
import subprocess
import sys


def _command() -> tuple[list[str], str] | None:
    """Return (argv, encoding) for the platform's clipboard writer."""
    if sys.platform == "win32":
        # clip.exe reads UTF-16 correctly when the input starts with a BOM.
        return ["clip"], "utf-16"
    if sys.platform == "darwin":
        return ["pbcopy"], "utf-8"
    for argv in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        if shutil.which(argv[0]):
            return argv, "utf-8"
    return None


def copy_text(text: str) -> None:
    command = _command()
    if command is None:
        raise RuntimeError("No clipboard tool found (install wl-clipboard, xclip, or xsel), "
                           "or use --print")
    argv, encoding = command
    # No console flash when launched from a hotkey via pythonw.
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    subprocess.run(argv, input=text.encode(encoding), check=True, timeout=10,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, creationflags=flags)
