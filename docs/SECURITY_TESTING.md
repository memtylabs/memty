# Testing Memty's security and privacy yourself

Memty makes a few promises: SECRET facts never leave your computer, private values reach cloud AIs only as `[private]`, web pages can't read your vault, and a forgotten fact is really gone. This guide shows how to check each promise yourself, first with the automated attack suite and then by hand.

> **Version note:** the fixes these tests check are on `main` and ship in the first release after 0.2.0. Some of the attacks below succeed against 0.2.0. Run the tests from a clone of `main`, or upgrade once the next release is out.

## 1. Run the automated attack suite

[`tests/test_memty_security.py`](../tests/test_memty_security.py) holds 61 adversarial tests. Each one picks a Memty promise and tries to break it. If a test fails, that's a vulnerability.

**Set up once** (Python 3.10 or newer):

```shell
git clone https://github.com/memtylabs/memty.git
cd memty
python -m venv .venv
```

Activate the environment and install Memty from the clone:

| Shell | Commands |
| --- | --- |
| Windows PowerShell | `.\.venv\Scripts\Activate.ps1` then `pip install -e .` |
| macOS / Linux | `source .venv/bin/activate` then `pip install -e .` |

**Run the suite:**

```shell
python -m unittest tests.test_memty_security -v
```

You should see `Ran 61 tests ... OK`. On Windows, one test (`test_endpoint_file_is_owner_only`) is skipped because it checks POSIX file permissions.

**Run one area at a time:**

| Area | What it attacks | Command |
| --- | --- | --- |
| Privacy gate | SECRET, CONFIDENTIAL and INTERNAL facts against every cloud provider, look-alike "local" provider names, Unicode tricks, allow and block lists, steered relevance scores | `python -m unittest tests.test_memty_security.PrivacyGateTests -v` |
| Prompt injection | Stored values that try to close or forge the capsule markers (`</memty_state>`, `[/Memty]`) | `python -m unittest tests.test_memty_security.CapsuleFramingTests -v` |
| Credentials | API keys, tokens, JWTs, private keys and passwords saved as "public" must become SECRET; ordinary facts must not | `python -m unittest tests.test_memty_security.CredentialTests -v` |
| Forget | A forgotten value must be gone from every table, the search index, and the raw bytes of the database file | `python -m unittest tests.test_memty_security.ForgetTests -v` |
| Injection | SQL and full-text-search syntax, path traversal, and oversized input | `python -m unittest tests.test_memty_security.InjectionTests -v` |
| Browser bridge | Network reach, DNS rebinding, web-page origins, forged or near-miss tokens, pairing by a second extension, provider spoofing, declassifying secrets, malformed bodies, request logs | `python -m unittest tests.test_memty_security.BridgeSecurityTests -v` |
| Daemon | Wrong tokens, calling internal methods, malformed messages, bypassing validation | `python -m unittest tests.test_memty_security.DaemonSecurityTests -v` |
| MCP | SECRET recall, drill-down into archived source text, agents overwriting or downgrading facts | `python -m unittest tests.test_memty_security.MCPSecurityTests -v` |
| Receipts | Usage receipts must never store fact values | `python -m unittest tests.test_memty_security.ReceiptTests -v` |

**Run the whole test suite** to confirm nothing else broke:

```shell
python -m unittest tests.test_memty_security tests.test_memty_week1 tests.test_memty_week2 tests.test_memty_week3 tests.test_memty_week4 tests.test_memty_trust tests.test_memty_welcome tests.test_memty_daemon_command tests.test_memty_benchmark
```

## 2. Try the attacks by hand

These steps use a throwaway vault, so your real `~/.memty` vault is never touched.

### Set up a test vault

Windows PowerShell (run everything in the same window):

```powershell
$db = "$env:TEMP\memty-sec\ledger.sqlite3"
New-Item -ItemType Directory -Force "$env:TEMP\memty-sec" | Out-Null
function m { python -m memty --db $db @args }
```

macOS / Linux:

```shell
export db="${TMPDIR:-/tmp}/memty-sec/ledger.sqlite3"; mkdir -p "$(dirname "$db")"
m() { python -m memty --db "$db" "$@"; }
```

Add some facts:

```shell
m remember work.project editor "VS Code"
m remember work.project db_password "hunter2-xyz" --sensitivity SECRET
m remember work.project client "Acme BLUEFIN" --sensitivity CONFIDENTIAL
```

### Credentials are always SECRET

```shell
m remember work.project openai_key "sk-proj-4fG7hJ2kL9mN3pQ8rS1tU6vW0xY5zA2bC7dE"
m remember work.project wifi "password: Tr0ub4dor&3"
m remember work.project rule "Rotate the API key monthly"
```

