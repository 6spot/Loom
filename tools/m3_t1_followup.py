#!/usr/bin/env python3
from pathlib import Path

root = Path(__file__).resolve().parents[1]

path = root / "tests/loom-composition/subresolution.rs"
content = path.read_text()
marker = "impl WorldStore for CountingStore {\n"
insert = '''impl loom_runtime::WorldLifecycleStore for CountingStore {\n    fn create_world(\n        &self,\n        world_id: WorldId,\n        timeline_id: TimelineId,\n        initial_world_time: loom_core::WorldInstant,\n    ) -> PersistenceFuture<\n        '_,\n        Result<loom_runtime::WorldCreation, loom_runtime::LifecycleError>,\n    > {\n        loom_runtime::WorldLifecycleStore::create_world(\n            &self.inner,\n            world_id,\n            timeline_id,\n            initial_world_time,\n        )\n    }\n}\n\nimpl WorldStore for CountingStore {\n'''
if content.count(marker) != 1:
    raise SystemExit("subresolution.rs: expected one CountingStore WorldStore marker")
path.write_text(content.replace(marker, insert, 1))

for relative in [
    "crates/loom-runtime/src/identity.rs",
    "crates/loom-runtime/src/orchestration.rs",
]:
    target = root / relative
    text = target.read_text()
    if "UUIDv7" not in text:
        raise SystemExit(f"{relative}: expected UUIDv7 documentation marker")
    target.write_text(text.replace("UUIDv7", "`UUIDv7`"))

print("M3-T1 composition delegation and clippy doc fixes applied")
