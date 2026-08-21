from pathlib import Path

composition = Path("tests/loom-composition/subresolution.rs")
text = composition.read_text()
start = text.index("impl WorkStore for CountingStore {")
end = text.index("fn request(input: Value)", start)
text = text[:start] + '''impl WorkStore for CountingStore {
    fn claim<'a>(
        &'a self,
        timeline_id: TimelineId,
        work_id: loom_core::WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    ) -> PersistenceFuture<'a, Result<WorkClaim, WorkError>> {
        WorkStore::claim(&self.inner, timeline_id, work_id, now, claimed_until)
    }

    fn retry<'a>(
        &'a self,
        claim: &'a WorkClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        last_error: Option<String>,
    ) -> PersistenceFuture<'a, Result<WorkRecord, WorkError>> {
        WorkStore::retry(&self.inner, claim, now, available_at, last_error)
    }

    fn work(
        &self,
        timeline_id: TimelineId,
        work_id: loom_core::WorkId,
    ) -> PersistenceFuture<'_, Result<Option<WorkRecord>, ReadError>> {
        WorkStore::work(&self.inner, timeline_id, work_id)
    }
}

''' + text[end:]
composition.write_text(text)

work_test = Path("crates/loom-storage/tests/postgres_work.rs")
text = work_test.read_text().replace("use serde_json::{Value, json};", "use serde_json::Value;", 1)
work_test.write_text(text)
