# Chronicle

Chronicle is the historical-world application built on Loom.

It is designed to let users enter any historical moment, inspect the world state of that time, follow people and entities through their trajectories, understand causal explanations and sources, and eventually fork a historical point into clearly labeled counterfactual simulation.

## Product principle

Chronicle does not treat Three Kingdoms, World War I, Roman history, or Chinese history as separate applications. They are progressively denser slices of one global historical corpus.

Initial data may focus on a narrow period, but the product and data model must remain compatible with gradual expansion toward Chinese history and world history.

## Project structure

- `docs/` — Chronicle product, UX, data, read API, and browser UI documents.
- `ingestion/` — schema-driven historical-data ingestion, resolution, and canonical publication prototypes/contracts.
- `persistence/` — Chronicle-owned PostgreSQL persistence for staged, Resolution, and canonical layers.
- `read_api/` — deterministic Timeline/Event/Entity read contracts plus the same-origin HTTP host.
- `web/` — zero-build Chronicle browser UI that consumes only the C0-T10 HTTP API.

## Current design and implementation documents

- [`docs/product.md`](docs/product.md) — product definition and V0 surfaces.
- [`docs/ui.md`](docs/ui.md) — broader interaction and UI design direction.
- [`docs/browser-ui.md`](docs/browser-ui.md) — implemented C0-T11 Timeline/Event/Entity browser slice.
- [`docs/read-api.md`](docs/read-api.md) — C0-T10 read-model and HTTP contracts.
- [`docs/data-contract.md`](docs/data-contract.md) — Chronicle Data Contract v0.1 for Source / Entity / Event / Claim ingestion.
- [`ingestion/README.md`](ingestion/README.md) — ingestion vertical slice and fixture semantics.

## Run the current browser slice

Against an already imported Chronicle PostgreSQL database:

```bash
export CHRONICLE_DATABASE_URL='postgresql://.../chronicle'
python3 apps/chronicle/read_api/server.py --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080/timeline`.

The browser UI calls only `/v0/timeline`, `/v0/events/{id}`, and `/v0/entities/{id}`. It does not read local ingestion artifacts or PostgreSQL directly.

## Initial product pillars

1. **Time** — enter a historical moment and inspect the world at that time.
2. **World** — see concurrent events, places, polities, relationships, and state.
3. **People** — follow entity trajectories across the historical timeline.
4. **Why** — inspect sourced causal explanations and competing interpretations.
5. **Sources** — preserve provenance, confidence, uncertainty, and disputes.
6. **What If** — later fork a historical point into clearly separated simulation.

The historical browsing experience must remain useful even without counterfactual AI simulation.
