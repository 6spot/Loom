//! `PostgreSQL` implementation of Runtime Durable Work lease and retry ports.

use std::{fmt::Display, str::FromStr};

use loom_core::{EventId, SchemaRevision, TimelineId, WorkHandlerId, WorkId, WorldInstant};
use loom_runtime::{
    PersistenceFuture, PlatformTime, ReadError, WorkClaim, WorkError, WorkLease, WorkRecord,
    WorkStatus, WorkStore, WorldStore,
};
use serde_json::Value;
use sqlx::{Postgres, Row, Transaction};

use super::PgStorage;

type PgTransaction<'a> = Transaction<'a, Postgres>;

impl WorkStore for PgStorage {
    fn claim<'a>(
        &'a self,
        timeline_id: TimelineId,
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    ) -> PersistenceFuture<'a, Result<WorkClaim, WorkError>> {
        Box::pin(async move { claim_work(self, timeline_id, work_id, now, claimed_until).await })
    }

    fn retry<'a>(
        &'a self,
        claim: &'a WorkClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        last_error: Option<String>,
    ) -> PersistenceFuture<'a, Result<WorkRecord, WorkError>> {
        Box::pin(async move { retry_work(self, claim, now, available_at, last_error).await })
    }

    fn work(
        &self,
        timeline_id: TimelineId,
        work_id: WorkId,
    ) -> PersistenceFuture<'_, Result<Option<WorkRecord>, ReadError>> {
        Box::pin(async move {
            let snapshot = WorldStore::snapshot(self, timeline_id).await?;
            Ok(snapshot.works.into_iter().find(|work| work.id == work_id))
        })
    }
}

async fn claim_work(
    storage: &PgStorage,
    timeline_id: TimelineId,
    work_id: WorkId,
    now: PlatformTime,
    claimed_until: PlatformTime,
) -> Result<WorkClaim, WorkError> {
    let mut transaction = storage.pool.begin().await.map_err(work_sql_error)?;
    let mut work = locked_work(&mut transaction, timeline_id, work_id)
        .await?
        .ok_or_else(|| missing_work(&mut transaction, timeline_id, work_id))?;

    if !work.is_pending() {
        return Err(WorkError::NotPending {
            work_id,
            status: work.status,
        });
    }
    if now < work.available_at {
        return Err(WorkError::NotAvailable {
            work_id,
            available_at: work.available_at,
            now,
        });
    }
    if let Some(lease) = work.lease
        && now < lease.claimed_until()
    {
        return Err(WorkError::AlreadyClaimed {
            work_id,
            claimed_until: lease.claimed_until(),
        });
    }
    if claimed_until <= now {
        return Err(WorkError::InvalidLease {
            work_id,
            now,
            claimed_until,
        });
    }

    let next_fence = work
        .claim_generation
        .checked_add(1)
        .ok_or(WorkError::AttemptOverflow { work_id })?;
    let next_attempt = work
        .attempt_count
        .checked_add(1)
        .ok_or(WorkError::AttemptOverflow { work_id })?;
    sqlx::query(
        "UPDATE loom_work SET attempt_count = $3, claim_generation = $4::numeric, \
         lease_claimed_until = $5, lease_fence = $4::numeric \
         WHERE timeline_id = $1::uuid AND work_id = $2::uuid",
    )
    .bind(timeline_id.to_string())
    .bind(work_id.to_string())
    .bind(i64::from(next_attempt))
    .bind(next_fence.to_string())
    .bind(claimed_until.value())
    .execute(&mut *transaction)
    .await
    .map_err(work_sql_error)?;
    transaction.commit().await.map_err(work_sql_error)?;

    work.attempt_count = next_attempt;
    work.claim_generation = next_fence;
    work.lease = Some(WorkLease::new(claimed_until, next_fence));
    Ok(WorkClaim::new(
        timeline_id,
        work_id,
        claimed_until,
        next_fence,
    ))
}

async fn retry_work(
    storage: &PgStorage,
    claim: &WorkClaim,
    now: PlatformTime,
    available_at: PlatformTime,
    last_error: Option<String>,
) -> Result<WorkRecord, WorkError> {
    let timeline_id = claim.timeline_id();
    let work_id = claim.work_id();
    let mut transaction = storage.pool.begin().await.map_err(work_sql_error)?;
    let mut work = locked_work(&mut transaction, timeline_id, work_id)
        .await?
        .ok_or_else(|| missing_work(&mut transaction, timeline_id, work_id))?;
    validate_claim(&work, claim, now)?;

    sqlx::query(
        "UPDATE loom_work SET available_at = $3, last_error = $4, \
         lease_claimed_until = NULL, lease_fence = NULL \
         WHERE timeline_id = $1::uuid AND work_id = $2::uuid",
    )
    .bind(timeline_id.to_string())
    .bind(work_id.to_string())
    .bind(available_at.value())
    .bind(last_error.clone())
    .execute(&mut *transaction)
    .await
    .map_err(work_sql_error)?;
    transaction.commit().await.map_err(work_sql_error)?;

    work.available_at = available_at;
    work.last_error = last_error;
    work.lease = None;
    Ok(work)
}

async fn locked_work(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    work_id: WorkId,
) -> Result<Option<WorkRecord>, WorkError> {
    let row = sqlx::query(
        "SELECT work_id::text AS work_id, handler, schema_revision, payload, due_world_time, \
                causal_event_id::text AS causal_event_id, origin_work_id::text AS origin_work_id, \
                status, attempt_count, claim_generation::text AS claim_generation, available_at, \
                last_error, lease_claimed_until, lease_fence::text AS lease_fence \
         FROM loom_work WHERE timeline_id = $1::uuid AND work_id = $2::uuid FOR UPDATE",
    )
    .bind(timeline_id.to_string())
    .bind(work_id.to_string())
    .fetch_optional(&mut **transaction)
    .await
    .map_err(work_sql_error)?;
    row.map(|row| work_record(&row, timeline_id)).transpose()
}

