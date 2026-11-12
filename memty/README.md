# Memty

**Your AI memory, owned by you.** Memty keeps the facts, decisions, and preferences you share with AI assistants in one private vault on your own computer. It brings that memory to Claude, ChatGPT, Gemini, Perplexity, Cursor, Windsurf, and any MCP client, so you stop repeating yourself every time you open a new chat or switch to a different assistant.

[![PyPI](https://img.shields.io/pypi/v/memty.svg)](https://pypi.org/project/memty/)
[![Python](https://img.shields.io/pypi/pyversions/memty.svg)](https://pypi.org/project/memty/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/memtylabs/memty/blob/main/LICENSE)

- **Local-first.** The vault is a single SQLite file in `~/.memty/`. There are no accounts, no cloud sync, and no telemetry.
- **Works everywhere.** It connects to MCP clients (Claude Desktop, Claude Code, Codex CLI, VS Code, Cursor, Windsurf), to chat websites through a browser extension, and to anything else through the clipboard.
- **Under your control.** You can view, edit, delete, and mark any fact private. Deleted facts stay deleted, and AI extraction can never bring them back.
- **Private by design.** Private values are hidden from cloud AIs and appear only as `[private]`. Secrets never leave your machine.
- **Small and fast.** Capsules stay under a fixed token budget, and the core uses only the Python standard library.

> Memty is in alpha (0.x). The storage format is stable and covered by tests, but commands and options may still change between minor versions. See the [changelog](https://github.com/memtylabs/memty/blob/main/memty/CHANGELOG.md).

## Token Burn Benchmark

Three live runs of one synthetic five-turn handoff between Claude Haiku 5.5 and Gemini 2.5 Flash produced the following provider-reported input usage:

| Context supplied | Average input tokens per run | Reduction with Memty | Exact answers across three runs |
| --- | ---: | ---: | ---: |
| Full document replay | 4,663 | 61.1% | 27/30 |
| Simulated retrieval with curated snippets and illustrative schemas | 3,128.7 | 42.0% | 27/30 |
| Selected Memty context | 1,816 | — | 30/30 |

This is one synthetic fixture with preselected Memty facts; the retrieval baseline did not call a real retrieval product. It is not a guarantee of universal recall or savings. See the [benchmark, individual runs, and reproduction instructions](../benchmarks/token_burn/README.md).

---

## Quick start (about 3 minutes)

```shell
pip install memty

memty serve --autostart   # 1. start the local bridge now and at every login (one time)
memty extension           # 2. install the browser extension folder and show where it is
memty connect             # 3. optional: connect Claude Desktop, Claude Code, Cursor, Windsurf
```

### Windows: `memty` is not recognized

This usually means the Python Scripts folder is not on your PATH, or Memty was
installed into a different Python environment. In Command Prompt or PowerShell,
install and run it with the same Python interpreter:

```shell
py -m pip install --upgrade memty
py -m memty
```

You can use `py -m memty` in place of `memty` for every command, for example
`py -m memty extension`. If `py` is unavailable, use `python -m pip install --upgrade memty`
and `python -m memty` instead. If you installed Memty in a virtual environment,
activate that same environment first in each new terminal.

To make the shorter `memty` command work without an activated environment, add
the Scripts folder reported in the pip installation warning to your Windows
user PATH, then open a new terminal. If there was no warning, use
`py -m pip show -f memty` to locate `memty.exe` under the installation's Scripts
folder. If `py -m memty` says there is no module named `memty`, install it using
the same `py` or `python` command you use to run it.

Then load the extension once. Open `chrome://extensions` (or `edge://extensions`), turn on **Developer mode**, click **Load unpacked**, and choose the folder that `memty extension` printed. There's no token to copy and nothing to configure: the extension pairs itself with Memty on your computer.

In any chat on ChatGPT, Claude.ai, Gemini, or Perplexity:

- **Select text → ＋ Save to Memty.** Memty proposes short, atomic facts. You edit or untick them, then save.
- **⚡ Memty (or Alt+M).** Choose a saved context, newest first. Its numbered facts are added to the prompt for you to check before sending:

  ```
  [Memty context]
  1. Company: MEMTY
  2. Category: Portable AI Memory Infrastructure
  3. Client: [private]
  [/Memty]
  ```

- **☰ (or the extension icon).** Opens **Your Memty facts**, where you can view, search, edit, add, delete, or mark facts private.

Prefer the terminal?

```shell
memty remember work.project editor "VS Code"
memty recall "Which editor do I use?" --namespace work.project
memty clip work.project            # copy your facts to the clipboard for any AI
```

---

## How it works

```
 ChatGPT · Claude.ai · Gemini · Perplexity          Claude Desktop · Claude Code · Cursor · Windsurf
                │  browser extension                               │  MCP (stdio)
                ▼                                                  ▼
     memty serve  (127.0.0.1 only, paired token)          memty mcp
                └──────────────────────┬───────────────────────────┘
                                       ▼
                        memtyd  (one local daemon per vault)
                                       ▼
                ~/.memty/ledger.sqlite3   (your vault: SQLite, on your disk)
```

1. **Atomic facts.** Memory is stored as small `namespace.slot = value` facts, for example `work.project.editor = "VS Code"`. There is one value per slot and each fact is at most 40 tokens. CLI updates replace a slot and keep an audit trail. Each reviewed browser save creates a separate context, so a later selection with the same titles does not overwrite it.
2. **Namespaces** keep contexts apart (`work.project`, `personal`, `client.acme`). A chat only receives the namespace you choose.
3. **The compiler** builds a small capsule for each request. Without a question it lists the newest facts first. With a question it ranks facts by relevance. Either way the capsule stays within a hard token budget.
4. **The privacy gate** runs on every capsule:
   - **PUBLIC** facts are shared.
   - **CONFIDENTIAL** (private) facts appear only as `[private]` to cloud assistants.
   - **SECRET** facts stop the request and ask for a local model instead.
5. **You stay in control.** Facts saved from chats are proposals until you approve them. Facts you confirm can't be overwritten by automatic extraction. Deleting a fact removes it and its history, and it can't be brought back automatically.

---

## Browser extension (Chrome, Edge, Brave)

The **Memty Bridge** extension ships inside this package.

```shell
memty extension          # copies it to ~/.memty/browser-extension and prints the steps
memty extension --open   # also opens the folder
```

After `pip install -U memty`, run `memty extension` again and click reload on the extension in `chrome://extensions`. Open chat tabs pick up the new version without a refresh.

| Feature | What it does |
| --- | --- |
| ⚡ Memty / Alt+M | Choose a context from newest to oldest and add its individually numbered facts to the prompt |
| Select text → ＋ Save to Memty | Proposes atomic facts from the selection. You edit titles and values, then save. |
| ＋ Save | The same, for your selection or the latest answer |
| ☰ Your facts | View, search, edit, add, delete, and mark facts private |
| Draggable pill | Drag the ⋮⋮ grip anywhere. Each site remembers the position, and a double-click resets it. |

How facts are extracted, all on your machine:

- Headings, questions, and Memty blocks you pasted earlier are skipped.
- Prose and list items are both considered. Long facts are split into related parts instead of silently cutting off their endings. The review panel shows the original text and warns about known limits; check the proposed facts before saving.
- A single review can propose up to 25 facts. Select another part of the text if the review reports that some proposals were left out.
- Bare file paths are grouped into one `files` fact.
- Code is never stored. Each code block becomes one summary, such as `JavaScript code in content.js defines saveFacts`.
- Set `MEMTY_OLLAMA_MODEL` (for example `llama3.1`) to extract and summarize with a local Ollama model. If Ollama doesn't respond, Memty falls back to its built-in rules. Both approaches can miss context, so review the result.

### Bridge commands

```shell
memty daemon                   # start the vault daemon and browser bridge together
memty serve --autostart        # also start the browser bridge at every login (per-user, no admin)
memty serve --no-autostart     # stop it and remove the login item
memty serve --background       # start quietly once
memty serve --stop
memty pair                     # connect another browser or a reinstalled extension (2-minute window)
memty serve --new-token        # revoke access: new token, forget the paired extension (restart the bridge)
memty serve --show-token       # for manual pairing (extension options > Advanced)
```

### Security model

The bridge runs on your computer, so it's built so that websites can't read or change your vault:

- It binds only to `127.0.0.1`, and the address can't be configured.
- Every data route needs `Authorization: Bearer <token>`. The token is stored owner-only in `<db>.web-token`.
- **Pairing is trust on first use.** `POST /pair` only answers browser-extension origins, and the first extension to ask is remembered. Web pages and other extensions are refused (`403`). To add another browser, or an extension you reinstalled, run `memty pair`: it lets exactly one more extension connect within two minutes.
- Requests from web-page origins are refused, and the `Host` header must be `127.0.0.1` or `localhost`, which blocks DNS rebinding. Writes must be `application/json`.
- Capsules are compiled for each site as a cloud provider. Private values are never sent to the browser, not even to the facts page, and redaction maps never leave the bridge.
- The extension's background worker is the only part that holds the token. Scripts running inside chat sites never see it.

| Route | Purpose |
| --- | --- |
| `GET /health` | Liveness check (no token, no data) |
| `POST /pair` | Token for the paired extension only |
| `GET /contexts?provider=` | Saved contexts across namespaces, newest first; previews respect privacy |
| `GET /capsule?namespace=&provider=&context=&tokens=2000&format=text` | Numbered facts for one selected context |
| `GET /capsule?namespace=&provider=&query=&tokens=350&format=text\|xml` | Legacy query or latest-save capsule |
| `GET /namespaces` | Namespace names and fact counts |
| `GET /facts?namespace=` | Facts, newest first; private values are `null` |
| `POST /extract` `{"text"}` | Proposed facts. Writes nothing. |
| `POST /facts` `{"namespace", "facts": [{"slot", "value"}], "confirmed", "separate_context"}` | Saves a reviewed selection as one context when both flags are true |
| `POST /facts/update` `{"namespace", "slot", "new_slot", "value", "private"}` | Edits, renames, or changes privacy (saved as user-confirmed) |
| `POST /facts/delete` `{"namespace", "slot"}` | Forgets a fact and its history |

---

## Clipboard: any AI, any app

```shell
memty clip work.project                    # copy your facts as Title: value lines
memty clip work.project --query "deploy"   # rank facts for a question
memty clip work.project --print            # print instead of copying
memty clip work.project --format xml       # the <memty_state> block for agents and tools
```

The clipboard counts as a cloud destination: private values are redacted, and the command exits with status 2 if a SECRET fact matches. Use `--provider local` only when the paste goes to a local model. Memty uses the operating system's own clipboard tool: `clip` on Windows, `pbcopy` on macOS, and `wl-copy`, `xclip`, or `xsel` on Linux.

To bind it to a hotkey:

- **Windows**: create a shortcut whose target is `pythonw -m memty clip work.project`, then set a **Shortcut key** in its properties.
- **macOS**: in Shortcuts, add *Run Shell Script* with `memty clip work.project` and assign a shortcut.
- **Linux**: bind the command in your desktop's keyboard settings.

---

## MCP clients: Claude Desktop, Claude Code, Codex CLI, VS Code, Cursor, Windsurf

```shell
memty connect --dry-run            # show the plan; run and open nothing
memty connect                      # connect every detected client
memty connect --no-open            # print the Cursor link instead of opening it
memty connect --client Cursor      # only one client (repeatable)
```

**Memty never creates, edits, or deletes another application's settings file.** Each change goes through the client's own installer, or through you:

| Client | How `memty connect` connects it |
| --- | --- |
| Claude Code | Runs Claude Code's official `claude mcp add --scope user memty -- <python> -m memty mcp` |
| Cursor | Opens Cursor's official MCP install link, and Cursor asks you to confirm |
| Codex CLI | Runs `codex mcp add memty -- <python> -m memty mcp` through Codex's installer |
| VS Code | Runs `code --add-mcp` with a stdio server definition; confirm in VS Code |
| Claude Desktop | Prints the exact entry and steps (Settings > Developer > Edit Config) |
| Windsurf | Prints the exact entry and steps for Windsurf's MCP settings |

Restart each client after connecting it. Every MCP process talks to the same `memtyd` for the configured vault. For example, saving `project.api.editor = VS Code` in Codex makes it available to Cursor's next `memty_sync(namespace="project.api")` call. The server exposes three tools:

- `memty_sync(namespace, query, set_slots)` recalls a 120-token capsule. On an explicit user request, `set_slots` saves up to 25 confirmed slot/value pairs and returns the updated capsule in the same call. The older `action=remember|forget` form remains available for single-slot changes.
- `memty_propose(namespace, slot, value, reason)` is for facts an agent learns on its own. A new slot is saved as `EXTRACTED`. A change to an existing or deleted slot is never written directly: it waits in `memty inbox` until you approve it (see [Trust control plane](#trust-control-plane-scan-inbox-receipts)). The reply never echoes the value already saved.
- `memty_drill(namespace, slot)` returns at most 4,000 characters of archived source, only when `MEMTY_PROVIDER` names a genuinely local model. It never runs for the default cloud-provider identity.

The resource template `memty://capsule/{namespace}` is also available. **MCP clients do not automatically read a resource merely because it is registered**; ask the assistant to call `memty_sync` for the relevant namespace. If you want this every chat, put a concise instruction in the client's own agent settings. The client and model still decide when to call tools.

MCP capsules are limited to 120 tokens, and MCP clients are treated as cloud providers by default, so the privacy gate applies. Set `MEMTY_PROVIDER` to a local identity only when the model really runs locally. Tool schemas and returned capsules still use tokens; no fixed percentage saving is guaranteed.

Note: Memty 0.1.0 and 0.1.1 could write client settings files directly. If a client broke after one of those versions ran, use that client's recovery steps. Don't delete its whole configuration file.

---

## Trust control plane: scan, inbox, receipts

### Bootstrap a project without a model: `memty scan`

```shell
cd ~/code/billing-api
memty scan                 # or: memty scan PATH --namespace project.billing --dry-run
```

```
Scanned 4 file(s) in 3.1 ms (0 LLM tokens): pyproject.toml, package.json, Dockerfile, .env.example
project.billing-api: 14 saved, 0 updated, 0 unchanged
  + python_package = billing-api 1.4.2
  + python_frameworks = FastAPI, SQLAlchemy
  + env_keys = STRIPE_SECRET_KEY, DATABASE_URL, REDIS_URL
  ...
```

The scan reads `pyproject.toml`, `package.json`, `Cargo.toml`, `Dockerfile` and `.env.example` (or `.env.sample` / `.env.template`) at the project root. It makes no model or network calls. It typically saves 10 to 20 facts to `project.<folder>`: name and version, runtime, frameworks, dependencies, scripts, package manager, test framework, base images, exposed ports, environment key names, and license.

- **No secret values.** Env templates contribute key names only, and a real `.env` is never opened. From a Dockerfile only `FROM`, `EXPOSE` and `WORKDIR` are read; `ENV`, `ARG`, `RUN` and `CMD` are ignored.
- **Your edits win.** Facts are saved as `EXTRACTED`, so a scan never overwrites a value you confirmed and never recreates a slot you deleted. Running the scan again updates only the values that changed. It lists facts that are no longer in the project but doesn't delete them.
- `memty init` is the same command: run it once in a project folder to bootstrap that project's memory.

### Agent proposal inbox: `memty inbox`, `memty approve`, `memty reject`

When Cursor, Claude Code, or another MCP client learns something, it calls `memty_propose`. A conflicting change never overwrites your memory. It is queued for your review:

```shell
memty inbox
# [1] project.api -> cache_engine: "Redis" [confirmed] => "DragonflyDB" (Proposed by Cursor)
#       why: docker-compose runs dragonfly
memty approve 1            # saved as USER_CONFIRMED; the old value stays in `memty history`
memty reject 1             # discarded; the saved fact is untouched
memty approve --all        # or several ids: memty approve 1 2 3
memty inbox --all          # include approved, rejected and superseded proposals
```

Approving a value keeps the slot's existing sensitivity and provider rules. A newer proposal for the same slot supersedes the older one. `memty forget` also removes any proposals for that slot.

### Context receipts: `memty receipts`, `memty report`

Each time `memty recall`, `memty clip`, MCP, or the browser bridge serves a capsule, Memty writes a receipt and increments a `hit_count` on each injected fact. The same happens when a SECRET slot blocks a request. A receipt holds the channel, the client, token counts, the number of redacted values, and slot **names**. It never stores values.

```shell
memty report
# 42 capsules served across Claude, Cursor & Perplexity | 114 verified facts reused | ~91,000 tokens saved | 4 SECRET slots protected
memty report --days 7 --json
memty receipts --limit 20
memty list --namespace project.api      # each fact now shows its hit_count
```

"Tokens saved" is a conservative local estimate. It compares each capsule with the token count of the full namespaces it drew from plus their archived raw sources, at about 4 characters per token. It is not a provider bill. The report prints this caveat. MCP receipts use the client name reported by the MCP client, while privacy decisions still use `MEMTY_PROVIDER`.

After upgrading, run `memtyd stop` once so the background daemon reloads with the new commands.

---

## CLI reference

```shell
memty remember work.preferences editor "VS Code" --verification USER_CONFIRMED
memty recall "Which editor do I use?" --provider claude --tokens 600
memty list                                   # active facts
memty history work.preferences editor        # superseded versions
memty forget work.preferences editor --purge-raw
memty summary repo.memty --set "Memty uses Postgres and a local context compiler."
memty rule repo.memty database_queries "writing database queries" "always use async Motor"
memty rules --namespace repo.memty
memty rule-delete repo.memty database_queries
memty stats
memty migrate ~/.memty/memory.sqlite3        # import from an earlier Memty vault
memty scan [PATH] [--dry-run]                # bootstrap project facts from manifests, 0 tokens
memty inbox                                  # agent proposals waiting for review
memty approve 1 / memty reject 1             # resolve a proposal (--all for every one)
memty receipts --limit 20                    # recent capsules served (no values)
memty report [--days 7] [--json]             # capsules, reuse, tokens saved, secrets protected
memty --version
```

`memty recall` prints a deterministic `<memty_state>` capsule and never includes archived raw source text. If a SECRET fact matches a cloud provider, it exits with status 2 and prints a `local_routing_required` payload.

### Configuration

| Setting | Default | Purpose |
| --- | --- | --- |
| `--db` / `MEMTY_VAULT_PATH` (or `MEMTY_DB`) | `~/.memty/ledger.sqlite3` | Vault location |
| `--user` / `MEMTY_USER` | `local` | User ID inside the vault |
| `MEMTY_PROVIDER` | external | Identity used by MCP capsules |
| `MEMTY_OLLAMA_MODEL`, `MEMTY_OLLAMA_HOST` | not set, `http://127.0.0.1:11434` | Local model for fact extraction |

### The local daemon

The MCP servers, the CLI, and the web bridge share one `memtyd` process for each vault. It starts automatically when it's needed and keeps one SQLite connection. It uses authenticated loopback connections, and its endpoint and secret are stored beside the database, so keep that folder private.

```shell
memtyd status
memtyd start
memtyd stop     # add --db PATH for a non-default vault
```

---

## Python API

```python
from memty import open_ledger, LocalRoutingRequired

vault = open_ledger()  # ~/.memty/ledger.sqlite3, user "local"

vault.record("work.preferences", "editor", "VS Code", verification_state="USER_CONFIRMED")
vault.record("repo.memty", "primary_db", "Postgres 16", verification_state="USER_CONFIRMED")
vault.set_summary("repo.memty", "Memty uses Postgres and a local context compiler.")

compiled = vault.context("Which editor and database do I use?", provider="claude", token_budget=600)
print(compiled["text"])                   # <memty_state> capsule within the budget
print(compiled["approx_tokens"], compiled["sections"])

# Privacy gate
vault.record("user.vault", "api_key", "...", sensitivity="SECRET", verification_state="USER_CONFIRMED")
try:
    vault.context("api key", provider="claude")
except LocalRoutingRequired as exc:
    print(exc.as_dict())                  # suggests a local provider; no secret value included

vault.record("repo.memty", "internal_host", "db.internal.example",
             sensitivity="CONFIDENTIAL", verification_state="USER_CONFIRMED")
compiled = vault.context("internal host", provider="claude")   # value masked as a placeholder
answer = vault.rehydrate(model_output, compiled["redactions"]) # put it back locally
```

A provider is trusted when it is local (`local`, `ollama`, `local_ollama`, `memty_local`), was passed to `MemtyLedger(..., trusted_providers=[...])`, or is named in the fact's `allowed_providers`.

Archived raw text is never injected into a capsule. You can only read it back with an explicit call:

```python
fact = vault.record("repo.memty", "deployment_host", "db.internal.example",
                    verification_state="USER_CONFIRMED", source_raw="full log excerpt ...")
vault.drill_down(fact_id=fact["id"])
```

### Guarantees

| Guarantee | How |
| --- | --- |
| One value per slot, no contradictions | `UNIQUE(user_id, namespace, slot)`; superseded values move to `atomic_fact_audit` |
| Facts stay small | `record()` rejects values over 40 tokens |
| Deletion is permanent | `forget()` tombstones the slot and purges its plaintext and audit history |
| Extraction can't undo you | `EXTRACTED` writes can't overwrite user-confirmed slots or restore deleted ones |
| Bounded context | The compiler enforces `estimate_tokens(text) <= token_budget` |
| Fast | Warm compile median about 3 ms with 300 facts and a 600-token budget |
| Search works everywhere | FTS5 when SQLite supports it, with a SQL fallback otherwise |

---

## Code layout

Each folder in the package has one job. Start with the folder for the behavior you want to change:

```
memty/
├── cli.py                  every `memty <command>`: parses arguments and calls the folders below
├── vault/                  STORAGE: where facts live
│   ├── ledger.py           the SQLite vault: facts, rules, summaries, raw archive, audit, inbox, receipts
│   ├── paths.py            default vault path (~/.memty/ledger.sqlite3) and open_ledger()
│   ├── migrate.py          import from older vaults
│   └── tokens.py, vectors.py   token estimates and embedding packing
├── context/                CAPSULES: what an assistant gets to see
│   ├── privacy.py          the privacy gate: SECRET stays local, CONFIDENTIAL is redacted, allow/block lists
│   ├── compiler.py         ranks facts for a query and packs them into the token budget
│   └── render.py           plain "Title: value" capsules for chat apps
├── extraction/             FACTS IN: without a cloud model
│   ├── atomic_facts.py     splits selected text into short slot/value facts (heuristics or local Ollama)
│   └── project_scan.py     `memty scan`: project facts from manifests, zero tokens
├── trust/                  TRUST CONTROL PLANE
│   ├── receipts.py         logs every capsule served (counts and slot names only)
│   └── render.py           prints `memty inbox`, `memty receipts`, `memty report`
├── runtime/                BACKGROUND PROCESSES
│   ├── daemon.py           memtyd: the one process per vault that every call goes through
│   └── autostart.py        start the browser bridge at login
├── integrations/           HOW ASSISTANTS CONNECT
│   ├── mcp/server.py       MCP tools memty_sync, memty_propose, memty_drill
│   ├── mcp/connect.py      `memty connect` for Claude Code, Cursor, Codex, VS Code, Windsurf
│   ├── browser/bridge.py   127.0.0.1 HTTP bridge for the browser extension
│   ├── browser/installer.py  `memty extension`
│   ├── browser/extension/  the extension itself (JavaScript, shipped in the wheel)
│   └── clipboard.py        `memty clip`
└── legacy/                 the older temporal vault (memoryport): `memty-api` for the memory-vault service, `memty vault`, `memty vault-mcp`
```

A request flows **integration → runtime/daemon → vault/ledger → context/compiler (through context/privacy) → integration**, and the integration writes a **trust/receipts** entry. Import public names from `memty` (for example `from memty import open_ledger, MemtyLedger, LocalRoutingRequired`). The submodule paths above are internal and may change.

## Uninstall

```shell
memty serve --no-autostart      # stop the bridge and remove the login item
pip uninstall memty
```

Remove the extension from `chrome://extensions`. Your vault stays in `~/.memty/` until you delete that folder yourself.

## License

MIT. See [LICENSE](https://github.com/memtylabs/memty/blob/main/LICENSE).
