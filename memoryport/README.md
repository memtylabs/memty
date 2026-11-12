# memoryport: the older temporal vault

This package holds Memty's previous, event-sourced memory vault. It is kept for one reason: the `memory-vault` service in [`compose.yaml`](../compose.yaml) runs its HTTP API (`memty-api`, built from [`Dockerfile.vault`](../Dockerfile.vault)) for the web workspace.

New local memory lives in [`memty`](../memty/README.md): one SQLite vault, one daemon (`memtyd`), MCP for desktop and CLI agents, and the browser extension. To bring old facts across, run:

```shell
memty migrate ~/.memty/memory.sqlite3
```

The older vault's entry points are still available:

```shell
memty-api          # HTTP API used by the memory-vault container (needs the [server] extra)
memty vault ...    # its CLI
memty vault-mcp    # its MCP server
```

Model routing and the multi-provider chat SDK that used to live here have been removed. Memty is a memory layer, not a model router.
