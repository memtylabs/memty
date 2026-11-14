<p align="center">
  <img src="https://raw.githubusercontent.com/memtylabs/memty/main/assets/memty-wordmark-light.png" alt="Memty" width="320">
</p>

<p align="center"><b>Your AI memory, owned by you.</b><br>
One private, local memory vault for every AI assistant you use.</p>

<p align="center">
  <a href="https://pypi.org/project/memty/"><img src="https://img.shields.io/pypi/v/memty.svg" alt="PyPI version"></a>
  <a href="https://pypi.org/project/memty/"><img src="https://img.shields.io/pypi/pyversions/memty.svg" alt="Python versions"></a>
  <a href="https://github.com/memtylabs/memty/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License: MIT"></a>
</p>

<p align="center">
  <a href="https://memtylabs.github.io/memty/">Website</a> ·
  <a href="https://github.com/memtylabs/memty">GitHub</a> ·
  <a href="https://github.com/memtylabs/memty/blob/main/memty/CHANGELOG.md">Changelog</a> ·
  <a href="https://github.com/memtylabs/memty/blob/main/SECURITY.md">Security</a>
</p>

Memty keeps the facts, decisions and preferences you share with AI in **one SQLite file on your own computer**. It brings that memory to ChatGPT, Claude, Gemini, Perplexity, Claude Code, Codex, Cursor, VS Code, Windsurf and any MCP client, so you stop repeating yourself every time you open a new chat or switch assistants.

- **Local-first.** Your vault is `~/.memty/ledger.sqlite3`. There's no account, no cloud sync and no telemetry.
- **Works everywhere.** A browser extension for chat websites, MCP for desktop and coding tools, the clipboard for anything else, and a Python API.
- **You're in control.** Facts saved from chats are proposals you approve. You can edit, mark private, or permanently delete anything.
- **Private by design.** Private facts reach cloud AIs only as `[private]`. Secrets, including API keys you paste by accident, never leave your machine.
- **Verified releases.** Every release from 0.2.1 on is built by GitHub Actions and published with PyPI provenance attestations.

> **Alpha (0.x).** The vault's storage format is stable and covered by tests. Commands and options may still change between versions.

## Quick start

You need Python 3.10 or newer on Windows, macOS or Linux.

```shell
pip install memty

memty serve --autostart   # 1. start the local bridge now and at every login (one time)
memty extension --open    # 2. install the browser extension folder and open it
memty connect             # 3. optional: connect Claude Code, Codex, Cursor, VS Code and others
```

Load the extension once:

1. Open `chrome://extensions` (or `edge://extensions`).
2. Turn on **Developer mode**.
3. Click **Load unpacked** and choose the folder that opened.

It pairs itself with Memty, so there's no token to copy.

> **Windows: is `memty` "not recognized"?** Use `py -m memty` in place of `memty`, for example `py -m pip install --upgrade memty` and then `py -m memty extension`.

## Using it in a chat

On ChatGPT, Claude.ai, Gemini or Perplexity:

| Action | What happens |
| --- | --- |
| Select text, then **＋ Save to Memty** | Memty proposes short facts. You edit or untick them, then save. |
| **⚡ Memty** (or Alt+M) | Pick a saved context. Its numbered facts go into the message box for you to check before sending. |
| **☰ Your facts** | View, search, edit, add, delete or mark facts private. |

What gets pasted into the chat:

```text
[Memty context]
1. Database: PostgreSQL 16 on Neon
2. Deploy target: Fly.io
3. Client: [private]
[/Memty]
```

From the terminal:

```shell
memty remember work.project editor "VS Code"
memty recall "Which editor do I use?" --namespace work.project
memty clip work.project        # copy your facts for any AI app
```

## How it works

- **Atomic facts.** Memory is stored as small `namespace.slot = value` facts of at most 40 tokens, for example `work.project.editor = "VS Code"`. Updating a slot keeps its history.
- **Namespaces** such as `work.project` and `personal` keep contexts apart. A chat only gets the namespace you choose.
- **One daemon, every tool.** The browser bridge, every MCP client and the CLI all go through one local process (`memtyd`) for your vault. A fact you save in ChatGPT is available in Claude Code a moment later.
- **The compiler** builds a small capsule for each request, newest facts first or the most relevant ones for a question, always under a hard token budget.
- **The privacy gate** checks every capsule before anything is shown to an AI:

| Level | Cloud assistants see | Example |
| --- | --- | --- |
| PUBLIC | The value | `Editor: VS Code` |
| INTERNAL | Nothing (only local or trusted models do) | (left out) |
| CONFIDENTIAL | A placeholder | `Client: [private]` |
| SECRET | Nothing: the request is refused and a local model is suggested | request refused |

## Security and privacy

The browser bridge runs only on `127.0.0.1`, so it's built so that websites can't read your vault:

- Every request needs a pairing token, stored owner-only beside your vault.
- Web pages are refused. Only the browser extension you paired can connect (`memty pair` adds another browser).
- `Host` header checks block DNS rebinding, and writes must be JSON, which blocks form-based attacks.
- A browser can't claim to be a local model to get SECRET facts, and can't make a SECRET fact public.

Built-in protections for your data:

