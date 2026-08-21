from pathlib import Path
import re

path = Path("crates/loom-storage/src/postgres/commit.rs")
text = path.read_text()
text = text.replace(
    "use loom_protocol::{NewWork, ProposedEvent, WorkMutation, WorkSchedule};\nuse loom_runtime::{\n",
    "use loom_runtime::{\n",
    1,
)
text = text.replace(
    "    CommitError, CommitResult, CommitStore, CommittedEvent, PersistenceFuture, PlatformTime,\n    ValidatedResolution, WorkClaim, WorkError, WorkStatus,\n",
    "    CommitError, CommitResult, CommitStore, CommittedEvent, PersistenceFuture, PlatformTime,\n    ProposedEvent, ValidatedResolution, WorkClaim, WorkError, WorkMutation, WorkStatus,\n",
    1,
)
replacement = r'''async fn apply_work_mutation(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    mutation: &WorkMutation,
    now: PlatformTime,
) -> Result<(), CommitError> {
    match mutation {
        WorkMutation::Schedule(work) => {
            if work.timeline_id != timeline_id {
                return Err(WorkError::TimelineMismatch {
                    expected: timeline_id,
                    actual: work.timeline_id,
                }
                .into());
            }
            if work_exists(transaction, timeline_id, work.id).await? {
                return Err(WorkError::DuplicateWork { work_id: work.id }.into());
            }
            if let Some(event_id) = work.causal_event_id
                && !event_exists(transaction, timeline_id, event_id).await?
            {
                return Err(WorkError::MissingCausalEvent {
                    work_id: work.id,
                    event_id,
                }
                .into());
            }
            if let Some(origin_work_id) = work.origin_work_id
                && !work_exists(transaction, timeline_id, origin_work_id).await?
            {
                return Err(WorkError::WorkNotFound {
                    timeline_id,
                    work_id: origin_work_id,
                }
                .into());
            }
            let record = loom_runtime::WorkRecord::from_new_work(work, now);
            sqlx::query(
                "INSERT INTO loom_work \
                 (timeline_id, work_id, handler, schema_revision, payload, due_world_time, causal_event_id, \
                  origin_work_id, status, attempt_count, claim_generation, available_at, last_error, \
                  lease_claimed_until, lease_fence) \
                 VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6, $7::uuid, $8::uuid, 'pending', 0, 0, $9, \
                         NULL, NULL, NULL)",
            )
            .bind(timeline_id.to_string())
            .bind(work.id.to_string())
            .bind(work.handler.as_str())
            .bind(i64::from(work.schema_revision.value()))
            .bind(work.payload.clone())
            .bind(record.due_world_time.map(loom_core::WorldInstant::value))
            .bind(work.causal_event_id.map(|id| id.to_string()))
            .bind(work.origin_work_id.map(|id| id.to_string()))
            .bind(now.value())
            .execute(&mut **transaction)
            .await
            .map_err(storage_error)?;
            Ok(())
        }
        WorkMutation::Cancel(work_id) => cancel_work(transaction, timeline_id, *work_id).await,
    }
}

'''
text, count = re.subn(
    r"async fn apply_work_mutation\(.*?\nasync fn cancel_work\(",
    replacement + "async fn cancel_work(",
    text,
    count=1,
    flags=re.S,
)
if count != 1:
    raise SystemExit("work mutation block not found")
text = text.replace("    query: &str,\n", "    query: &'static str,\n", 1)
text = text.replace(
    "    if database_code(&error) == Some(\"23505\") {",
    "    if database_code(&error).as_deref() == Some(\"23505\") {",
    1,
)
text = text.replace(
    "    match database_code(&error) {\n        Some(\"23503\" | \"23505\" | \"23514\") => invalid_effect(event_id, error.to_string()),",
    "    match database_code(&error).as_deref() {\n        Some(\"23503\" | \"23505\" | \"23514\") => invalid_effect(event_id, error.to_string()),",
    1,
)
text = text.replace(
    "fn database_code(error: &sqlx::Error) -> Option<&str> {\n    error.as_database_error()?.code().as_deref()\n}",
    "fn database_code(error: &sqlx::Error) -> Option<std::borrow::Cow<'_, str>> {\n    error.as_database_error()?.code()\n}",
    1,
)
path.write_text(text)
