# Chronicle

Chronicle is the historical-world application built on Loom.

Readers enter through important periods or events and follow a continuous,
chronological historical narrative synthesized from reviewed source material.
People and places carry the states supported for the current phase; sources
and uncertainty are available when the reader chooses to investigate.

## Product principle

Chronicle does not treat Three Kingdoms, World War I, Roman history, or Chinese history as separate applications. They are progressively denser slices of one global historical corpus.

Initial data may focus on a narrow period, but the product and data model must remain compatible with gradual expansion toward Chinese history and world history.

## Project structure

- `docs/` — Chronicle product, UX, data, read API, and browser UI documents.
- `ingestion/` — schema-driven historical-data ingestion, resolution, and canonical publication prototypes/contracts.
- `corpus/` — pinned historical source packs and development fixture tooling; [six retained biographies](corpus/c1-t13/sources/README.md).
- `assets/backgrounds/` — retained background-art candidates, prompts and metadata; [archive entry](assets/backgrounds/README.md), not a public image-serving directory.
- `persistence/` — Chronicle-owned PostgreSQL persistence for staged, Resolution, and canonical layers.
- `read_api/` — published history, source and object reads; internal Studio orchestration.
- `webapp/` — the single React/TypeScript public and Studio application.
- `web/dist/` — committed build embedded by the Rust server.

## Current design and implementation documents

- [`docs/historical-narrative-design.md`](docs/historical-narrative-design.md) — continuous history, curated anchors, page responsibilities and R3 boundaries.
- [`docs/source-corroboration.md`](docs/source-corroboration.md) — complete-source facts, two review gates, immutable narrative publication and APIs.
- [Reading enhancement](../../docs/tasks/chronicle/reading-enhancement/README.md) — #658 implementation and focused acceptance context.
- [Second-round task graph](../../docs/tasks/chronicle/second-round/README.md) — #549 source-reading delivery; background-art preparation has its own scope.
- [`docs/continuous-reading.md`](docs/continuous-reading.md) — second-round chapter annotations, immutable streams, source time and snapshot APIs.
- [`docs/reading-experience.md`](docs/reading-experience.md) — reading layout, current-fragment context, accessible previews and position restoration.
- [`docs/person-state-reading.md`](docs/person-state-reading.md) — third-round source-grounded offices, affiliations, narrative phases, evidence review and certainty display (implementation target).
- [`docs/background-art.md`](docs/background-art.md) — era-aware background art, explicit generation/upload and human save-to-display workflow; product upload/display integration remains planned.
- [First-round task graph](../../docs/tasks/chronicle/first-round/README.md) — #548 chapter production and review task context.
- [`docs/chapter-production.md`](docs/chapter-production.md) — first-round full-chapter production, references and publication contract.
- [`docs/review-workflow.md`](docs/review-workflow.md) — first-round review queue, source context and continuous review contract.
- [`docs/product.md`](docs/product.md) — product definition and V0 surfaces.
- [`docs/ui.md`](docs/ui.md) — broader interaction and UI design direction.
- [`docs/browser-ui.md`](docs/browser-ui.md) — implemented C0-T11 Timeline/Event/Entity browser slice.
- [`docs/read-api.md`](docs/read-api.md) — C0-T10 read-model and HTTP contracts.
- [`docs/data-contract.md`](docs/data-contract.md) — Chronicle Data Contract v0.1 for Source / Entity / Event / Claim ingestion.
- [`ingestion/README.md`](ingestion/README.md) — ingestion vertical slice and fixture semantics.

## Run the current browser slice

The long-lived path is the Rust Chronicle server (`docs/server.md`), which
fronts the deployment with public/Studio namespaces, single-admin Studio
auth, and the same-origin web UI. Against an already imported Chronicle
PostgreSQL database:

```bash
export CHRONICLE_DATABASE_URL='postgresql://.../chronicle'
python3 apps/chronicle/read_api/server.py --host 127.0.0.1 --port 8081 &
CHRONICLE_UPSTREAM_URL=http://127.0.0.1:8081 \
cargo run --manifest-path apps/chronicle/server/Cargo.toml
```

Open `http://127.0.0.1:8080/`. A fresh deployment stays empty until content is
produced and reviewed; it does not seed a demonstration article. Configure
the chapter and narrative models and follow [`docs/worker.md`](docs/worker.md)
to publish a real history through Studio.

Public reads live under `/api/v1/public/*` (legacy `/v0/*` compat is
preserved); Studio operations live under `/api/v1/studio/*` and require the
environment-configured administrator. The browser UI calls only the read
contracts. It does not read local ingestion artifacts or PostgreSQL
directly.

## Initial product pillars

1. **Time** — enter a historical moment and inspect the world at that time.
2. **World** — see concurrent events, places, polities, relationships, and state.
3. **People** — follow entity trajectories across the historical timeline.
4. **Why** — inspect sourced causal explanations and competing interpretations.
5. **Sources** — preserve provenance, confidence, uncertainty, and disputes.
6. **What If** — later fork a historical point into clearly separated simulation.

The historical browsing experience must remain useful even without counterfactual AI simulation.
