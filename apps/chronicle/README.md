# Chronicle

Chronicle is the historical-world application built on Loom.

It is designed to let users enter any historical moment, inspect the world state of that time, follow people and entities through their trajectories, understand causal explanations and sources, and eventually fork a historical point into clearly labeled counterfactual simulation.

## Product principle

Chronicle does not treat Three Kingdoms, World War I, Roman history, or Chinese history as separate applications. They are progressively denser slices of one global historical corpus.

Initial data may focus on a narrow period, but the product and data model must remain compatible with gradual expansion toward Chinese history and world history.

## Project structure

- `docs/` — Chronicle product, UX, data, and implementation design documents.
- `ingestion/` — the schema-driven historical-data ingestion prototype, machine-readable contract, and curated regression fixtures.
- Application code will live in this directory when implementation begins.

## Current design documents

- [`docs/product.md`](docs/product.md) — product definition and V0 surfaces.
- [`docs/ui.md`](docs/ui.md) — interaction and UI design.
- [`docs/data-contract.md`](docs/data-contract.md) — Chronicle Data Contract v0.1 for Source / Entity / Event / Claim ingestion.
- [`ingestion/README.md`](ingestion/README.md) — first ingestion vertical slice and fixture semantics.

## Initial product pillars

1. **Time** — enter a historical moment and inspect the world at that time.
2. **World** — see concurrent events, places, polities, relationships, and state.
3. **People** — follow entity trajectories across the historical timeline.
4. **Why** — inspect sourced causal explanations and competing interpretations.
5. **Sources** — preserve provenance, confidence, uncertainty, and disputes.
6. **What If** — later fork a historical point into clearly separated simulation.

The historical browsing experience must remain useful even without counterfactual AI simulation.
