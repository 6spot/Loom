# Application world modeling

Use Loom concepts to model durable application semantics before designing UI tables or ad-hoc persistence.

## Modeling questions

Before implementation, decide:

- What is the World boundary?
- When is a new Timeline required instead of more state on the same Timeline?
- Which domain objects are Entities?
- Which durable properties belong in Facets?
- Which changes should be represented as Events?
- Which user/system operations are Actions?
- Which relationships must remain queryable or explainable through history?

## Prefer domain meaning over storage shape

Do not start from PostgreSQL tables and then map them upward.

Start from application semantics and the public Loom model, then use Loom APIs to create/query the authoritative state.

Application-owned relational tables may still be appropriate for unrelated product concerns such as accounts, UI preferences, billing or derived search caches, but they must not become a second authority for Loom World state.

## Timeline use

Use Timeline when the application needs an explicit alternate evolution path, fork, simulation or counterfactual history.

Do not create separate Timelines merely as a substitute for ordinary categorization or pagination.

## Historical applications

For history-oriented applications such as Chronicle, distinguish at least:

- source/import records;
- normalized domain facts;
- Loom semantic events/state;
- derived presentation/search structures.

The ingestion pipeline may clean and normalize external data before it becomes Loom input. Once committed through Loom, do not maintain a parallel mutable copy as the semantic source of truth.

## Validate with examples

Before building a large importer or UI, model a small end-to-end slice and verify that Actions, state reads, history and Timeline behavior express the product requirement cleanly.
