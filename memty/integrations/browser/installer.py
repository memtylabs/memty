"""Install the bundled Memty Bridge browser extension into a stable folder.

The extension ships inside the ``memty`` wheel. Browsers load an unpacked
extension from a folder path, and the site-packages path changes between
Python versions and virtual environments, so ``memty extension`` copies it to
``~/.memty/browser-extension``. After ``pip install -U memty``, run it again
and click reload in ``chrome://extensions``.
"""
from __future__ import annotations

from importlib import resources
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

DEFAULT_DIR = Path.home() / ".memty" / "browser-extension"
EXTENSION_NAME = "Memty Bridge"


def bundled() -> Path:
    return Path(str(resources.files("memty.integrations.browser") / "extension"))


def _is_ours(folder: Path) -> bool:
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return manifest.get("name") == EXTENSION_NAME


def install(target: str | Path | None = None) -> dict:
    """Copy the bundled extension to ``target``; only ever replaces a Memty Bridge folder."""
    source = bundled()
    if not (source / "manifest.json").exists():
        raise RuntimeError("The browser extension is missing from this Memty install; reinstall memty.")
    target = Path(target).expanduser() if target else DEFAULT_DIR
    if target.exists() and any(target.iterdir()) and not _is_ours(target):
        raise RuntimeError(f"{target} is not empty and is not a Memty Bridge folder; choose another --dir.")
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    # Update in place (no folder rename): on Windows, antivirus briefly locks
    # freshly written files, and the browser may hold the folder open.
    shutil.copytree(source, target, ignore=ignore, dirs_exist_ok=True)
    wanted = {path.relative_to(source) for path in source.rglob("*")
              if "__pycache__" not in path.parts and path.suffix != ".pyc"}
    for path in sorted(target.rglob("*"), reverse=True):  # files from an older version
        if path.relative_to(target) not in wanted:
            path.unlink() if path.is_file() else shutil.rmtree(path, ignore_errors=True)
    version = json.loads((target / "manifest.json").read_text(encoding="utf-8")).get("version")
    return {"path": str(target), "version": version}


def open_folder(path: str | Path) -> None:
    path = str(path)
    if os.name == "nt":
        os.startfile(path)  # noqa: S606 - opens Explorer on a folder we just wrote
    elif sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)
