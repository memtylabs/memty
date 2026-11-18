# Python API

Install Memty into the Python environment running your program. The [examples folder](../examples/README.md) contains complete, runnable programs using temporary vaults.

```python
from pathlib import Path
from memty import open_ledger

vault = open_ledger(path=Path("my-vault.sqlite3"))
try:
    vault.record("demo.project", "editor", "VS Code",
                 verification_state="USER_CONFIRMED")
    result = vault.context("editor", provider="openai",
                           namespace="demo.project", strict_namespace=True)
    print(result["text"])
finally:
    vault.close()
```

The path in this snippet is persistent and relative to the current directory. For your normal vault, `open_ledger()` uses the default path and user. Do not open a real vault in examples you do not trust.

## Privacy in application code

Specify the destination provider accurately. Catch `LocalRoutingRequired` for eligible secret facts. `result["text"]` is the compiled capsule; `result["redactions"]` can contain confidential originals, so never send the complete result to a remote model. Metadata and errors can also contain namespace and slot names. The privacy filter applies when compiling; it does not control what your application does with `record`, `find`, `list`, raw sources, logs, or other direct vault reads.

```python
from memty import LocalRoutingRequired

try:
    result = vault.context("client", provider="openai",
                           namespace="demo.project", strict_namespace=True)
except LocalRoutingRequired:
    print("This request needs a local model.")
else:
    print(result["text"])  # Inspect before sharing.
```

In this second snippet, `vault` is the open ledger from the first example; run it before the `finally` block closes the ledger. Alternatively run [privacy_demo.py](../examples/privacy_demo.py), which is self-contained.

## Useful methods

`record` saves a fact; `find`, `list`, and `history` inspect it. `forget(namespace, slot, purge_raw=True)` tombstones a fact and attempts to remove its unused linked raw source. `propose` and `proposals` support agent suggestions; `resolve_proposal(id, approve=True)` approves a pending proposal. `archive_raw` and `drill_down` explicitly manage source text. See [memory commands](memory-and-commands.md) and [privacy](privacy.md) for limitations.

For strict namespace selection use `strict_namespace=True`; the default compiler can consider related namespaces. Close the ledger when finished to release database connections.
