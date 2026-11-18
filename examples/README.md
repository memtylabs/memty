# Memty Python examples

These examples use fictional values and create temporary SQLite vaults. They do not read or modify your default Memty vault, call an AI service, or require an API key. The temporary directory is cleaned up when each script finishes.

Install Memty first (`python -m pip install memty`), or from the repository root install the current checkout (`python -m pip install -e .`). Then, from the repository root:

```sh
python examples/basic_memory.py
python examples/privacy_demo.py
python examples/proposals.py
```

| Example | Demonstrates |
| --- | --- |
| [basic_memory.py](basic_memory.py) | Save, recall, update, inspect history, and forget a fact |
| [privacy_demo.py](privacy_demo.py) | Confidential redaction and refusal to route a secret to a cloud provider |
| [proposals.py](proposals.py) | Queue a change to an existing fact and approve it |

For persistent application data, pass your chosen path to `open_ledger(path=...)` instead of a temporary path, and protect that unencrypted file. Do not send a full `context()` result to an AI provider: the `redactions` mapping can contain confidential originals. See the [Python API guide](../docs/python-api.md) and [privacy guide](../docs/privacy.md).
