# Memory and command reference

## Facts and namespaces

A fact has a namespace, a slot, and a value. Namespaces such as `work.project` and `personal` help organize facts. Slots identify facts within a namespace. Saving the same slot explicitly updates it and keeps its history.

```sh
memty remember work.project database "PostgreSQL 16"
memty remember work.project database "PostgreSQL 17"
memty list --namespace work.project
memty history work.project database
memty recall "Which database?" --namespace work.project --provider openai
memty clip work.project --print
memty stats
```

Recall normally considers related namespaces as well. A namespace argument is not a strict isolation boundary for the CLI `recall` command; inspect the output. The MCP capsule and browser routes use strict namespace selection. Recall's default provider is `local`: explicitly select the destination for anything you intend to share.

## Delete and archive

```sh
memty forget work.project database
memty forget work.project database --purge-raw
memty list --namespace work.project --all
```

The first command removes the active fact's value and history and leaves a tombstone that prevents automatic restoration. Use the second form _instead of the first_ when you also want Memty to purge its linked raw source if it is no longer used by another fact. If the fact is already tombstoned, repeating the command with `--purge-raw` does not perform that cleanup. Separately archived sources, shared sources, backups, exported copies, and content already sent to other services can remain. With the 0.2.2 candidate, forgetting also removes that namespace's stored summary. See [privacy](privacy.md).

`memty raw-add NAMESPACE "text"` archives text and returns an ID; `memty raw-get ID` explicitly reads it. Raw sources are separate from normal capsule output and may contain sensitive material.

## Project scan, proposals, and activity

```sh
memty scan --dry-run
memty scan . --namespace project.example
memty inbox
memty approve 1
memty reject 2
memty receipts
memty report --days 7
```

Replace `1` and `2` with actual proposal IDs. Scan uses supported project manifests and `.env.example`; it records environment key names rather than their values and does not read a real `.env`. Scan results are extracted facts, not user-confirmed facts. Agents can add new extracted facts, but proposed changes to existing facts wait for review. Receipts contain metadata such as slot names and counts, not fact values. Token savings are estimates, not billing data.

## More commands

| Command                                        | Purpose                                                                                         |
| ---------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `memty summary NS`                             | Read or generate a namespace summary; `--set "text"` replaces it. Treat summaries as sensitive. |
| `memty rule`, `rules`, `rule-delete`           | Store, list, and delete logical namespace rules. See each command's `--help`.                   |
| `memty migrate PATH`                           | Import from an older temporal vault; make a backup first.                                       |
| `memty serve`, `pair`, `extension`             | Manage the browser bridge and extension.                                                        |
| `memty connect`                                | Configure supported MCP clients.                                                                |
| `memtyd status`, `memtyd start`, `memtyd stop` | Control the shared daemon.                                                                      |

Run `memty --help` and `memty COMMAND --help` for all flags. Global options such as `--db`, `--user`, and `--trusted-provider` go **before** the command, for example `memty --db /path/to/vault.sqlite3 list`. The CLI also exposes legacy vault commands; they are separate from the main atomic-fact workflow.
