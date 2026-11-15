# Frontend guide

This folder contains the Memty Next.js App Router UI, API routes, shared global styles, and route-level pages. Start the frontend from the repository root with `npm run dev`; it serves on port 3001 by default.

> **Frontend path:** browser → Next.js page/API route → provider adapter or private backend proxy. The root [README](../README.md) has the system diagram and full local setup.

| Want to... | Read |
| --- | --- |
| Understand model calls and provider fallback | [Provider and routing guide](../providers/README.md) |
| Change sign-in, sessions, or saved data | [Backend guide](../backend/README.md) |
| Change memory retrieval or dashboard behavior | [Portable memory guide](memory/README.md) |

## Where to make a frontend change

| Area | Files | Notes |
| --- | --- | --- |
| App routes | `page.tsx`, `login/`, `chatbot/`, `memory/`, `terms/`, `privacy/` | Route entry points and React pages. |
| Chat endpoint | `api/chat/route.ts` | Request validation, context orchestration, provider call, and persistence handoff. |
| Public model metadata | `api/config/route.ts` | Reports configured models without exposing provider secrets. |
| Landing page | `page.tsx`, `../components/landing/`, `../components/site/` | Hero, install walkthrough, privacy gate demo, benchmark. Styles in `memty.css`. |
| Demo workspace | `workspace/`, `../components/workspace/`, `../lib/memty-sim.ts` | In-browser Memty demo. `memty-sim.ts` mirrors the package's token estimate, capsule format and privacy gate; keep them in sync. |
| Legacy login UI | `../lib/legacy-markup.ts`, `../components/legacy-page.tsx`, `../public/legacy/` | HTML strings, React wrapper, and page scripts. |
| Shared and responsive styles | `globals.css` | Scope legacy styles to their page root classes. |
| Backend proxy routes | `backend/`, `users/` | Forward requests to the Express service. |

## Pages

| Route | Source | Purpose |
| --- | --- | --- |
| `/` | `page.tsx` | Memty landing page: what it is, install walkthrough, privacy gate, benchmark |
| `/workspace` | `workspace/page.tsx` + `components/workspace/workspace.tsx` | Hands-on Memty demo that runs entirely in the browser (no server calls) |
| `/login` | `login/page.tsx` | Sign in, register, and optional Google sign-in UI |
| `/chatbot` | `chatbot/page.tsx` | Redirects to `/workspace` (the old multi-model chat was retired) |
| `/memory` | `memory/page.tsx` + `memory/memory-dashboard.tsx` | Memory controls, conversation summaries, and usage |
| `/terms` | `terms/page.tsx` | Terms of Service draft |
| `/privacy` | `privacy/page.tsx` | Privacy Notice draft |
| `/api-reference` | `api-reference/page.tsx` | First-party chat API behavior and limitations |

The login page renders legacy HTML strings from `lib/legacy-markup.ts`; `LegacyPage` attaches their browser scripts from `public/legacy/`. The landing page, demo workspace, Memory dashboard and legal pages use React components directly. The landing page and workspace styles live in `memty.css`, scoped under `.mt`.

## GitHub Pages

`.github/workflows/deploy-pages.yml` publishes `/`, `/workspace`, `/privacy`, `/terms` and `/api-reference` to <https://memtylabs.github.io/memty/> on every push to `main` that touches the app. It sets `PAGES_BASE_PATH`, which makes `next.config.ts` produce a static export under that sub-path, and drops the server-only routes (API, backend proxies, login, memory, chatbot) first. To try the Pages build locally in PowerShell:

```powershell
$env:PAGES_BASE_PATH = '/memty'; npm run build   # output in out/
```

Use root-relative links through `next/link` (or prefix `process.env.NEXT_PUBLIC_BASE_PATH`) so they keep working under the sub-path.

## API routes

- `POST /api/chat`: authenticates through the backend, retrieves user context, calls the selected model, optionally compares a second model, and persists the turn.
- `GET /api/config`: lists configured models and public metadata. It does not return provider secrets.
- `/api/users/*` and `/users/*`: Next proxy routes to the backend user service.
- `/backend/*`: generic backend proxy used by the app.
- `GET /health`: frontend health response.
- `POST /api/clear-history`: clears browser history through the app's local-history flow.

The chat handler limits request bodies to 100 KiB and messages to 30,000 characters. Its current 30 requests per minute limit is in-memory per frontend process. It requires the HTTP-only session cookie from the backend. Chat generation currently returns a complete response rather than a token stream.

## Responsive layout

`globals.css` contains the shared legal and memory styles plus scoped legacy landing, login, and chat styles. Keep styles scoped under `.legacy-page-landing`, `.legacy-page-login`, or `.legacy-page-chat` to avoid affecting unrelated routes. The mobile chat sidebar becomes a drawer; the message composer wraps for narrow screens and accounts for device safe areas; compare results stack vertically on phones. Landing feature cards use two columns on tablets and one on narrow phones. Memory cards, usage rows, legal content, dialogs, and navigation reflow at phone widths.

The root layout declares a device-width viewport with `viewportFit: cover`. Interactive controls should retain touch-friendly dimensions, and long text should wrap instead of widening the viewport.

## Frontend environment

See the root `.env.example` for provider keys, model names, output limits, proxy target, frontend port, Google client ID, and memory defaults. Provider keys stay server-side in Next.js routes and must not be exposed through client JavaScript.

The workspace's short recent-history list and theme/display preferences use browser storage. Full neutral conversation context and portable memory are stored in MongoDB through the backend. Deleting browser storage removes local UI state; use the Memory page to delete saved server conversations and memories.

