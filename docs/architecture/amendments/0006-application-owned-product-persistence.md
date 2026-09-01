# Architecture Amendment 0006 — Application-Owned Product Persistence

> Status: **ACCEPTED for Loom v0 architecture baseline.**
>
> Depends on: `0001-runtime-liveness-and-boundaries.md`, `0002-supersession-and-authority-linkage.md`, `0003-agency-execution-and-pinned-read-boundary.md`, `0004-derived-resource-public-read-boundary.md`, `0005-automatic-bounded-timeline-discovery.md`.
>
> This Amendment closes a persistence-boundary gap discovered when Chronicle application persistence was checked against Loom's engine-storage enforcement. The existing rule correctly reserves Loom Runtime/World/Timeline PostgreSQL authority to `loom-storage`, but its machine interpretation also rejected an independent application's own product corpus merely because that corpus used PostgreSQL. This Amendment separates **Loom engine persistence** from **explicitly registered application-owned product persistence** without granting applications access to Loom engine storage authority.

---

## 1. Exact affected-clause index

Frozen baseline documents remain historical snapshots. This Amendment augments their current interpretation through explicit linkage.

| Baseline location | Existing meaning | Current authority |
| --- | --- | --- |
| `governance.md` §5.3 Runtime persistence/authority ports | Runtime defines Loom execution persistence ports and `loom-storage` implements them | **Clarified, not weakened** by Amendment 0006 §3: this exclusivity covers Loom engine/Runtime persistence authority; an Application may separately own persistence for product data that is outside Loom engine authority |
| `governance.md` §6 `loom-storage` type placement | PostgreSQL transaction implementation and migrations belong to `loom-storage` | **Materially augmented** by Amendment 0006 §3–§4: Loom engine PostgreSQL remains exclusively `loom-storage`; an explicitly registered Application may own its own product database/schema, migrations and adapter when the data is not Loom World/Runtime/Timeline authority |
| `governance.md` §7 One Public Loom Entry Point | Loom semantic operations are exposed through `loom-api` / Runtime rather than capability/storage bypasses | **Clarified, not relaxed** by Amendment 0006 §5: an Application may expose a product API over data the Application itself owns; any operation on Loom engine semantics still goes through Loom API |
| `governance.md` §9 Transport is an Adapter | Transport cannot define or bypass Loom semantics | **Clarified** by Amendment 0006 §5: product transport may present Application-owned data, but may not turn that route into a hidden Loom Runtime/Storage path |
| `governance.md` §10 Composition Root | Applications wire Loom implementations but do not acquire Runtime/Storage authority | **Clarified** by Amendment 0006 §3–§5: a composition root may additionally wire an independent product datastore owned by that Application, provided the datastore is not a Loom engine persistence implementation |
| `crates/loom-storage/sql/README.md` PostgreSQL SQL ownership | `loom-storage` is the only owner of SQLx/PostgreSQL implementation details | **Narrowed to Loom engine persistence** by Amendment 0006 §3–§4; registered Application product stores are a separate authority domain and never become `PgStorage` or Runtime persistence ports |
| `tools/check_storage_sql_ownership.py` all-repository `*.sql` rule | Any SQL file outside `crates/loom-storage` fails | **Replaced** by Amendment 0006 §6: SQL is allowed only under `loom-storage` or an explicit registered Application product-persistence root; there is no generic `apps/**` exemption |

This Amendment does not change Core primitives, World Truth authority, World Runtime Binding, World Time, Timeline logical commit, Runtime Revision, Capability semantics, Scheduler authority, or the Cargo dependency DAG.

---

## 2. Problem and why the existing contract is insufficient

The current storage rule was written to prevent this dangerous path:

```text
Application / Capability / Boundary
        ↓
raw SQL / PgPool / table name
        ↓
Loom Runtime / World / Timeline persistence
```

That prohibition remains correct.

However, Loom can host product applications whose own durable data is not Loom engine state. Chronicle provides a concrete counterexample. Its historical source corpus contains:

```text
source-owned historical records
cross-source Resolution Links
application canonical publication records
application read-model data
```

Those records are not:

```text
World Truth committed by Loom Runtime
World Runtime Binding
Timeline logical state
World-Time authority
Runtime Revision
Durable Work authority
Execution provenance owned by Loom Runtime
```

Treating every PostgreSQL table in the monorepo as a Loom Runtime storage table would force application-specific product semantics into `loom-storage` merely because PostgreSQL is the chosen database. Persistence technology would then determine semantic ownership, contradicting the governance principle that **persistence location does not determine semantic ownership**.

