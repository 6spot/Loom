# Timeline Logical Journal queries

These queries persist Runtime-owned Timeline Logical Commit records. The
journal is semantic Timeline history and is never represented as fake World
Events or populated with lease/retry/error metadata. `after_state_revision` is
the deterministic read order and is written in the same transaction as the
Timeline authority mutation.
