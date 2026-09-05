# Chronicle webapp

One React + TypeScript + Vite web application for Chronicle. One build serves
both the public Historical World experience and the `/studio/*` engineering
surface.

## Routes

```text
/                        redirects to /world?year=208
/world                   public grounded Historical Moment / World page
/timeline                public Timeline
/search                  public Search
/events/{id}             public Event Detail
/entities/{id}           public Entity Detail
/studio                  Studio overview (authenticated)
/studio/imports          import operations
/studio/review           resolution review
/studio/sources          source/corpus operations
/studio/coverage         corpus Coverage visibility
/studio/login            Studio login (HTTP Basic credentials, tab-session only)
```

The Rust same-origin web front serves the SPA shell for `/world` and `/world/`,
so a direct browser refresh of a bookmarked Historical World URL remains on the
React route rather than falling through to an API/404 path.

Public routes may carry the shared historical-time context as either
`?year=208` or a bounded `?from_year=208&to_year=210` range. Chronicle keeps
this context in the URL so World, Timeline, Search, Event, and Entity links are
bookmarkable and deterministic. The public UI exposes year/year-range precision
only; it does not fabricate month/day precision.

## Historical World boundary

`/world` is a presentation of the C1 Historical Moment projection, not a
complete Historical World State. Browser code renders only data returned by the
public Chronicle APIs: canonical Events/Entities, persisted Reader Presentation,
Claim/source evidence, Coverage, and explicit uncertainty. It must not infer
territorial control, precise person locations, political ownership, office
state, troop state, or other missing historical state merely to fill a card.
An unrepresented period is a corpus-coverage statement, not a claim that
nothing happened historically.

## Stack

- React Router for browser routing (single `BrowserRouter`; Studio routes are
  nested under `/studio/*` in the same app, not a separate deployment).
- TanStack Query for server state (`src/lib/queries.ts`).
- shadcn/ui-style component foundation **only** for Studio
  (`src/components/ui/*` + `src/styles/studio.css`). Public Chronicle pages use
  Chronicle-specific product CSS (`src/styles/chronicle.css` and
  `src/styles/world.css`) and must not import from `components/ui` (enforced by
  `tests/route-split.test.ts`).
- Studio routes are `React.lazy` code-split; public browsing never loads the
  admin component surface (`scripts/check-dist.mjs` verifies separate Studio
  chunks in the committed build).

## API boundary

The browser stays downstream of the Rust Chronicle public boundary:

```text
GET /api/v1/public/historical-moment
GET /api/v1/public/timeline
GET /api/v1/public/search
GET /api/v1/public/events/{id}
GET /api/v1/public/entities/{id}
GET /api/v1/studio/status   (Studio only, HTTP Basic, server-enforced)
```

No PostgreSQL, application persistence adapter, staged artifacts, migrations,
or deployment secrets are browser authorities (`tests/no-db-authority.test.ts`).
The Historical Moment response itself explicitly carries derived-projection,
Coverage, and uncertainty semantics; the frontend does not override them.

Studio authentication stays server-enforced: the login form only attaches
`Authorization: Basic ...` to Studio fetches and keeps credentials for the tab
session (`sessionStorage`, never `localStorage`) without logging them.
Privileged APIs remain `401` + `Basic realm="chronicle-studio"` without valid
credentials and fail closed (`503 studio_auth_unconfigured`) when the server
has no administrator configured.

## Build output

`vite.config.ts` emits deterministic filenames (no content hash) into
`../web/dist/` so `chronicle-server` can embed the build at compile time with
`include_bytes!`. The `dist/` output is committed so `cargo test` works without
a Node toolchain:

```bash
npm ci
npm test
npm run build     # tsc + vite build -> apps/chronicle/web/dist/
npm run smoke:dist
```

`Dockerfile` needs no Node stage: it already copies `apps/chronicle/web`
(which includes `dist/`).

## Verification

- `npm test && npm run build && npm run smoke:dist`
- `cargo test` inside `apps/chronicle/server/`
- Existing two-source browser smoke: `apps/chronicle/web/browser_smoke.py`
- Historical World production-front smoke: `apps/chronicle/web/world_browser_smoke.py`
  (World -> Event -> Entity -> persisted evidence, plus neighboring Coverage
  semantics and historical-time-context preservation)
- `node scripts/visual-verify.mjs` for focused Playwright/Chromium visual checks
  against the real Rust server and its configured upstream.
