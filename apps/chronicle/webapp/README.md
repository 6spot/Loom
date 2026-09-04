# Chronicle webapp (C1-T9)

One React + TypeScript + Vite web application for Chronicle. One build serves
both public Chronicle routes and the `/studio/*` engineering surface.

## Routes

```text
/ , /timeline            public Timeline
/search                  public Search
/events/{id}             public Event Detail
/entities/{id}           public Entity Detail
/studio                  Studio overview (authenticated)
/studio/imports          Imports placeholder (C1-T10 mounts here)
/studio/review           Review placeholder (C1-T11 mounts here)
/studio/sources          Sources/Corpus placeholder (C1-T12/C1-T13 mount here)
/studio/login            Studio login (HTTP Basic credentials, memory-only)
```

## Stack

- React Router for browser routing (single `BrowserRouter`; Studio routes are
  nested under `/studio/*` in the same app, not a separate deployment).
- TanStack Query for server state (`src/lib/queries.ts`).
- shadcn/ui-style component foundation **only** for Studio
  (`src/components/ui/*` + `src/styles/studio.css`). Public Chronicle pages use
  `src/styles/chronicle.css` (ported C0 product styles) and must not import
  from `components/ui` (enforced by `tests/route-split.test.ts`).
- Studio routes are `React.lazy` code-split (`tests/route-split.test.ts`);
  public browsing never loads the admin component surface
  (`scripts/check-dist.mjs` verifies a separate Studio chunk in `dist/`).

## API boundary

The UI calls only the Rust server public boundary:

```text
GET /api/v1/public/timeline
GET /api/v1/public/search
GET /api/v1/public/events/{id}
GET /api/v1/public/entities/{id}
GET /api/v1/studio/status   (Studio only, HTTP Basic, server-enforced)
```

No PostgreSQL, no staged artifacts, no migrations, no secrets in browser code
(enforced by `tests/no-db-authority.test.ts`).

Studio authentication stays server-enforced: the login form only attaches
`Authorization: Basic ...` to Studio fetches and keeps credentials for the
tab session (sessionStorage: survives reloads, cleared on tab close, never
`localStorage`) without logging them. Privileged APIs remain
`401` + `Basic realm="chronicle-studio"` without credentials and fail closed
(`503 studio_auth_unconfigured`) when the server has no admin configured.

## Build output

`vite.config.ts` emits deterministic filenames (no content hash) into
`../web/dist/` so `chronicle-server` can embed the build at compile time with
`include_bytes!`. The `dist/` output is committed so `cargo test` works
without a Node toolchain:

```bash
npm ci
npm test          # vitest: API paths, routes, no-DB-authority, route-split
npm run build     # tsc + vite build -> apps/chronicle/web/dist/
npm run smoke:dist
```

`Dockerfile` needs no Node stage: it already copies `apps/chronicle/web`
(which now includes `dist/`).

## Verification

- `npm test && npm run build && npm run smoke:dist`
- `cargo test` inside `apps/chronicle/server/`
- `node scripts/visual-verify.mjs` (Playwright + Chromium against the real
  Rust server + mock upstream; writes `scripts/visual/*` screenshots)
- Existing Chronicle browser smoke (`apps/chronicle/web/browser_smoke.py`)
  against a real imported database still exercises the same DOM contracts.
