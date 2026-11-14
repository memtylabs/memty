# Security policy

Memty keeps your AI memory on your own computer, so its security promises matter: SECRET facts never leave your device, private values reach cloud AIs only as `[private]`, web pages can't read your vault, and a forgotten fact is really gone.

## Supported versions

Security fixes go into the latest release only. Please upgrade before reporting.

| Version | Supported |
| --- | --- |
| Latest 0.x release | ✅ |
| Older releases | ❌ |

```shell
pip install --upgrade memty
```

## Reporting a vulnerability

**Please don't open a public issue for a security problem.** Report it privately through GitHub instead:

1. Go to [Report a vulnerability](https://github.com/memtylabs/memty/security/advisories/new) (the **Security** tab → **Report a vulnerability**).
2. Describe what you found, how to reproduce it, and which version you used (`pip show memty`).
3. Use a throwaway vault and fake data in your report. Never include your real facts or tokens.

We aim to acknowledge reports within 3 days and to ship a fix for confirmed issues as soon as we can, usually within 14 days. We'll credit you in the changelog unless you'd rather stay anonymous.

**In scope:**
- the privacy gate: SECRET, CONFIDENTIAL and INTERNAL facts, and provider allow and block lists;
- the browser bridge (`memty serve`) and the browser extension;
- the daemon (`memtyd`) and the MCP server;
- forget and purge;
- credential detection;
- context receipts.

**Out of scope** (known design limits):
- anything that needs another program already running as your user account (the vault file isn't encrypted);
- the first browser extension to pair is trusted;
- passwords written as ordinary words aren't detected as credentials.

## Verifying a release

Every release from 0.2.1 on is built and published by [GitHub Actions](.github/workflows/publish.yml) using PyPI Trusted Publishing, with no API tokens. Each file carries a provenance attestation that links it to the exact commit and workflow run that built it. You can see this on the **Verified details** panel of the [PyPI page](https://pypi.org/project/memty/), or check it yourself:

```shell
pip download memty --no-deps -d memty-dist
python -m pip install pypi-attestations
pypi-attestations verify pypi --repository https://github.com/memtylabs/memty memty-dist/*.whl
```

## Testing the protections yourself

The repository has an adversarial test suite that attacks each promise above. See [docs/SECURITY_TESTING.md](docs/SECURITY_TESTING.md).
