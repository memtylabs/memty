# Troubleshooting and maintenance

## Installation and command problems

- **`memty` is not recognized:** install and run it with the same interpreter: `python -m pip install memty` then `python -m memty --version`. On Windows try `py -m pip install memty` and `py -m memty --version`.
- **Wrong version or missing feature:** check `memty --version`, `python -m pip show memty`, and `memty COMMAND --help`. The guides describe the current checkout; some features are planned for the unreleased 0.2.2 candidate.
- **Different facts in different apps:** verify that they use the same vault path and user. Defaults are `~/.memty/ledger.sqlite3` and `local`; environment overrides are `MEMTY_VAULT_PATH` (or `MEMTY_DB`) and `MEMTY_USER`.

## Browser and MCP

- **No pill:** verify the supported website, that the unpacked extension is enabled, and reload the page. Website layouts can change; select text manually if automatic answer selection fails.
- **Bridge not connected:** run `memty serve --background`, then retry. For another browser or a reinstalled extension run `memty pair` and retry within the window. For diagnostics, stop the background bridge and run `memty serve` in a terminal; it binds to `127.0.0.1`, normally port 8765. Check for a port conflict. Avoid sharing tokens or private values in logs.
- **MCP client does not use memory:** run `memty connect --dry-run`, inspect its output, connect the intended client, and restart it if necessary. Ask the agent to call `memty_sync` for the correct namespace. Client registration does not force automatic recall.
- **A capsule is empty or refuses a request:** check the namespace, provider, sensitivity and provider lists. SECRET facts may require local routing. Size budgets and selected context can omit facts. Do not set a cloud destination to `local` merely to bypass the privacy gate.

## Upgrade

```sh
python -m pip install --upgrade memty
memty --version
memtyd stop
memty extension
```

Reload the extension in the browser's extensions page, and restart the browser bridge if it is running so it uses the upgraded package. Start it again with `memty serve --autostart` if desired. `pip install --upgrade` installs the latest published release, not an unreleased candidate. Review the [changelog](../memty/CHANGELOG.md) for version-specific instructions.

## Back up and restore

First stop the bridge and daemon and close programs using the vault. Make a protected backup of the vault using a SQLite-consistent backup method; preserve the correct user and path. A live SQLite database can have uncheckpointed WAL data, so copying only the `.sqlite3` file while it is in use is not a reliable backup. Test restoration to a separate path with `memty --db PATH list` before relying on it. Backups can contain private facts and older deleted values; encrypt and manage them accordingly.

## Uninstall

Run `memty serve --no-autostart`, `memtyd stop`, and `python -m pip uninstall memty`, then remove the browser extension in the browser. Uninstalling the package does **not** remove the vault, its sidecar files, or backups. Delete those separately only if you intend to permanently discard them.
