# Getting started

## 1. Install

Memty requires Python 3.10 or newer on Windows, macOS, or Linux. In a terminal:

```sh
python -m pip install memty
memty --version
```

On Windows, if `python` or `memty` is not available, try `py -m pip install memty` and `py -m memty --version`. You can substitute `py -m memty` for `memty` in the examples below. Use the same Python environment to install and run Memty.

To try the unreleased repository version instead, open a terminal at the repository root and run `python -m pip install -e .`. This installs the current checkout, which may differ from PyPI.

## 2. Save and recall a fact

```sh
memty remember demo.project editor "VS Code"
memty list --namespace demo.project
memty recall "Which editor do I use?" --namespace demo.project --provider openai
```

`demo.project` is a namespace, `editor` is a slot, and `VS Code` is its value. Use your own names and short facts. A fact value is limited to 40 estimated tokens.

The example asks for a cloud-provider view. **`memty recall` defaults to the local provider**, which can include local-only facts. Choose the actual destination with `--provider` before sending a result elsewhere. CLI recall returns JSON; send only the reviewed `text` field, never the entire result, because the `redactions` mapping can contain private values. See [privacy](privacy.md).

## 3. Choose where to use it

- For chat websites, follow the [browser guide](browser.md).
- For Claude Code, Codex, Cursor, VS Code, Windsurf, or another MCP client, follow [MCP setup](mcp.md).
- For any app, use `memty clip demo.project --print` to inspect a provider-filtered capsule; remove `--print` to copy it.
- For code, try the [Python examples](../examples/README.md).

By default the vault is `~/.memty/ledger.sqlite3`. It is not encrypted. Do not put secrets in examples or share the vault, its backups, or its pairing token. Learn about [privacy and storage](privacy.md).
