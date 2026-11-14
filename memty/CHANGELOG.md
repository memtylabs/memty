# Changelog

All notable changes to the `memty` package. This project follows [Semantic Versioning](https://semver.org/); while it is in 0.x, minor versions may change commands and options.

## Unreleased

- **Security fixes** (found by the new adversarial suite, `tests/test_memty_security.py`):
  - The browser bridge no longer accepts a local provider name (`provider=ollama`, `local`, ...). Before, any caller with the pairing token could ask for a "local" capsule and receive SECRET facts and unredacted CONFIDENTIAL values. It now answers 400.
  - Credentials are always stored as SECRET: API keys (OpenAI, Anthropic, GitHub, GitLab, AWS, Slack, Google, Stripe, Hugging Face), JWTs, private-key headers, passwords in URLs, and `password: ...` style lines. This applies to every write path (CLI, browser saves, reviewed contexts, MCP, agent proposals). Extraction marks these proposals with `"sensitivity": "SECRET"`.
  - The browser can no longer make a SECRET fact public, and saves from the browser or MCP never lower a slot's sensitivity. Making a secret public now needs the terminal.
  - `forget` now also removes the value from disk: deleted SQLite pages are zeroed (`secure_delete`), the search index is compacted, and the WAL is checkpointed. An archived source stays linked to its slot when the slot is updated, so `forget --purge-raw` can still find and delete it.
  - Stored values can no longer close or forge capsule markers (`</memty_state>`, `<slots>`, `[/Memty]`, ...), so text saved from one chat can't inject instructions into the next assistant's context.

- **Memty is a memory layer, not a model router.** Removed:
  - the model-routing SDK and multi-provider chat client: `memty models`, `route`, `chat`, `integration`, `router-mcp`, the `memty-router-mcp` script, and `load_client`, `Memty`, the provider adapters and `SmartRouter` from `from memty import ...`
  - the `nexorai` alias package
  - the routing modules in `memoryport` (`sdk`, `sdk_cli`, `sdk_mcp`, `router`, `embeddings`)

  `memty init` no longer writes `~/.memty/models.json`. It now bootstraps the current project, the same as `memty scan`. `import memty` no longer loads `memoryport`. The older temporal vault (`memty-api`, `memty vault`, `memty vault-mcp`) stays for the `memory-vault` Docker service.

- **Package reorganized into folders by job:** `vault/`, `context/`, `extraction/`, `trust/`, `runtime/`, `integrations/` (`mcp/`, `browser/`), `routing/` and `legacy/`. See "Code layout" in the README.
  - The privacy gate now has its own module, `context/privacy.py`.
  - Commands, console scripts and the public `from memty import ...` API are unchanged.
  - Breaking for deep imports: module paths changed. For example, `memty.ledger` is now `memty.vault.ledger`, `memty.daemon` is now `memty.runtime.daemon`, and `memty.web_bridge` is now `memty.integrations.browser.bridge`. The bundled extension moved to `memty/integrations/browser/extension/`.
  - After upgrading, run `memtyd stop` once so the daemon restarts from its new module path.

- **Trust control plane.**
  - `memty scan` (alias `memty init`) bootstraps project facts from `pyproject.toml`, `package.json`, `Cargo.toml`, `Dockerfile` and `.env.example` without a model. Env templates contribute key names only. Facts are saved as `EXTRACTED`, so confirmed and deleted slots are never touched.
  - The new MCP tool `memty_propose` saves new agent-learned facts as `EXTRACTED`. Changes to existing facts are queued for `memty inbox`, `memty approve` and `memty reject`.
  - Context receipts: recall, clip, MCP and browser capsules record counts and slot names, never values, and increment per-fact `hit_count`. `memty receipts` lists them and `memty report` summarizes capsules served, verified facts reused, an estimate of tokens saved, and SECRET slots protected.
  - Ledger schema v2 adds the `fact_proposals`, `fact_usage` and `context_receipts` tables. Existing vaults are upgraded in place.

- `memty daemon` starts the shared vault daemon and local browser bridge together, checking that an existing bridge uses the same vault and user.
- Browser reviews suggest namespaces found in the selection and allow choosing or creating a project before saving; fact titles prefer acronyms and identifiers.
- Added a reproducible synthetic token payload benchmark and an optional live provider measurement runner.
- Save each reviewed browser selection as an independent context, and choose a context from a newest-first list before pasting its numbered facts.
- Preserve prose alongside lists, split long proposed facts without cutting words, show the original selection and known limits during review, and report when a capsule omits saved facts.
- Fixed dragging the browser extension pill when the ChatGPT prompt changes position or size, with touch support and saved positions that remain in view after resizing.
- `memty connect` now supports Codex CLI and VS Code through their official MCP installer commands, alongside Claude, Cursor, and Windsurf.
- The stdio MCP server now exposes `memty_drill` for bounded archived-source reads with a local-model-only gate.
- `memty_sync` can save up to 25 explicitly requested slot/value pairs and return the updated capsule in one call.
- Documented that MCP resource registration does not force clients to load memory automatically; clients must call `memty_sync` or read the resource.

## 0.2.0 (2026-11-05)

Brings Memty to web assistants (ChatGPT, Claude.ai, Gemini, Perplexity) and puts you in control of every fact.

### Added
- **Browser extension bundled in the package.** `memty extension` installs the Memty Bridge folder (Chrome, Edge, Brave) at `~/.memty/browser-extension`, and `--open` opens it.
  - **⚡ Memty / Alt+M** adds your facts to the prompt.
  - **Select text → ＋ Save to Memty** proposes atomic facts that you edit before saving.
  - The pill is draggable, and each site remembers its position.
  - New logo icons for light and dark toolbars.
- **Your Memty facts page:** view, search, edit, add, delete, and mark facts private, from the ☰ button or the extension icon.
- **Localhost web bridge (`memty serve`)**, bound to 127.0.0.1 only. Routes: `/capsule`, `/extract`, `/facts`, `/facts/update`, `/facts/delete`, `/namespaces` (with counts), `/pair`, `/health`.
- **Zero-setup pairing.** The extension pairs itself with trust on first use: only one extension origin is accepted, and `--new-token` resets it. It also picks a default namespace on its own. `memty pair` connects another browser or a reinstalled extension.
- **Login autostart.** `memty serve --autostart` and `--no-autostart`: a per-user item on Windows, macOS, and Linux, with no admin rights needed.
- **`memty clip`** copies a capsule to the clipboard for any AI app.
- **Welcome screen.** Running `memty` with no command shows a short introduction and the main commands.
- **Local fact extraction** from chat answers:
  - Uses built-in rules by default, or a local Ollama model when `MEMTY_OLLAMA_MODEL` is set.
  - Skips headings and pasted capsules.
  - Groups file paths into one fact.
  - Summarizes code blocks in one line instead of storing code.

### Changed
- **Plain capsule format.** Capsules for chat assistants and the clipboard are now plain `Title: value` lines. `format=xml` and `--format xml` keep the `<memty_state>` block. MCP and `memty recall` are unchanged.
- **Newest facts first.** Without a query, the newest facts come first, so a fact saved a minute ago is never pushed out by older ones. Web capsules use up to 350 tokens.
- **Reviewed saves are confirmed.** Facts you review and save in the extension are stored as user-confirmed and keep their existing privacy level.
- **`memty connect` is safer.** It never writes another application's settings file. Claude Code and Cursor are connected through their official installers, and Claude Desktop and Windsurf get printed instructions.

### Fixed
- Chats no longer stutter while answers stream: the extension stopped re-measuring the page on every scroll.
- "Extension context invalidated" after an update: stale copies remove themselves, and open tabs get the new version.
- Requests time out with a clear message instead of hanging the chat.
- On Windows, oversized requests sometimes reset the connection before the "413 Request Entity Too Large" reply arrived.
- Snake_case names such as `logical_constraints` are kept intact in extracted facts.

## 0.1.1

- Bug fixes for the atomic vault, CLI, and MCP bridge.

## 0.1.0

- First release: an atomic-fact SQLite vault with versioning, tombstones, and namespace rules; a context compiler under 600 tokens with a privacy gate (SECRET routing and CONFIDENTIAL redaction); a shared `memtyd` daemon; the CLI; and the MCP server (`memty_sync`, `memty://capsule/{namespace}`).