The missing distinction is therefore:

```text
Loom engine persistence
!=
Application-owned product persistence
```

---

## 3. Two persistence authority domains

### 3.1 Loom engine persistence

`loom-storage` remains the exclusive PostgreSQL implementation owner for Loom engine authority, including Runtime ports and data such as:

```text
World / Timeline engine state
logical commit/history authority
World Runtime Binding persistence
World-Time transition persistence
Durable Work / claim state
Runtime Revision / execution provenance
engine-owned projections and other Runtime persistence ports
```

No Application, Capability, Boundary, provider adapter or product module may read or write those tables directly.

### 3.2 Application-owned product persistence

An Application may own an independent product datastore only when all of the following are true:

1. **Semantic ownership is application-local.** The records describe product/application concepts rather than Loom Runtime authority.
2. **Connection authority is separate.** The Application uses an application-specific connection contract, not `LOOM_DATABASE_URL` or a `PgStorage` handle. A separate database is preferred; a separately owned schema is acceptable only when operational isolation is explicit.
3. **Migrations are application-owned.** They evolve only the application's product schema and never create/alter/drop Loom engine tables.
4. **No engine persistence port is implemented.** The adapter is not an implementation of `WorldStore`, `CommitStore`, Work storage, binding storage, Runtime Revision storage, or any other Runtime-owned persistence port.
5. **No Loom storage internals leak in.** The Application does not import/use `PgStorage`, engine table names, engine SQL files, engine transactions, or storage-private row types.
6. **Loom semantic operations still use Loom API.** Product persistence cannot be used to mutate or impersonate Loom World/Timeline/Runtime semantics.
7. **Ownership is explicitly registered in machine enforcement.** There is no wildcard permission for arbitrary application SQL.

Conceptually:

```text
                 Loom engine domain
Application ──> Loom API ──> Runtime ──> Runtime persistence ports ──> loom-storage

                 Application product domain
Application ────────────────────────────────────────────────────────> its own product store
```

The lower arrow is legal only for data the Application itself owns.

---

## 4. SQL, migrations and database-driver boundary

An accepted Application product-persistence root may contain:

```text
application migrations
application SQL/query implementation
application database driver code
application transaction orchestration
application repository/read-model code
```

Those implementation details must remain inside the registered Application boundary and must not be imported upward into Loom Core/Protocol/API/Runtime/Capability/Boundary crates.

This Amendment does **not** create a general SQL exception. In particular, the following remain forbidden:

```text
apps/*/random.sql                        # not registered
capabilities/*/*.sql                     # forbidden
loom-boundary -> application DB tables   # hidden engine/public bypass
Application -> crates/loom-storage/sql   # storage-private dependency
Application -> LOOM_DATABASE_URL         # engine DB authority
Application SQL -> timeline/world/work engine tables
```

A registered root should be as narrow as possible, normally its migrations/query/persistence subtree rather than the whole Application.

### 4.1 Chronicle registration

For Loom v0, the first accepted product-persistence registration is:

```text
Application: Chronicle
Persistence root: apps/chronicle/persistence/
SQL root:         apps/chronicle/persistence/migrations/
Connection:       CHRONICLE_DATABASE_URL
Authority:        historical source / resolution / canonical product corpus
Excluded:         all Loom Runtime/World/Timeline/Work/Binding authority
```

Chronicle may operationally use the same PostgreSQL server/image as Loom, but shared server process does not imply shared semantic authority. Production ownership remains separated by database/schema and connection contract.

---

## 5. Product API versus Loom public API

`One Public Loom Entry Point` continues to mean that **Loom engine semantics** have one sanctioned public contract.

It does not mean every product-specific datum stored by every Application must be promoted into `loom-api`.

An Application may expose a product API over its own data, for example:

```text
Chronicle Timeline read
Chronicle historical Event Detail
Chronicle historical Entity Detail
source/evidence inspection
```

provided those operations read only Application-owned product authority.

If the same Application needs a Loom semantic operation, the path remains:

```text
Chronicle / other Application
        ↓
      Loom API
        ↓
      Runtime
```

Forbidden examples remain:

```text
Chronicle API -> UPDATE Loom timeline table
Chronicle API -> PgStorage private query
Chronicle product canonical row -> masquerades as committed Loom World Event
Application HTTP route -> Capability Resolver directly
```

Thus an Application product API is not a second Loom engine API; it is the public surface of a separate product authority domain.

