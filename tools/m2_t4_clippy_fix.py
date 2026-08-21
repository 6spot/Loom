from pathlib import Path

for name in [
    "crates/loom-runtime/src/persistence.rs",
    "crates/loom-runtime/src/orchestration.rs",
    "crates/loom-storage/src/in_memory.rs",
    "crates/loom-storage/src/postgres/work.rs",
    "tests/loom-composition/subresolution.rs",
]:
    path = Path(name)
    text = path.read_text()
    text = text.replace(
        "fn claim<'a>(\n        &'a self,",
        "fn claim(\n        &self,",
    )
    text = text.replace(
        ") -> PersistenceFuture<'a, Result<WorkClaim, WorkError>> {",
        ") -> PersistenceFuture<'_, Result<WorkClaim, WorkError>> {",
    )
    text = text.replace(
        ") -> PersistenceFuture<'a, Result<WorkClaim, WorkError>>;",
        ") -> PersistenceFuture<'_, Result<WorkClaim, WorkError>>;",
    )
    path.write_text(text)
