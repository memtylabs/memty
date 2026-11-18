# Privacy and security

Memty's vault is local by default, but local storage and privacy filters are not the same as encryption or a guarantee about what an AI service does with text you send it. Review the output before sharing it.

## Sensitivity levels

| Level | Typical treatment for an untrusted cloud provider |
| --- | --- |
| `PUBLIC` | The value can be included. |
| `INTERNAL` | Omitted unless the provider is trusted or explicitly allowed. |
| `CONFIDENTIAL` | Replaced with a placeholder unless the provider is trusted or explicitly allowed. |
| `SECRET` | An eligible matching fact causes a local-routing refusal; its value is not included in the cloud capsule. |

Provider allow and block lists also affect eligibility. An explicitly allowed provider can receive confidential values, and a trusted provider can receive internal and confidential values. Make these choices deliberately. A provider identifier is a label supplied by the caller; Memty cannot verify where an AI model runs. Local provider labels, including `local` and `ollama`, can receive secrets.

```sh
memty remember demo.project client "Example client" --sensitivity CONFIDENTIAL
memty recall "client" --namespace demo.project --provider openai
```

**`memty recall` defaults to `local`.** Always specify the real destination provider before sharing its output. Python callers should transmit only the reviewed `result["text"]`: the full result includes a `redactions` mapping that may contain original confidential values. Do not send that mapping, logs, or full result to a cloud service. `memty clip` defaults to provider `clipboard` and renders private values as `[private]`.

Memty detects some credential patterns and marks matching facts `SECRET`, but detection is not exhaustive. Explicitly classify sensitive information, and avoid storing credentials when possible. Terminal commands can expose values through shell history and process listings.

The 0.2.2 candidate limits unclassified stored summaries to local providers and removes the namespace summary on a new forget operation. Older releases behave differently. Even in 0.2.2, existing summaries and other copies created before an upgrade may remain; inspect and handle them separately.

## Browser and MCP trust

The browser bridge listens on localhost and uses host/origin checks and a pairing token. Pairing uses trust on first use: the first extension to connect is trusted. Keep the token private; it grants access to bridge operations. To rotate it, run `memty serve --new-token`, restart the bridge, and pair trusted extensions again.

MCP clients default to the cloud-like `mcp` provider. Setting `MEMTY_PROVIDER` to a local name lets the MCP client receive local-only information; do so only if the client and the model it uses are genuinely local. An assistant can forward tool results elsewhere.

## Storage and deletion limits

The default vault `~/.memty/ledger.sqlite3` is **not encrypted**. Protect the operating-system account and device, and keep the vault out of synced folders unless you intend to upload it. SQLite may also use WAL and shared-memory files. Pairing tokens and daemon files live beside the vault. Backups, cloud-sync versions, disk snapshots, logs, exported text, and provider-side conversations are separate copies.

`memty forget NS SLOT` deletes the fact value and audit history and leaves a tombstone. For linked raw material, use `memty forget NS SLOT --purge-raw` on the first forget; shared or independently archived sources can remain. Browser deletion does not request raw-source purge. Database cleanup and WAL checkpointing are best effort when another connection is active; secure deletion on flash storage, backups, and snapshots cannot be guaranteed. Review [memory commands](memory-and-commands.md) before deleting.

Report suspected vulnerabilities privately using the [security policy](../SECURITY.md); do not include real tokens or private facts in reports. See [security testing](SECURITY_TESTING.md) to run the project's checks.
