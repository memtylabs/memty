# Coding agents and MCP

The Model Context Protocol (MCP) lets a compatible client call Memty tools through a local server. Installing Memty does not force a client to load memory automatically.

## Connect a client

Install Memty in an environment that the client can access, then run:

```sh
memty connect --dry-run
memty connect
```

Review the output. To connect a single client, for example, use `memty connect --client "Codex CLI"`. Other accepted names are `Claude Desktop`, `Claude Code`, `VS Code`, `Cursor`, and `Windsurf`. Memty uses supported client installers where available and prints manual steps where needed. Follow the client's prompts and restart it if needed. If the dry run reports an error, resolve the client setup before retrying.

Ask the agent: “Use `memty_sync` to recall the `demo.project` namespace before answering.” The client must support and enable MCP tools. A registered resource alone does not guarantee that the client reads it.

## Available tools

| Tool | Purpose |
| --- | --- |
| `memty_sync` | Recall a namespace; on explicit request, remember or forget a slot, or save a batch of up to 25 slots. |
| `memty_propose` | Suggest a learned fact. New slots are saved as extracted; changes to existing or deleted slots go to the inbox. |
| `memty_drill` | Read a bounded excerpt of an archived source for a slot, only when configured for a local provider. |

Review proposed changes with `memty inbox`, then `memty approve ID` or `memty reject ID`. Check the actual IDs shown; they are not list positions.

MCP defaults to provider `mcp`, treated as a cloud destination. `MEMTY_PROVIDER` configures the provider for the MCP server process. Set a local provider only when the client and model that receive the output are genuinely local; a client may otherwise forward its tool results to a remote model. The provider setting is a trust decision, not proof of where the model runs. See [privacy](privacy.md).

For manual configuration, use the command and arguments printed by `memty connect --dry-run`; its server entry runs Python with `-m memty mcp`. Configure the same vault and user for every client with `MEMTY_VAULT_PATH` and `MEMTY_USER` if you override the defaults.
