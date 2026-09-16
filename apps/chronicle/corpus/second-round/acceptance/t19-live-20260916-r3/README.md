## T19 real-data linked publication/readback evidence (2026-09-16)

This directory is the latest real-data rerun for PR head
`3956ab0202edf4e37101aeb9df5c7d5167128827`, after the public chapter linking
fix. It is additive: the earlier strict-provider records in
`../t19-live-20260916-r2/` remain unchanged.

### Result

One fresh database run for 《三國志·吳書·周瑜傳》 reached `completed` at the
`present` stage after the real provider, human review decisions and publication
resume. The job has 18 published reading units, 8 time groups, a published
chapter/catalog, and a public reading stream. Credentials are omitted; the
global model timeout was 1,800 seconds.

The downstream regression was real: before this head, public chapter detail
returned `reference_unmapped` HTTP 409 when assembled blocks already contained
chapter-scoped revision refs. `reader_chapters.py` now accepts either the
legacy local ref or an already assembled ref only when it belongs to the
addressed chapter, and still fails closed for unknown/cross-chapter refs. The
same published chapter detail and source anchor returned HTTP 200 after the
fix. The focused regression is in
`apps/chronicle/read_api/test_reader_chapters_unit.py`.

### Evidence map

- `t19-live-execution.json`: immutable run, provider selection, acceptance,
  failure-artifact, publication and downstream readback manifest.
- `content-checks.json`: 12 source-grounded checks covering称谓、阶段身份、
  source ownership, alternative attribution, contradiction and uncertainty.
  Nine are direct passes and three explicitly preserve source-qualified
  uncertainty; none failed.
- `model-outputs/job-detail.json` and `model-outputs/api-pages/`: full job
  detail, usage/status/timestamps and every saved model/attempt output. Invalid
  extraction, linking and review outputs are retained and excluded from the
  accepted candidate.
- `operator/`: content-review rounds, human revisions, acceptance, and the
  person-state review/decision. The final model context-limit record is kept;
  no model pass is claimed for it. The accepted candidate was human-reviewed
  with zero mechanical validation errors; 52 source-quoted person-state
  candidates were supported and two unknown placeholders were rejected.
- `readback/`: raw HTTP 200 responses for stream directory/detail, two unit
  pages, two group pages, locate, chapter directory/detail and source anchor.
  The unit pages cross ordinals 1→2 and group pages cross ordinals 1→2,
  demonstrating cursor continuation instead of a single-page smoke check.

### Scope boundary

This rerun is the requested real linked publication/readback chain for one
complete chapter. It does not claim that the broader LM-80 acceptance is
finished: background UI persistence, an additional edition, and the separate
deterministic 300+ capacity fixture were not rerun in this downstream-fix
turn. Existing evidence for those scopes remains in the neighboring acceptance
directories and is not overwritten or reinterpreted here.
