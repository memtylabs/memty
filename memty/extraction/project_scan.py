"""Zero-LLM project bootstrap: turn a code folder's manifests into baseline facts.

``memty scan`` reads a handful of well-known files at the project root and
derives 10-15 short, deterministic facts (package name, runtime, frameworks,
scripts, base image, environment key names, ...).  No model is called and no
network request is made.

Secrets never leave the file: from ``.env.example``-style files only the key
names are kept, and the Dockerfile parser ignores ``ENV``, ``ARG``, ``CMD`` and
``RUN`` lines entirely.  Real ``.env`` files are never opened.

Facts are saved as ``EXTRACTED`` with a ``scan:<file>`` source, so the ledger's
normal rules apply: a scan can never overwrite a ``USER_CONFIRMED`` slot or
recreate a slot the user deleted.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from ..vault.tokens import estimate_tokens, truncate_tokens

FACT_TOKENS = 40
MAX_FILE_BYTES = 512 * 1024
ENV_EXAMPLES = (".env.example", ".env.sample", ".env.template", ".env.dist")
SCAN_SOURCE_PREFIX = "scan:"

_ENV_KEY = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]{0,127})\s*=")
_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_SLUG = re.compile(r"[^a-z0-9_-]+")

_NODE_FRAMEWORKS = (
    ("next", "Next.js"), ("nuxt", "Nuxt"), ("@remix-run/react", "Remix"), ("astro", "Astro"),
    ("@sveltejs/kit", "SvelteKit"), ("react", "React"), ("vue", "Vue"), ("svelte", "Svelte"),
    ("@angular/core", "Angular"), ("solid-js", "Solid"), ("express", "Express"),
    ("fastify", "Fastify"), ("@nestjs/core", "NestJS"), ("hono", "Hono"), ("koa", "Koa"),
    ("electron", "Electron"), ("react-native", "React Native"), ("vite", "Vite"),
    ("tailwindcss", "Tailwind CSS"), ("prisma", "Prisma"), ("drizzle-orm", "Drizzle"),
)
_NODE_TESTS = (("vitest", "Vitest"), ("jest", "Jest"), ("mocha", "Mocha"),
               ("@playwright/test", "Playwright"), ("cypress", "Cypress"))
_PY_FRAMEWORKS = (
    ("django", "Django"), ("fastapi", "FastAPI"), ("flask", "Flask"), ("starlette", "Starlette"),
    ("streamlit", "Streamlit"), ("pydantic", "Pydantic"), ("sqlalchemy", "SQLAlchemy"),
    ("celery", "Celery"), ("torch", "PyTorch"), ("tensorflow", "TensorFlow"),
    ("pandas", "pandas"), ("mcp", "MCP SDK"), ("langchain", "LangChain"),
)
_RUST_FRAMEWORKS = (("tokio", "Tokio"), ("axum", "Axum"), ("actix-web", "Actix Web"),
                    ("rocket", "Rocket"), ("serde", "Serde"), ("clap", "clap"),
                    ("tauri", "Tauri"), ("bevy", "Bevy"))


# ----------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------
def _fit_list(items: list[str], prefix: str = "", limit: int = FACT_TOKENS) -> str:
    """Join ``items`` into one value that stays within the atomic fact budget."""
    items = [str(item).strip() for item in items if str(item).strip()]
    unique = list(dict.fromkeys(items))
    for count in range(len(unique), 0, -1):
        more = len(unique) - count
        text = prefix + ", ".join(unique[:count]) + (f" (+{more} more)" if more else "")
        if estimate_tokens(text) <= limit:
            return text
    return ""


def _fit(text: str, limit: int = FACT_TOKENS) -> str:
    return truncate_tokens(" ".join(str(text).split()), limit)


def _read(path: Path) -> str | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None


def _req_names(requirements: Any) -> list[str]:
    names = []
    for item in requirements or []:
        match = _REQ_NAME.match(str(item))
        if match:
            names.append(match.group(1).lower())
    return names


def default_namespace(root: str | Path) -> str:
    """``~/code/My App`` -> ``project.my-app``."""
    name = _SLUG.sub("-", Path(root).resolve().name.lower()).strip("-_")[:64]
    return "project." + (name if name and name[0].isalnum() else "default")


# ----------------------------------------------------------------------------
# TOML: stdlib tomllib on 3.11+, a small subset parser on 3.10
# ----------------------------------------------------------------------------
class _MiniToml:
    """Enough TOML for manifests: tables, dotted keys, strings, arrays, inline tables."""

    def __init__(self, text: str):
        self.s = text
        self.i = 0

    def error(self, message: str) -> ValueError:
        line = self.s.count("\n", 0, self.i) + 1
        return ValueError(f"TOML parse error on line {line}: {message}")

    def ws(self, newlines: bool = False) -> None:
        while self.i < len(self.s):
            ch = self.s[self.i]
            if ch in " \t\r" or (newlines and ch == "\n"):
                self.i += 1
            elif ch == "#":
                while self.i < len(self.s) and self.s[self.i] != "\n":
                    self.i += 1
            else:
                break

    def parse(self) -> dict:
        root: dict = {}
        current = root
        while True:
            self.ws(newlines=True)
            if self.i >= len(self.s):
                return root
            if self.s.startswith("[[", self.i):
                self.i += 2
                keys = self.keys("]]")
                parent = self.walk(root, keys[:-1])
                array = parent.setdefault(keys[-1], [])
                if not isinstance(array, list):
                    raise self.error("array of tables conflicts with a key")
                current = {}
                array.append(current)
            elif self.s[self.i] == "[":
                self.i += 1
                current = self.walk(root, self.keys("]"))
            else:
                keys = self.keys("=")
                self.ws()
                target = self.walk(current, keys[:-1])
                target[keys[-1]] = self.value()
            self.ws()
            if self.i < len(self.s) and self.s[self.i] != "\n":
                raise self.error("expected end of line")

    @staticmethod
    def walk(table: dict, keys: list[str]) -> dict:
        for key in keys:
            nxt = table.setdefault(key, {})
            if isinstance(nxt, list):
                nxt = nxt[-1]
            if not isinstance(nxt, dict):
                raise ValueError(f"TOML key {key!r} is not a table")
            table = nxt
        return table

    def keys(self, end: str) -> list[str]:
        keys = []
        while True:
            self.ws()
            if self.i < len(self.s) and self.s[self.i] in "\"'":
                keys.append(self.string())
            else:
                start = self.i
                while self.i < len(self.s) and (self.s[self.i].isalnum() or self.s[self.i] in "_-"):
                    self.i += 1
                if start == self.i:
                    raise self.error("expected a key")
                keys.append(self.s[start:self.i])
            self.ws()
            if self.s.startswith(".", self.i):
                self.i += 1
                continue
            if not self.s.startswith(end, self.i):
                raise self.error(f"expected {end!r}")
            self.i += len(end)
            return keys

    def string(self) -> str:
        quote = self.s[self.i]
        if self.s.startswith(quote * 3, self.i):
            self.i += 3
            if self.s.startswith("\n", self.i):
                self.i += 1
            end = self.s.find(quote * 3, self.i)
            if end < 0:
                raise self.error("unterminated multi-line string")
            raw = self.s[self.i:end]
            self.i = end + 3
            return self.unescape(raw) if quote == '"' else raw
        self.i += 1
        out = []
        while self.i < len(self.s):
            ch = self.s[self.i]
            if ch == quote:
                self.i += 1
                text = "".join(out)
                return self.unescape(text) if quote == '"' else text
            if ch == "\n":
                break
            if ch == "\\" and quote == '"':
                out.append(self.s[self.i:self.i + 2])
                self.i += 2
                continue
            out.append(ch)
            self.i += 1
        raise self.error("unterminated string")

    @staticmethod
    def unescape(text: str) -> str:
        table = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "b": "\b", "f": "\f"}

        def replace(match: re.Match) -> str:
            body = match.group(1)
            if body[0] in "uU":
                return chr(int(body[1:], 16))
            if body[0] == "\n":
                return ""
            return table.get(body, body)
        return re.sub(r"\\(u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|\n\s*|.)", replace, text)

    def value(self) -> Any:
        self.ws()
        if self.i >= len(self.s):
            raise self.error("expected a value")
        ch = self.s[self.i]
        if ch in "\"'":
            return self.string()
        if ch == "[":
            self.i += 1
            items = []
            while True:
                self.ws(newlines=True)
                if self.s.startswith("]", self.i):
                    self.i += 1
                    return items
                items.append(self.value())
                self.ws(newlines=True)
                if self.s.startswith(",", self.i):
                    self.i += 1
                elif not self.s.startswith("]", self.i):
                    raise self.error("expected ',' or ']'")
        if ch == "{":
            self.i += 1
            table: dict = {}
            self.ws()
            if self.s.startswith("}", self.i):
                self.i += 1
                return table
            while True:
                keys = self.keys("=")
                self.walk(table, keys[:-1])[keys[-1]] = self.value()
                self.ws()
                if self.s.startswith(",", self.i):
                    self.i += 1
                    continue
                if self.s.startswith("}", self.i):
                    self.i += 1
                    return table
                raise self.error("expected ',' or '}'")
        match = re.compile(r"[^\s,\]\}#]+").match(self.s, self.i)
        if not match:
            raise self.error("expected a value")
        self.i = match.end()
        token = match.group(0)
        if token in {"true", "false"}:
            return token == "true"
        try:
            return int(token.replace("_", ""), 0)
        except ValueError:
            pass
        try:
            return float(token.replace("_", ""))
        except ValueError:
            return token  # dates and other scalars stay as text


try:  # Python 3.11+
    import tomllib as _tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    _tomllib = None


def parse_toml(text: str) -> dict:
    if _tomllib is None:  # pragma: no cover - exercised on Python 3.10
        return _MiniToml(text).parse()
    try:
        return _tomllib.loads(text)
    except _tomllib.TOMLDecodeError as error:
        raise ValueError(str(error)) from error


# ----------------------------------------------------------------------------
# Per-file extractors.  Each returns (slot, value) pairs.
# ----------------------------------------------------------------------------
def _pyproject(data: dict, root: Path) -> list[tuple[str, str]]:
    facts: list[tuple[str, str]] = []
    project = data.get("project") or {}
    poetry = (data.get("tool") or {}).get("poetry") or {}
    name = project.get("name") or poetry.get("name")
    version = project.get("version") or poetry.get("version")
    if name:
        facts.append(("python_package", f"{name} {version}" if version else str(name)))
    if project.get("description") or poetry.get("description"):
        facts.append(("description", project.get("description") or poetry.get("description")))
    python = project.get("requires-python") or (poetry.get("dependencies") or {}).get("python")
    if isinstance(python, str):
        facts.append(("python_requires", python))
    backend = (data.get("build-system") or {}).get("build-backend")
    if backend:
        facts.append(("python_build_backend", backend))

    deps = _req_names(project.get("dependencies"))
    deps += [key.lower() for key in (poetry.get("dependencies") or {}) if key.lower() != "python"]
    if deps:
        facts.append(("python_dependencies", _fit_list(deps)))
    extras = list((project.get("optional-dependencies") or {}).keys())
    if extras:
        facts.append(("python_extras", _fit_list(extras)))
    scripts = list((project.get("scripts") or poetry.get("scripts") or {}).keys())
    if scripts:
        facts.append(("cli_entrypoints", _fit_list(scripts)))

    every = set(deps)
    for group in (project.get("optional-dependencies") or {}).values():
        every.update(_req_names(group))
    for group in (data.get("dependency-groups") or {}).values():
        every.update(_req_names(item for item in group if isinstance(item, str)))
    frameworks = [label for key, label in _PY_FRAMEWORKS if key in every]
    if frameworks:
        facts.append(("python_frameworks", _fit_list(frameworks)))
    tool = data.get("tool") or {}
    if "pytest" in tool or "pytest" in every:
        facts.append(("python_test_framework", "pytest"))
    linters = [label for key, label in (("ruff", "Ruff"), ("black", "Black"), ("mypy", "mypy"),
                                        ("isort", "isort"), ("pyright", "Pyright")) if key in tool]
    if linters:
        facts.append(("python_tooling", _fit_list(linters)))
    if (root / "uv.lock").is_file():
        facts.append(("python_package_manager", "uv"))
    elif (root / "poetry.lock").is_file() or poetry:
        facts.append(("python_package_manager", "Poetry"))
    elif (root / "pdm.lock").is_file():
        facts.append(("python_package_manager", "PDM"))
    license_value = project.get("license")
    if isinstance(license_value, dict):
        license_value = license_value.get("text") or license_value.get("file")
    if isinstance(license_value, str) and license_value:
        facts.append(("license", license_value))
    return facts


def _package_json(data: dict, root: Path) -> list[tuple[str, str]]:
    facts: list[tuple[str, str]] = []
    name, version = data.get("name"), data.get("version")
    if name:
        facts.append(("node_package", f"{name} {version}" if version else str(name)))
    if isinstance(data.get("description"), str) and data["description"]:
        facts.append(("description", data["description"]))
    deps = {**(data.get("dependencies") or {}), **(data.get("peerDependencies") or {})}
    dev = data.get("devDependencies") or {}
    every = {**deps, **dev}
    frameworks = [label for key, label in _NODE_FRAMEWORKS if key in every]
    if "typescript" in every or (root / "tsconfig.json").is_file():
        frameworks.insert(0, "TypeScript")
    if frameworks:
        facts.append(("node_frameworks", _fit_list(frameworks)))
    tests = [label for key, label in _NODE_TESTS if key in every]
    if tests:
        facts.append(("node_test_framework", _fit_list(tests)))
    if deps:
        facts.append(("node_dependencies", _fit_list(list(deps))))
    scripts = list((data.get("scripts") or {}).keys())
    if scripts:
        facts.append(("node_scripts", _fit_list(scripts)))
    manager = str(data.get("packageManager") or "").split("@")[0]
    if not manager:
        for lock, label in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lockb", "bun"),
                            ("bun.lock", "bun"), ("package-lock.json", "npm")):
            if (root / lock).is_file():
                manager = label
                break
    if manager:
        facts.append(("node_package_manager", manager))
    engine = (data.get("engines") or {}).get("node")
    if isinstance(engine, str):
        facts.append(("node_engine", engine))
    if data.get("type") in {"module", "commonjs"}:
        facts.append(("node_module_type", "ESM" if data["type"] == "module" else "CommonJS"))
    if isinstance(data.get("workspaces"), (list, dict)):
        facts.append(("monorepo", "npm workspaces"))
    if isinstance(data.get("license"), str) and data["license"]:
        facts.append(("license", data["license"]))
    return facts


def _cargo(data: dict, root: Path) -> list[tuple[str, str]]:
    facts: list[tuple[str, str]] = []
    package = data.get("package") or {}
    if package.get("name"):
        version = package.get("version")
        version = version if isinstance(version, str) else None
        facts.append(("rust_crate", f"{package['name']} {version}" if version else str(package["name"])))
    if isinstance(package.get("edition"), str):
        facts.append(("rust_edition", package["edition"]))
    if isinstance(package.get("description"), str) and package["description"]:
        facts.append(("description", package["description"]))
    if isinstance(package.get("rust-version"), str):
        facts.append(("rust_version", package["rust-version"]))
    deps = list((data.get("dependencies") or {}).keys())
    if deps:
        facts.append(("rust_dependencies", _fit_list(deps)))
    frameworks = [label for key, label in _RUST_FRAMEWORKS if key in deps]
    if frameworks:
        facts.append(("rust_frameworks", _fit_list(frameworks)))
    members = (data.get("workspace") or {}).get("members")
    if isinstance(members, list) and members:
        facts.append(("rust_workspace", _fit_list([str(m) for m in members])))
    if isinstance(package.get("license"), str) and package["license"]:
        facts.append(("license", package["license"]))
    return facts


def _dockerfile(text: str) -> list[tuple[str, str]]:
    """Only FROM, EXPOSE and WORKDIR are read; ENV/ARG/RUN/CMD may hold secrets."""
    images, ports, stages, workdir = [], [], set(), None
    for line in re.sub(r"\\\r?\n", " ", text).splitlines():
        parts = line.strip().split()
        if not parts or parts[0].startswith("#"):
            continue
        op = parts[0].upper()
        if op == "FROM":
            args = [part for part in parts[1:] if not part.startswith("--")]
            if args:
                image = args[0]
                if image.lower() not in stages and "$" not in image:
                    images.append(image)
                if len(args) >= 3 and args[1].upper() == "AS":
                    stages.add(args[2].lower())
        elif op == "EXPOSE":
            ports.extend(part for part in parts[1:] if re.fullmatch(r"\d{1,5}(/(tcp|udp))?", part))
        elif op == "WORKDIR" and len(parts) > 1 and "$" not in parts[1]:
            workdir = parts[1]
    facts: list[tuple[str, str]] = []
    if images:
        facts.append(("docker_base_images", _fit_list(images)))
    if ports:
        facts.append(("docker_exposed_ports", _fit_list(ports)))
    if workdir:
        facts.append(("docker_workdir", workdir))
    return facts


def env_key_names(text: str) -> list[str]:
    """Return variable names from an env template.  Values are never returned."""
    names = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _ENV_KEY.match(line)
        if match:
            names.append(match.group(1))
    return list(dict.fromkeys(names))


# ----------------------------------------------------------------------------
# Scan + apply
# ----------------------------------------------------------------------------
def scan_project(root: str | Path = ".") -> dict[str, Any]:
    """Parse the project's manifests and return deterministic facts (no I/O beyond reads)."""
    started = time.perf_counter()
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"not a directory: {root}")
    facts: dict[str, dict[str, str]] = {}
    files: list[str] = []
    errors: list[dict[str, str]] = []
    languages: list[str] = []

    def add(pairs: list[tuple[str, str]], source: str) -> None:
        for slot, value in pairs:
            value = _fit(value)
            if value and slot not in facts:  # first manifest wins (e.g. description)
                facts[slot] = {"slot": slot, "value": value, "source": source}

    def structured(name: str, loader, extractor, language: str | None) -> None:
        text = _read(root / name)
        if text is None:
            return
        files.append(name)
        try:
            data = loader(text)
            if not isinstance(data, dict):
                raise ValueError("top level is not an object")
        except ValueError as error:
            errors.append({"file": name, "error": str(error)[:200]})
            return
        if language:
            languages.append(language)
        add(extractor(data, root), name)

    structured("pyproject.toml", parse_toml, _pyproject, "Python")
    structured("package.json", json.loads, _package_json, None)
    if "package.json" in files and "package.json" not in {e["file"] for e in errors}:
        languages.append("TypeScript" if "TypeScript" in facts.get("node_frameworks", {}).get("value", "")
                         else "JavaScript")
    structured("Cargo.toml", parse_toml, _cargo, "Rust")

    for name in ("Dockerfile", "dockerfile", "Containerfile"):
        text = _read(root / name)
        if text is not None:
            files.append(name)
            add(_dockerfile(text), name)
            break
    for name in ("compose.yaml", "compose.yml", "docker-compose.yml", "docker-compose.yaml"):
        if (root / name).is_file():
            add([("container_orchestration", "Docker Compose")], name)
            break

    for name in ENV_EXAMPLES:
        text = _read(root / name)
        if text is not None:
            files.append(name)
            keys = env_key_names(text)
            if keys:
                add([("env_keys", _fit_list(keys))], name)
            break

    if not languages and (root / "go.mod").is_file():
        languages.append("Go")
    if languages:
        add([("languages", _fit_list(list(dict.fromkeys(languages))))], "manifests")
    if "license" not in facts:
        for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
            text = _read(root / name)
            if text:
                first = next((line.strip() for line in text.splitlines() if line.strip()), "")
                if first:
                    add([("license", first)], name)
                break

    elapsed = (time.perf_counter() - started) * 1000
    return {"root": str(root), "namespace": default_namespace(root), "files": files,
            "facts": list(facts.values()), "errors": errors, "elapsed_ms": round(elapsed, 2),
            "llm_tokens": 0}


