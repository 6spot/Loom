# Current chapter assembly

The active assembly entry point is
`apps/chronicle/persistence/assembly.py:assemble_chapters`. It consumes one
accepted `chronicle.chapter-artifact / 0.4` for every chapter in the immutable
T03 plan, remaps local references into one revision namespace, preserves
source evidence, and fails closed on missing, duplicate, mixed, or tampered
inputs.

Assembly is deterministic and model-free. Its output is committed before the
worker advances to identity review and publication. The old C1 chunk assembly
entry point and its fake-worker hook were removed; see
[staged-chapter-production.md](staged-chapter-production.md) and
[worker.md](worker.md) for the complete current lifecycle.