---

## 6. Machine enforcement

The SQL ownership checker must enforce a closed registration model.

Required behavior:

1. `crates/loom-storage/migrations/**` and `crates/loom-storage/sql/**` remain allowed as Loom engine SQL roots.
2. Additional SQL roots are allowed only through an explicit source-controlled Application product-persistence registration.
3. The initial registration is Chronicle's persistence migration root.
4. A new Application SQL root requires an Architecture Amendment (or later equally explicit architecture registry mechanism), not a glob such as `apps/**`.
5. The checker must still fail SQL elsewhere.
6. The checker should fail if a registered Application boundary loses its required ownership documentation/connection declaration.

Core CI path routing should likewise classify Loom Storage PostgreSQL tests from Loom-owned Storage paths rather than from every `*.sql` file in the repository. Each registered Application owns its own database contract lane.

---

## 7. Alternatives considered

### 7.1 Put Chronicle tables and migrations into `loom-storage`

Rejected for the current product corpus.

This would make the engine adapter physically own application-specific Source / Resolution / Canonical publication concepts and couple Chronicle product schema evolution to Loom Runtime storage releases. It would make technology placement determine semantic ownership and would invite product concepts into engine persistence domains despite no Runtime port requiring them.

If Chronicle later needs to persist actual Loom World/Timeline semantics, those writes must use Loom API/Runtime ports and `loom-storage`; this Amendment does not authorize a Chronicle shortcut.

### 7.2 Promote the complete Chronicle product model into `loom-api`

Rejected.

`loom-api` is the public consumption language of the Loom engine, not a generic home for every application's product DTOs. Source criticism, historical cross-source resolution and Chronicle presentation contracts are not currently Loom engine semantics.

### 7.3 Keep Chronicle as JSON files only

Rejected for the product requirement.

The application requires durable, restart-safe, queryable data and stable read contracts. Avoiding a database only to satisfy a storage-location checker would remove required product behavior rather than solve the authority distinction.

### 7.4 Move Chronicle into a separate repository/service solely to escape the checker

Rejected as an architecture requirement.

Repository/process separation may be an operational choice later, but it does not create a semantic boundary that is absent in the model. The monorepo should be able to represent two explicitly isolated persistence authorities without pretending they are one.

---

## 8. Dependency / authority safety

This Amendment creates no Rust dependency cycle and does not add a new framework crate edge.

Application product persistence:

- cannot be imported by `loom-core`, `loom-protocol`, `loom-api`, `loom-runtime`, `loom-capability`, `loom-agency`, or `loom-boundary` as a hidden authority source;
- cannot implement Runtime persistence ports unless moved behind the ordinary Runtime -> port -> `loom-storage` architecture;
- cannot expose Loom storage/backend identifiers as Loom API DTOs;
- cannot infer or mutate World Truth from product rows;
- remains replaceable product infrastructure owned by its Application.

The key invariant is:

> **A database engine is infrastructure; authority belongs to the semantic owner of the records. Loom engine records remain `loom-storage`-exclusive, while explicitly isolated product records may be Application-owned.**

---

## 9. Discovery/remediation note

C0-T9 Chronicle persistence was merged before the repository's core Architecture policy was executed against the new Application SQL path. C0-T10 CI subsequently exposed the mismatch.

This Amendment is not justified by “the code already exists.” The independent justification is the semantic distinction and alternatives evaluated in §§2–8. If this Amendment were not accepted, the required remediation would be to revert/refactor Chronicle persistence behind existing Loom engine storage/API boundaries before C0-T10 delivery.

Until Amendment 0006 is merged, C0-T10 delivery remains blocked.

---

## 10. Acceptance

This Amendment is satisfied only when:

- the architecture index records the exact supersession/clarification links above;
- `loom-storage` documentation states its exclusivity in terms of Loom engine persistence rather than every product datastore in the monorepo;
- machine enforcement uses a closed explicit registration for Application product SQL roots rather than a broad application allowlist;
- Chronicle's registration is limited to its product persistence boundary and `CHRONICLE_DATABASE_URL`;
- arbitrary SQL outside Loom Storage or registered Application product roots still fails;
- core architecture checks pass on the exact amendment candidate;
- Chronicle's own PostgreSQL contracts continue to pass independently;
- no Loom Runtime/World/Timeline/Work/Binding authority is moved to or exposed through Chronicle persistence;
- C0-T10 is not merged until this architecture amendment is accepted and its enforcement is present on `main`.