- **Credentials are always SECRET.** API keys (OpenAI, Anthropic, GitHub, AWS, Slack, Google and more), tokens, private keys and `password: ...` lines are stored as SECRET however they're saved.
- **Forget means forget.** `memty forget` erases the value from the vault file on disk, including the search index and the write-ahead log.
- **Automation can't overrule you.** Extraction and agents can't overwrite facts you confirmed or bring back facts you deleted. An agent's change to an existing fact waits in `memty inbox` for your approval.
- **Saved text can't hijack a chat.** A stored value can't close or forge Memty's context markers.
- **Every capsule is accounted for.** Receipts record what was shared, with counts and slot names, never values. See `memty report`.

**Test it yourself.** The repository has 61 adversarial tests that attack each of these promises. See [Security testing](https://github.com/memtylabs/memty/blob/main/docs/SECURITY_TESTING.md). To report a vulnerability, see the [security policy](https://github.com/memtylabs/memty/blob/main/SECURITY.md).

The vault file itself is **not encrypted**; it relies on your computer account's protection. Keep it out of synced folders such as OneDrive or Dropbox unless you want it uploaded.

## Coding agents and desktop apps (MCP)

```shell
memty connect --dry-run        # show the plan without changing anything
memty connect                  # connect every detected client
memty connect --client Cursor  # only one client (repeatable)
```

Memty never edits another app's settings file itself. Each change goes through the app's own installer, or you get the exact steps:

| Client | How it's connected |
| --- | --- |
| Claude Code | Its official `claude mcp add` command |
| Codex CLI | Its official `codex mcp add` command |
| VS Code | Its official `code --add-mcp` command |
| Cursor | Cursor's MCP install link; Cursor asks you to confirm |
| Claude Desktop, Windsurf | Prints the exact entry and where to put it |

Restart each client afterwards. The MCP server offers three tools:

- **`memty_sync`** recalls a capsule of up to 120 tokens for a namespace. On your explicit request, it also saves facts.
- **`memty_propose`** lets an agent suggest a fact it learned. New facts are saved as extracted; changes to existing facts wait in `memty inbox`.
- **`memty_drill`** reads archived source text, and only for a genuinely local model.

MCP clients are treated as cloud providers, so the privacy gate applies. Clients don't load memory on their own: ask the assistant to call `memty_sync`, or add that instruction to the client's agent settings.

## Project memory, inbox and receipts

```shell
memty scan            # save 10-20 facts about a code project from its manifests (0 LLM tokens)
memty inbox           # facts your agents proposed
memty approve 1       # accept one (memty reject 1 discards it)
memty report          # capsules served, facts reused, tokens saved, secrets protected
```

`memty scan` (or `memty init`) reads `pyproject.toml`, `package.json`, `Cargo.toml`, `Dockerfile` and `.env.example` at the project root. It makes no model or network calls, takes only key names from env templates, and never opens a real `.env`.

## Commands

| Command | What it does |
| --- | --- |
| `memty serve --autostart` | Start the browser bridge now and at every login. `--no-autostart` undoes it, `--stop` stops it. |
| `memty extension` | Install or update the browser extension folder. `--open` opens it. |
| `memty pair` | Let one more browser or a reinstalled extension connect within two minutes |
| `memty connect` | Connect Claude Code, Codex CLI, VS Code, Cursor, Windsurf and Claude Desktop |
| `memty remember NS SLOT VALUE` | Save a fact. `--sensitivity SECRET` keeps it on this computer. |
| `memty recall "question"` | Print the capsule for a question. `--namespace` and `--provider` narrow it. |
| `memty clip NS` | Copy a namespace's facts to the clipboard for any AI app |
| `memty list` / `memty history NS SLOT` | List active facts, or earlier versions of one fact |
| `memty forget NS SLOT` | Delete a fact and its history. `--purge-raw` also deletes archived source text. |
| `memty scan` / `memty inbox` / `memty report` | Project facts, agent proposals, usage receipts |
| `memty serve --new-token` | Revoke access. Every extension must pair again. |
| `memtyd status` / `start` / `stop` | Check or control the shared background daemon |

Run `memty --help` for every option.

| Setting | Default | Purpose |
| --- | --- | --- |
| `--db` or `MEMTY_VAULT_PATH` | `~/.memty/ledger.sqlite3` | Where your vault lives |
| `--user` or `MEMTY_USER` | `local` | User inside the vault |
| `MEMTY_PROVIDER` | `mcp` (treated as cloud) | How MCP clients are treated by the privacy gate |
| `MEMTY_OLLAMA_MODEL` | not set | Use a local Ollama model to extract facts |

## Python API

```python
from memty import open_ledger, LocalRoutingRequired

vault = open_ledger()  # ~/.memty/ledger.sqlite3

vault.record("work.project", "editor", "VS Code", verification_state="USER_CONFIRMED")
vault.record("work.project", "client", "Acme Corp", sensitivity="CONFIDENTIAL")

capsule = vault.context("Which editor do I use?", provider="claude", namespace="work.project")
print(capsule["text"])  # the client appears only as a placeholder

vault.record("work.project", "db_password", "hunter2", sensitivity="SECRET")
try:
    vault.context("database password", provider="claude", namespace="work.project")
except LocalRoutingRequired as refused:
    print(refused.as_dict())  # suggests a local model; never contains the secret
```

Local providers (`local`, `ollama`, `local_ollama`, `memty_local`) see every value. Cloud providers go through the privacy gate.

## Uninstall

```shell
memty serve --no-autostart   # stop the bridge and remove the login item
pip uninstall memty
```

Remove the extension in `chrome://extensions`. Your vault stays in `~/.memty/` until you delete that folder.

## License

MIT. See [LICENSE](https://github.com/memtylabs/memty/blob/main/LICENSE).
