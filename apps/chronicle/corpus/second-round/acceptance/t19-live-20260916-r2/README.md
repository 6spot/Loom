## T19 strict-provider rerun evidence (2026-09-16)

This directory records the same real-data T19 flow rerun against candidate commit
`fde19a935198d37a40bcb3ed109b08a389636c3a` after the extraction provider output
contract fix. The earlier candidate evidence remains in
`../t19-live-20260916/`; this rerun does not overwrite or reinterpret it.

### What changed and what the rerun proves

The staged 0.4 worker now fails closed unless the extraction provider carries the
exact strict chapter-production JSON Schema. Structured providers are given the
provider-compatible projection of the local step schema (explicit types, closed
objects and no composition/unsupported keywords); local parsing and semantic
validation remain authoritative. The real configured gateway accepted that
extraction contract in this rerun: there was no provider HTTP 400/schema rejection.

The fresh 《先主傳》 child reached a completed, locally validated extraction on
attempt 2 after one semantic validation retry. Its saved output contains 44
entities, 22 events, 18 claims, 68 nested entity mentions, 8 top-level mentions,
5 person-state sections and 84 source records. Nested mentions contain only their
staged `text` field, while event places and participants use temporary entity
references, demonstrating the output ownership boundary that the contract fixes.

### Real-data run

The run used a fresh database and the configured real provider with the global
1,800-second model timeout. Credentials are intentionally omitted. The two source
revisions were:

- 《三國志·蜀書·先主傳》 — 37,474 bytes, 12,572 normalized characters,
  Wikisource oldid `2583378`, source SHA-256
  `ea40a7087560fe9e693e6f81cb7d1689704f888a40b5b8a8bf7169ec272994e8`.
- 《三國志·吳書·周瑜傳》 — 14,996 bytes, 5,018 normalized characters,
  Wikisource oldid `2387393`, source SHA-256
  `63db082c4e763be3b56c87cb56e2bed904af5325e9a498b07d932d3b5af1f43e`.

Four jobs are recorded in `t19-live-execution.json`: two initial Luna-profile
jobs and two fresh Sol-profile child jobs with the step selections swapped.

| Job | Result | Step evidence |
| --- | --- | --- |
| `initial_xianzhu-liubei` | failed at extraction | translation passed; extraction attempts had 17 and 9 validation errors |
| `initial_zhou-yu` | failed at extraction | translation timed out; extraction attempts had 9 and 2 validation errors |
| `fresh_xianzhu-liubei` | failed at linking | translation passed; extraction attempt 2 passed validation; linking timed out |
| `fresh_zhou-yu` | failed at extraction | translation and extraction timed out |

The successful extraction, its preceding invalid candidate, the timeout records,
and all other raw model outputs are retained under `model-outputs/`. No chapter
reached comparison/exception review, acceptance, publication, continuous
multi-fragment readback, background binding, or the 12-item content-check suite in
this rerun. T19 therefore remains incomplete; these records are an honest
post-fix provider-contract and partial real-data validation, not a content-quality
or publication pass.
