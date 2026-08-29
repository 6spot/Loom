# Architecture Amendment 0004 — Derived-Resource Public Read Boundary

> Status: **ACCEPTED for Loom v0 architecture baseline.**
>
> Depends on: `0001-runtime-liveness-and-boundaries.md`, `0002-supersession-and-authority-linkage.md`, `0003-agency-execution-and-pinned-read-boundary.md`.
>
> This Amendment closes one public-consumption gap discovered during current-main Validator re-certification: Loom already has Runtime-owned semantic retrieval/projection and immutable BlobStore capabilities, but the sanctioned `loom-api` / `loom-client` boundary exposes no way for an external consumer to observe either derived resource. The amendment adds only narrow, provider-neutral reads. It does not create new World authority, projection administration, blob mutation, or storage exposure.

---

## 1. Exact affected-clause index

Frozen baseline documents remain historical snapshots. This Amendment augments their current interpretation through explicit linkage.

| Baseline location | Existing meaning | Current authority |
| --- | --- | --- |
| `runtime-contracts.md` §17.2 public API boundary | External consumers use the formal Loom API; the original v0 slice does not enumerate semantic-projection or blob-reference reads | **Materially augmented** by Amendment 0004 §3: `QueryService` may expose provider-neutral semantic-projection and exact blob-reference reads, mediated by Runtime |
| `implementation.md` §5.1 public boundary | Boundary/API is the supported external entry point | **Materially augmented** by Amendment 0004 §3–§5: two derived-resource reads are permitted; direct Storage/SQL/BlobStore access remains forbidden |
| `implementation.md` §16 semantic retrieval boundary | Runtime mediates semantic retrieval and providers are hidden from Capability/external code | **Clarified/augmented** by Amendment 0004 §3: external reads may request provider-neutral semantic results through Runtime without receiving a retriever/provider handle |
| `governance.md` public exposure rules | `loom-api` is the unified public consumption language and lower authority layers are not exposed | **Clarified, not relaxed** by Amendment 0004 §5: public DTOs are provider/storage-neutral and Runtime remains the gatekeeper |
| `docs/tasks/m7/t3-runtime-semantic-retrieval.md` current capability contract | Semantic retrieval is derived, revision-aware, typed unavailable/stale, and not World authority | **Publicly observable** through the read contract in Amendment 0004 §3; semantic meaning and authority are unchanged |
| `docs/tasks/m7/t4-blob-store.md` current capability contract | Blob bytes are immutable external data addressed by stable references; missing/corrupt data must not rewrite World truth | **Publicly observable** through the exact-reference read contract in Amendment 0004 §4; BlobStore authority and mutation rules are unchanged |

This Amendment does not alter Core primitives, World Runtime Binding, TimelineVersion, Scheduler chronology, commit authority, replay/fork semantics, or Agency semantics.

---

## 2. Problem and design constraint

The current architecture already supports both capability families internally:

```text
committed World truth
    ├── Runtime-mediated semantic projection / retrieval
    └── stable BlobReference -> immutable BlobStore bytes
```

But the sanctioned consumer path currently stops before those reads:

```text
external consumer / Validator / official client
        ↓
loom-client
        ↓
loom-api QueryService
        ↓
Runtime
        ✕ no formal semantic-projection observable
        ✕ no formal blob-reference fetch observable
```

Using Runtime internals, projection stores, BlobStore handles, or SQL as a workaround would violate the existing public-boundary architecture. Therefore the correct repair is a **minimal read-only extension of the existing Query boundary**, not a second service authority and not a test-only production bypass.

---

## 3. Semantic projection read

### 3.1 Service ownership

The public operation belongs to the existing `QueryService`; no `SemanticService` is introduced for v0.

Conceptually:

```text
SemanticProjectionQuery
        ↓
QueryService
        ↓
Runtime
        ↓
Runtime-owned semantic projection / retriever
        ↓
SemanticProjectionRead
```

The request identifies at least:

- target World/Timeline;
- semantic index identity;
- schema/index/model revision identity required by the existing M7 contract;
- provider-neutral query vector and `top_k`;
- optional exact source `TimelineVersion` when a pinned projection read is requested.

A successful result returns provider-neutral hits and the resolved source/projection identity required to prove which derived materialization answered the read.