fn validate_claim(work: &WorkRecord, claim: &WorkClaim, now: PlatformTime) -> Result<(), WorkError> {
    if !work.is_pending() {
        return Err(WorkError::NotPending {
            work_id: claim.work_id(),
            status: work.status,
        });
    }
    let Some(lease) = work.lease else {
        return Err(WorkError::MissingLease {
            work_id: claim.work_id(),
        });
    };
    if lease.fence() != claim.fence() || lease.claimed_until() != claim.claimed_until() {
        return Err(WorkError::StaleClaim {
            work_id: claim.work_id(),
            expected_fence: claim.fence(),
            actual_fence: Some(lease.fence()),
        });
    }
    if now >= lease.claimed_until() {
        return Err(WorkError::LeaseExpired {
            work_id: claim.work_id(),
            claimed_until: lease.claimed_until(),
            now,
        });
    }
    Ok(())
}

fn missing_work(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    work_id: WorkId,
) -> WorkError {
    let timeline_exists = futures_lite_block_on_timeline_exists(transaction, timeline_id);
    match timeline_exists {
        Ok(true) => WorkError::WorkNotFound {
            timeline_id,
            work_id,
        },
        Ok(false) => WorkError::TimelineNotFound { timeline_id },
        Err(error) => error,
    }
}

fn futures_lite_block_on_timeline_exists(
    _transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
) -> Result<bool, WorkError> {
    Err(WorkError::StorageUnavailable {
        message: format!(
            "internal PostgreSQL Work lookup bug while distinguishing Timeline {timeline_id}"
        ),
    })
}

fn work_record(row: &sqlx::postgres::PgRow, timeline_id: TimelineId) -> Result<WorkRecord, WorkError> {
    let work_id = parse_identity::<WorkId>(&row_string(row, "work_id")?, "WorkId")?;
    let attempt_count = u32::try_from(row_i64(row, "attempt_count")?)
        .map_err(|_| corrupt("attempt_count exceeds u32"))?;
    let lease_until: Option<i64> = row.try_get("lease_claimed_until").map_err(work_sql_error)?;
    let lease_fence: Option<String> = row.try_get("lease_fence").map_err(work_sql_error)?;
    let lease = match (lease_until, lease_fence) {
        (None, None) => None,
        (Some(until), Some(fence)) => Some(WorkLease::new(
            PlatformTime::new(until),
            parse_u64(&fence, "lease_fence")?,
        )),
        _ => return Err(corrupt("persisted Work lease columns disagree")),
    };
    Ok(WorkRecord {
        id: work_id,
        timeline_id,
        handler: WorkHandlerId::from(row_string(row, "handler")?),
        schema_revision: SchemaRevision::new(
            u32::try_from(row_i64(row, "schema_revision")?)
                .map_err(|_| corrupt("schema_revision exceeds u32"))?,
        ),
        payload: row_json(row, "payload")?,
        due_world_time: row
            .try_get::<Option<i64>, _>("due_world_time")
            .map_err(work_sql_error)?
            .map(WorldInstant::new),
        causal_event_id: optional_identity::<EventId>(row, "causal_event_id", "EventId")?,
        origin_work_id: optional_identity::<WorkId>(row, "origin_work_id", "WorkId")?,
        status: parse_status(&row_string(row, "status")?)?,
        attempt_count,
        claim_generation: parse_u64(&row_string(row, "claim_generation")?, "claim_generation")?,
        available_at: PlatformTime::new(row_i64(row, "available_at")?),
        last_error: row.try_get("last_error").map_err(work_sql_error)?,
        lease,
    })
}

fn parse_status(value: &str) -> Result<WorkStatus, WorkError> {
    match value {
        "pending" => Ok(WorkStatus::Pending),
        "completed" => Ok(WorkStatus::Completed),
        "cancelled" => Ok(WorkStatus::Cancelled),
        "dead" => Ok(WorkStatus::Dead),
        other => Err(corrupt(format!("invalid persisted Work status {other}"))),
    }
}

fn parse_identity<T>(value: &str, label: &str) -> Result<T, WorkError>
where
    T: FromStr,
    T::Err: Display,
{
    value
        .parse()
        .map_err(|error| corrupt(format!("invalid persisted {label}: {error}")))
}

fn optional_identity<T>(
    row: &sqlx::postgres::PgRow,
    column: &str,
    label: &str,
) -> Result<Option<T>, WorkError>
where
    T: FromStr,
    T::Err: Display,
{
    row.try_get::<Option<String>, _>(column)
        .map_err(work_sql_error)?
        .map(|value| parse_identity(&value, label))
        .transpose()
}

fn parse_u64(value: &str, label: &str) -> Result<u64, WorkError> {
    value
        .parse()
        .map_err(|error| corrupt(format!("invalid persisted {label}: {error}")))
}

fn row_string(row: &sqlx::postgres::PgRow, column: &str) -> Result<String, WorkError> {
    row.try_get(column).map_err(work_sql_error)
}

fn row_i64(row: &sqlx::postgres::PgRow, column: &str) -> Result<i64, WorkError> {
    row.try_get(column).map_err(work_sql_error)
}

fn row_json(row: &sqlx::postgres::PgRow, column: &str) -> Result<Value, WorkError> {
    row.try_get(column).map_err(work_sql_error)
}

fn corrupt(message: impl Into<String>) -> WorkError {
    WorkError::StorageUnavailable {
        message: message.into(),
    }
}

fn work_sql_error(error: sqlx::Error) -> WorkError {
    corrupt(format!("PostgreSQL Work operation failed: {error}"))
}
