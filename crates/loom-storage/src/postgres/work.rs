//! `PostgreSQL` implementation of Runtime Durable Work lease and retry ports.

use std::{fmt::Display, str::FromStr};

use loom_core::{EntityId, EventId, SchemaRevision, TimelineId, WorkId, WorldInstant};
use loom_runtime::{
    PersistenceFuture, PlatformTime, ReadError, WorkClaim, WorkError, WorkLease, WorkRecord,
    WorkStatus, WorkStore, WorkTarget, WorldStore,
};
use serde_json::Value;
use sqlx::{Postgres, Row, Transaction};

use super::PgStorage;

type PgTransaction<'a> = Transaction<'a, Postgres>;

const CLAIM_WORK_SQL: &str = include_str!("../../sql/work/claim.sql");
const RETRY_WORK_SQL: &str = include_str!("../../sql/work/retry.sql");
const SELECT_WORK_FOR_UPDATE_SQL: &str = include_str!("../../sql/work/select_for_update.sql");
const TIMELINE_EXISTS_SQL: &str = include_str!("../../sql/work/timeline_exists.sql");

impl WorkStore for PgStorage {
    fn claim(
        &self,
        timeline_id: TimelineId,
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    ) -> PersistenceFuture<'_, Result<WorkClaim, WorkError>> {
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
    let Some(mut work) = locked_work(&mut transaction, timeline_id, work_id).await? else {
        return Err(missing_work_error(&mut transaction, timeline_id, work_id).await);
    };

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
    sqlx::query(CLAIM_WORK_SQL)
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
    let Some(mut work) = locked_work(&mut transaction, timeline_id, work_id).await? else {
        return Err(missing_work_error(&mut transaction, timeline_id, work_id).await);
    };
    validate_claim(&work, claim, now)?;

    sqlx::query(RETRY_WORK_SQL)
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
    let row = sqlx::query(SELECT_WORK_FOR_UPDATE_SQL)
        .bind(timeline_id.to_string())
        .bind(work_id.to_string())
        .fetch_optional(&mut **transaction)
        .await
        .map_err(work_sql_error)?;
    row.map(|row| work_record(&row, timeline_id)).transpose()
}

fn validate_claim(
    work: &WorkRecord,
    claim: &WorkClaim,
    now: PlatformTime,
) -> Result<(), WorkError> {
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

async fn missing_work_error(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    work_id: WorkId,
) -> WorkError {
    let exists = sqlx::query_scalar::<_, bool>(TIMELINE_EXISTS_SQL)
        .bind(timeline_id.to_string())
        .fetch_one(&mut **transaction)
        .await;
    match exists {
        Ok(true) => WorkError::WorkNotFound {
            timeline_id,
            work_id,
        },
        Ok(false) => WorkError::TimelineNotFound { timeline_id },
        Err(error) => work_sql_error(error),
    }
}

fn work_record(
    row: &sqlx::postgres::PgRow,
    timeline_id: TimelineId,
) -> Result<WorkRecord, WorkError> {
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
        target: work_target(row)?,
        schema_revision: SchemaRevision::new(
            u32::try_from(row_i64(row, "schema_revision")?)
                .map_err(|_| corrupt("schema_revision exceeds u32"))?,
        ),
        payload: row_json(row, "payload")?,
        effective_due_world_time: WorldInstant::new(row_i64(row, "effective_due_world_time")?),
        logical_schedule_order: parse_u64(
            &row_string(row, "logical_schedule_order")?,
            "logical_schedule_order",
        )?,
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

fn work_target(row: &sqlx::postgres::PgRow) -> Result<WorkTarget, WorkError> {
    match row_string(row, "target_kind")?.as_str() {
        "capability_work" => Ok(WorkTarget::CapabilityWork {
            owner: row
                .try_get::<Option<String>, _>("target_owner")
                .map_err(work_sql_error)?,
            handler: row_string(row, "target_handler")?.into(),
        }),
        "agency_wake" => {
            let agent = row
                .try_get::<Option<String>, _>("target_agent_id")
                .map_err(work_sql_error)?
                .ok_or_else(|| corrupt("Agency Wake target has no Agent Entity"))?
                .parse::<EntityId>()
                .map_err(|error| corrupt(format!("invalid Agency Wake Agent Entity: {error}")))?;
            let cognition = row
                .try_get::<Option<String>, _>("target_cognition")
                .map_err(work_sql_error)?
                .ok_or_else(|| corrupt("Agency Wake target has no cognition requirement"))?;
            if cognition.is_empty() {
                return Err(corrupt(
                    "Agency Wake target has an empty cognition requirement",
                ));
            }
            Ok(WorkTarget::AgencyWake { agent, cognition })
        }
        other => Err(corrupt(format!(
            "invalid persisted Work target kind {other}"
        ))),
    }
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
