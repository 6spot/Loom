# Chronicle document upload and immutable revisions (C1-T3)

Controlled UTF-8 text (`.txt` / `.md`) becomes a durable first-class
Chronicle source: a logical Document groups immutable Revisions, each
revision pins exact source bytes on disk plus auditable metadata in
PostgreSQL, and replacement appends a new revision instead of overwriting
history. Later stages (segmentation, chunks, evidence) trace to exact
source bytes through the revision's source locator.

Stop condition: if a source cannot be represented as controlled UTF-8
text, it is rejected here. PDF/OCR, EPUB/DOCX, and other adapters belong
to later tasks.

## Authority boundary

Application-owned product persistence only (Architecture Amendment 0006):

- PostgreSQL behind `CHRONICLE_DATABASE_URL`, migrations under
  `apps/chronicle/persistence/migrations/` (`0003_chronicle_c1_documents.sql`
  is strictly additive over the C1-T1 control plane).
- Source files under the Chronicle-owned data directory configured by
  `CHRONICLE_SOURCE_DIR` (Compose mounts it from the supported Chronicle
  data volume, so content survives restart/redeploy).
- The Rust `chronicle-server` never opens the database (no DB driver, no
  SQL): it enforces Studio auth and proxies document operations to the
  internal Python sidecar (`docs/server.md`).
- No Loom Runtime/World/Timeline/Work/Binding authority is read, written,
  or exposed.

## Upload contract

| Rule | Behavior |
| --- | --- |
| Formats | `.txt` (`text/plain`) and `.md` (`text/markdown`) only |
| Encoding | strict UTF-8; one leading BOM stripped; CRLF/CR normalized to LF for character counts (stored bytes stay verbatim; SHA-256 is over those bytes) |
| Size | `CHRONICLE_MAX_UPLOAD_BYTES` (default 10 MiB); over-limit fails with typed `413 payload_too_large` before anything is stored |
| Filename | plain basename, 1–255 chars, no `/`, `\`, `..`, leading `.`, or control characters |
| Media type | derived from the extension; a supplied `Content-Type` must match it |
| Storage key | server-derived relative key `documents/{document_id}/{revision_id}{ext}` — never a client path, never absolute |
| Write path | temp sibling + fsync + atomic rename; a DB failure removes staged bytes; a crash between commit and rename leaves `storage_status: missing`, repaired by retrying the identical upload |
| Duplicate | identical bytes to the tip return the tip with `duplicate: true` (no new row); replacement with different bytes appends revision N+1 with `supersedes_revision_id` set |
| Immutability | revision rows are DB-trigger immutable (C1-T1 guard still enforced); history is append-only |

## Revision metadata

Every revision records: document/revision identity, revision number,
filename, media type, byte size, character count, SHA-256, timestamps,
optional language/source labels, the relative storage key, and file
presence (`storage_status`). The tip revision per document is exposed
through the `chronicle.document_current_revisions` view; API status is
derived from revision ordering (`active` = tip, `superseded` otherwise) —
there is no mutable status column to drift from history.

## Studio API

Authenticated by the Rust server; served by the sidecar. Uploads send raw
file bytes with `?filename=` (plus optional `&language=` /
`&source_label=`):

```text
POST   /api/v1/studio/documents
GET    /api/v1/studio/documents
GET    /api/v1/studio/documents/{document_id}
POST   /api/v1/studio/documents/{document_id}/revisions?filename=wudi.txt
GET    /api/v1/studio/documents/{document_id}/revisions
GET    /api/v1/studio/documents/{document_id}/revisions/{revision_no_or_uuid}
GET    /api/v1/studio/documents/{document_id}/revisions/{revision_no_or_uuid}/content
```

Errors use the C0 envelope (`chronicle.error`): `bad_request` (400),
`unauthorized` / `studio_auth_unconfigured` (401/503, from the Rust
boundary), `not_found` (404, including cross-document revision access),
`method_not_allowed` (405), `payload_too_large` (413),
`database_unavailable` (503).

## Source locators for later stages

Each revision read carries a `locator`:

```json
{
  "document_id": "…",
  "revision_id": "…",
  "revision_no": 2,
  "source_sha256": "…",
  "source_bytes": 1024,
  "content_chars": 512,
  "storage_key": "documents/…/….txt",
  "source_start": 0,
  "source_end": 1024
}
```

Future sections/chunks cite `(revision_id, source_sha256,
[source_start, source_end))` sub-ranges of these exact bytes, so evidence
always resolves to auditable source content.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `CHRONICLE_SOURCE_DIR` | `./chronicle-sources` | Chronicle-owned directory that source files persist under |
| `CHRONICLE_MAX_UPLOAD_BYTES` | `10485760` | per-file upload ceiling in bytes |

The sidecar also accepts `--storage-dir` / `--max-upload-bytes` flags,
which override the environment for local development.

## Verification

- `python3 apps/chronicle/persistence/test_documents_unit.py` — validation,
  storage keys, atomic writes (no database).
- PostgreSQL 18: `test_documents_postgres.py` (store round trips,
  replacement immutability, safe failures, idempotency, locators) and
  `read_api/test_studio_documents_postgres.py` (full HTTP surface through
  the real sidecar). Both follow the repository PostgreSQL control-service
  pattern (`LOOM_TEST_POSTGRES_URL` or local `tools/postgres-test.sh`).
- Rust: `cargo test` / `clippy` / `fmt --check` in
  `apps/chronicle/server/` (Studio auth matrix, proxy passthrough,
  405/413 mapping, outage mapping).
