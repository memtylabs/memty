# Maintainer guide: publishing Memty to PyPI

This guide is for project maintainers. Publishing is public and a published file cannot be replaced with a different file under the same name and version.

## Before publishing 0.2.2

Review the changes and license, update the changelog and user guides to reflect the actual release, and commit and merge the intended source. Run the tests and verify the browser integration test on a suitable runner. The browser test timed out in the local preparation environment; the release workflow includes that check. Check that PyPI still has no 0.2.2 release, and review the [draft release notes](../memty/CHANGELOG.md).

The repository's [publishing workflow](../.github/workflows/publish.yml) can test, build, and publish a GitHub release using PyPI Trusted Publishing if the PyPI publisher and GitHub `pypi` environment are configured correctly. That setup has not been verified for this release. Do not use both the workflow and a manual upload for the same files. See [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/).

## Manual upload from Windows PowerShell

Use these steps only after the checks above pass and you intend to publish directly. A manual Twine upload is not the GitHub Trusted Publishing workflow and does not automatically provide its provenance attestations. The user running the commands needs a PyPI account with permission to publish `memty` and an API token scoped to that project. Create or manage a token in [PyPI account settings](https://pypi.org/manage/account/). Keep the `pypi-` token private and never paste it into chat, source code, a command, or a GitHub issue.

Open PowerShell at the intended, reviewed checkout:

```powershell
cd "C:\Users\ASUS\OneDrive\Desktop\OpenAI"
py -m pip install --upgrade build twine
```

If `py` is unavailable, use the Python interpreter that has Memty's build tools installed instead. Build into a new, timestamped directory so old distributions cannot accidentally be uploaded:

```powershell
$releaseDir = Join-Path (Get-Location) ("release-0.2.2-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
New-Item -ItemType Directory -Path $releaseDir -ErrorAction Stop | Out-Null
py -m build --outdir $releaseDir
```

Stop if the build fails. Inspect the output: it should contain exactly the two version 0.2.2 files below. Then check both explicitly:

```powershell
$wheel = Join-Path $releaseDir "memty-0.2.2-py3-none-any.whl"
$source = Join-Path $releaseDir "memty-0.2.2.tar.gz"
Get-Item $wheel, $source
py -m twine check --strict $wheel $source
```

Stop if either file is missing or the check fails. After reviewing the exact files and deciding to publish, use the following in the **same PowerShell session**:

```powershell
$env:TWINE_PASSWORD = $null
$env:TWINE_USERNAME = $null
$env:PYTHON_KEYRING_BACKEND = "keyring.backends.null.Keyring"
py -m twine upload --repository-url https://upload.pypi.org/legacy/ --username __token__ $wheel $source
```

When Twine prompts for a password, paste the complete PyPI token there and press Enter. The prompt may not show the characters. If Twine reports an error, stop and read it before retrying: 403 usually indicates insufficient account or token permissions; an existing filename cannot be replaced. If only one file was uploaded, inspect the [release files on PyPI](https://pypi.org/project/memty/) before taking further action. Do not use `--skip-existing` to hide an unexpected duplicate.

After success, check the version, README, license, and both files at [PyPI](https://pypi.org/project/memty/). Test an installation in a clean environment and publish matching release notes and source. Do not claim Trusted Publishing or provenance unless the PyPI file details show them.