def apply_scan(ledger, scan: dict[str, Any], namespace: str | None = None, *,
               dry_run: bool = False) -> dict[str, Any]:
    """Save scanned facts as EXTRACTED.  Confirmed and deleted slots are left alone."""
    from ..vault.ledger import LockedSlot, TombstonedSlot

    namespace = namespace or scan["namespace"]
    existing = {fact["slot"]: fact for fact in ledger.list(namespace=namespace, include_tombstones=True)}
    saved, updated, unchanged, skipped = [], [], [], []
    produced = set()
    for item in scan["facts"]:
        slot, value = item["slot"], item["value"]
        produced.add(slot)
        current = existing.get(slot)
        if current and not current["tombstone"] and current["value"] == value:
            unchanged.append(slot)
            continue
        if current and current["tombstone"]:
            skipped.append({"slot": slot, "reason": "deleted_by_user"})
            continue
        if current and current["verification_state"] in {"USER_CONFIRMED", "SPEC_LOCKED"}:
            skipped.append({"slot": slot, "reason": "user_confirmed"})
            continue
        if dry_run:
            (updated if current else saved).append(slot)
            continue
        try:
            ledger.record(namespace, slot, value, verification_state="EXTRACTED",
                          source_id=SCAN_SOURCE_PREFIX + item["source"])
        except LockedSlot:
            skipped.append({"slot": slot, "reason": "user_confirmed"})
            continue
        except TombstonedSlot:
            skipped.append({"slot": slot, "reason": "deleted_by_user"})
            continue
        except ValueError as error:
            skipped.append({"slot": slot, "reason": str(error)[:120]})
            continue
        (updated if current else saved).append(slot)
    stale = sorted(slot for slot, fact in existing.items()
                   if not fact["tombstone"] and slot not in produced
                   and fact["verification_state"] == "EXTRACTED"
                   and str(fact.get("source_id") or "").startswith(SCAN_SOURCE_PREFIX))
    return {"namespace": namespace, "saved": saved, "updated": updated, "unchanged": unchanged,
            "skipped": skipped, "stale": stale, "dry_run": dry_run}
