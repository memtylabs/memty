# Contributing to Memty

Thanks for helping improve Memty. The project has a Next.js app, an Express/MongoDB service, provider adapters, and an optional Python memory package. A focused change with a clear reproduction or outcome is easiest to review.

## Find the right area

| Change | Guide |
| --- | --- |
| Pages, chat UI, API routes, responsive behavior | [Frontend guide](app/README.md) |
| Authentication, sessions, REST endpoints, persistence | [Backend guide](backend/README.md) |
| Provider adapters, model registry, fallbacks | [Provider guide](providers/README.md) |
| Memory retrieval and dashboard behavior | [Memory guide](app/memory/README.md) |
| Python vault, daemon, CLI, MCP, or browser bridge | [Memty guide](memty/README.md) |

## Before you start

1. Search existing [issues](https://github.com/memtylabs/memty/issues) and pull requests to avoid duplicating work.
2. For a bug, include the route or command, steps to reproduce, expected result, actual result, and relevant sanitized logs.
3. For a feature, describe the user problem and a concrete acceptance outcome before expanding its scope.
4. For changes that affect account data or provider requests, explain which service owns the data and how user/account boundaries are preserved.

## Choosing an issue

Use the [open issue tracker](https://github.com/memtylabs/memty/issues) to find a task. Difficulty describes the expected scope, not the contributor's experience:

| Label | Typical scope |
| --- | --- |
| `difficulty: easy` | A focused, well-bounded change with a clear way to verify it; often suitable for a first contribution. |
| `difficulty: intermediate` | A change spanning multiple behaviors or requiring investigation and regression coverage. |
| `difficulty: hard` | A cross-component, security-sensitive, architectural, or data-migration change with significant design and testing needs. |

Area labels distinguish the browser extension, Python vault, benchmark, and web workspace. `priority: high` highlights important reliability, security, or evaluation work; it does not imply that other issues are invalid. `needs verification` means that a reported behavior or its current scope still needs reproduction; it does not mean a fix has been confirmed. `roadmap` identifies optional or larger proposals that need design decisions and should not be treated as promises or small standalone tasks. Existing type labels such as `bug`, `documentation`, and `enhancement` describe the kind of work. `good first issue` marks a particularly approachable issue.

Read the acceptance criteria and existing discussion before starting. If the problem is unclear, describe what you checked and ask on the issue. For a large issue, propose a focused first step before investing in a broad implementation. Comment when you start so others can coordinate, and link the issue in your pull request. Difficulty and scope may change as maintainers and contributors learn more.

Do not assume that a closed pull request was merged: check its merge status and the current default branch. The older web workspace and the local Python package are separate areas; a fix in one does not automatically fix the other.

## Local setup

Follow the [root README](README.md) web workspace section for frontend and backend setup. The Python package and its optional extras have separate instructions in [Memty](memty/README.md). You only need the services involved in your change; provider keys are optional unless the behavior depends on a live provider.

## Pull request checklist

- Keep the change focused and explain the user-visible result in the PR description.
- Update the relevant guide when a route, setting, supported flow, or limitation changes.
- Include before/after screenshots for visible UI changes and mention tested viewport sizes.
- Run the checks relevant to the files you changed; list the commands and results in the PR.
- Do not commit `.env` files, API keys, session secrets, personal data, or real user conversations.
- Call out migration, configuration, compatibility, or security implications.

## Testing by area

Run the checks relevant to your change from the repository root and report the result or any blocker in the pull request. Use a dedicated test vault and synthetic facts; never test destructive behavior against your real vault.

```shell
# Python vault, CLI, bridge, and benchmark tests (use a virtual environment)
python -m pip install -e .
python -m unittest discover -s tests -p 'test_memty*.py'

# Browser extension checks (Node.js and a local Chrome or Chromium installation required)
npm ci
npm run test:extension
```

For browser changes, state which websites and browsers you actually checked; local fixtures do not prove compatibility with live third-party sites. For benchmark work, distinguish estimated tokens from provider-reported usage, identify the fixture and models, include full methodology, and do not generalize from a single task or simulated baseline. Live provider tests may cost money and are optional unless needed for the specific change; never put keys or real conversations in results. For the web workspace, consult the relevant frontend or backend guide and report the checks you ran.

## Documentation and issue reports

Use relative links for files inside the repository. Keep examples runnable and use placeholders for secrets. When reporting a problem, never attach credentials, session cookies, full private prompts, or user memory contents; reduce logs to the smallest sanitized excerpt that demonstrates the failure.