**Expected:** the first two print `"sensitivity": "SECRET"` even though you didn't ask for it. The third stays `PUBLIC` because it only mentions a key.

### The privacy gate

```shell
m recall "db password" --namespace work.project --provider openai
m recall "client" --namespace work.project --provider openai
m recall "db password" --namespace work.project --provider ollama
```

**Expected:**
1. The first is refused with "local routing required", and the secret isn't printed.
2. The second shows the client as redacted.
3. The third shows everything, because `ollama` is a local model on your computer.

### Forget means forget

```shell
m remember work.project codename "zqxj-erase-me-7731"
m forget work.project codename --purge-raw
python -m memty.runtime.daemon stop --db "$db"
python -c "import pathlib,sys; d=pathlib.Path(sys.argv[1]); print(any(b'zqxj-erase-me' in p.read_bytes() for p in d.parent.glob(d.name+'*') if p.is_file()))" "$db"
```

**Expected:** `False`. The value isn't anywhere in the database files on disk.

### Attack the browser bridge

Start a bridge for the test vault in a **second terminal**:

```shell
python -m memty --db "<the same db path>" serve --port 8799
```

Back in the first terminal, get the token. In PowerShell, use `curl.exe`, not `curl`.

```powershell
$token = (m serve --show-token).Trim()
$ext = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"
$base = "http://127.0.0.1:8799"
```

```shell
# macOS / Linux
token=$(m serve --show-token | tr -d '[:space:]')
ext="chrome-extension://abcdefghijklmnopabcdefghijklmnop"
base="http://127.0.0.1:8799"
```

Each attack and the answer you should get:

| Attack | Command | Expected |
| --- | --- | --- |
| Claim to be a local model to get SECRET facts | `curl.exe -s -H "Origin: $ext" -H "Authorization: Bearer $token" "$base/capsule?namespace=work.project&provider=ollama&query=db%20password"` | `400`, no secret |
| Ask for a SECRET fact normally | `curl.exe -s -H "Origin: $ext" -H "Authorization: Bearer $token" "$base/capsule?namespace=work.project&query=db%20password"` | `409 local_routing_required`, no secret |
| Call the bridge from a web page | `curl.exe -s -H "Origin: https://evil.example" -H "Authorization: Bearer $token" "$base/facts?namespace=work.project"` | `403` |
| DNS rebinding (forged Host header) | `curl.exe -s -H "Host: evil.example:8799" -H "Origin: $ext" -H "Authorization: Bearer $token" "$base/facts?namespace=work.project"` | `403` |
| Wrong token | `curl.exe -s -H "Origin: $ext" -H "Authorization: Bearer wrong" "$base/facts?namespace=work.project"` | `401` |
| List facts | `curl.exe -s -H "Origin: $ext" -H "Authorization: Bearer $token" "$base/facts?namespace=work.project"` | Private facts show `"value": null` |
| Form-style write, as a CSRF attempt would send | `curl.exe -s -X POST -H "Origin: $ext" -H "Authorization: Bearer $token" -H "Content-Type: text/plain" --data "x" "$base/facts"` | `415` |

On macOS and Linux, use `curl` and `$token` / `$ext` / `$base` the same way.

To check that the browser can't make a secret public:

```powershell
curl.exe -s -X POST -H "Origin: $ext" -H "Authorization: Bearer $token" -H "Content-Type: application/json" `
  --data '{\"namespace\":\"work.project\",\"slot\":\"db_password\",\"private\":false}' "$base/facts/update"
```

```shell
curl -s -X POST -H "Origin: $ext" -H "Authorization: Bearer $token" -H "Content-Type: application/json" \
  --data '{"namespace":"work.project","slot":"db_password","private":false}' "$base/facts/update"
```

**Expected:** `400`, "a secret can only be made public from the terminal".

### Clean up

Stop the bridge with Ctrl+C, then:

```shell
python -m memty.runtime.daemon stop --db "$db"
```

Then delete the test folder: `Remove-Item -Recurse -Force "$env:TEMP\memty-sec"` (PowerShell) or `rm -rf "$(dirname "$db")"` (macOS/Linux).

## What these tests don't cover

These are design limits, not bugs, and the tests don't claim otherwise:

- **Pairing is trust on first use.** The first browser extension that asks gets the token. Run `memty serve --new-token` to reset it.
- **The vault file isn't encrypted.** Any program running as your user can read `~/.memty`.
- **Credential detection uses patterns.** It catches common key formats and `password: ...` lines, not a password written as ordinary words. Mark those facts SECRET yourself.
- **Your terminal is trusted.** `memty remember ... --sensitivity PUBLIC` can deliberately make a secret public.

Found a way past one of these protections? Please report it privately to the maintainers instead of opening a public issue.