### 3.2 Fail-closed outcomes

The public contract must distinguish at least:

- projection/index unavailable or rebuilding;
- stale projection revision;
- requested source revision does not match the materialized source.

These are typed API outcomes. A missing or stale derived projection never falls back to fabricated success and never changes World truth.

### 3.3 Deliberate non-goal: projection administration

The public API does **not** expose projection registration, rebuild, delete, provider selection, index-table access, or arbitrary projection mutation.

Those remain Runtime/application/test-fixture responsibilities under existing M7 ownership. A controlled Validator fixture may build/delete/rebuild projection state as setup, but acceptance evidence must come back through the formal `LoomClient` read.

---

## 4. Exact blob-reference read

The public operation also belongs to `QueryService`; no general Blob administration service is introduced.

Conceptually:

```text
BlobReference
        ↓
QueryService::read_blob
        ↓
Runtime
        ↓
BlobStore port
        ↓
integrity-verified bytes + stable reference metadata
```

The request addresses **one exact content-addressed reference**. The response returns its bytes and stable reference metadata only after the existing integrity contract succeeds.

The public contract must distinguish at least:

- reference not found;
- bytes present but integrity/hash verification fails;
- backing blob adapter unavailable.

A failed fetch never rewrites Facets, Events, History, or the BlobReference itself.

The API does **not** expose blob listing, browsing, write, delete, provider configuration, raw BlobStore handles, bucket paths, or persistence internals.

---

## 5. Authority and exposure rules

The following remain mandatory:

1. `loom-api` owns the public request/result/error vocabulary.
2. `loom-client` is the normal external consumer adapter.
3. `loom-boundary` transports the typed request/result; it does not implement semantic/blob authority.
4. `loom-runtime` mediates both reads and enforces target/revision/budget/integrity rules.
5. Storage adapters, projection stores, BlobStore handles, provider SDKs, SQL, table names and backend-specific identifiers never cross the public API.
6. Both operations are reads. They create no Event, Effect, Work, TimelineVersion advance or World mutation.
7. Existing resource/boundary limits remain applicable; this Amendment does not create an unbounded vector/blob transport exception.

Forbidden shortcuts include:

```text
Validator -> Runtime internals as acceptance evidence
Validator -> Storage/SQL
Boundary -> projection table directly
Boundary -> BlobStore directly
Client -> provider-specific semantic SDK
public projection rebuild/delete/register endpoint
public blob write/delete/list endpoint
```

---

## 6. Validator consequence

This Amendment authorizes only the missing formal observations needed by the existing frozen coverage semantics:

- CV-028 may use a test-only driver to build/delete/rebuild derived projection state, then use `LoomClient` semantic projection reads to prove rebuild equivalence while History/Facet truth remains unchanged.
- CV-029 may use a test-only driver to create/present/miss/corrupt blob backing state, then use `LoomClient` exact blob reads to prove success/not-found/integrity failure while History/Facet truth remains unchanged.

The controlled driver is still not acceptance evidence. The public read is.

This does not require CV-028/CV-029 to become generic production `--all` scenarios when their fixture setup is intentionally controlled-only. Registry policy remains a Validator/T19 concern, not a reason to add projection/blob mutation APIs.

---

## 7. Historical boundary

`VALR-T26` and PR #380 remain historical audit records. Their previous implementation was reverted because the public expansion lacked an accepted Architecture Amendment. This Amendment does not retroactively certify that candidate and does not resurrect T26.

New implementation work must be separately scoped, reviewed, executed on current main, and validated end-to-end.

---

## 8. Acceptance

This Amendment is satisfied only when:

- the public surface is limited to the two provider/storage-neutral reads described above;
- Runtime is the only authority/gateway behind both reads;
- semantic unavailable/stale/source-mismatch and blob not-found/integrity/unavailable outcomes are typed and fail closed;
- no projection administration or blob mutation API is added;
- controlled Validator evidence observes CV-028/CV-029 through `LoomClient`, never through Runtime/Storage/SQL assertions;
- InMemory and controlled PostgreSQL paths execute where applicable;
- architecture, dependency, storage-SQL ownership, format, check, clippy, tests, rustdoc, security policy and final Validator certification gates are green on the exact implementation candidate.
