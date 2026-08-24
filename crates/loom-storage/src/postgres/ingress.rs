//! `PostgreSQL` implementation of durable Ingress operational state.

use loom_core::ExecutionSessionId;
use loom_runtime::{
    IdempotencyConflict, IngressAcceptance, IngressClaim, IngressCompletion, IngressError,
    IngressId, IngressLease, IngressOperationalRecord, IngressReceipt, IngressStatus, IngressStore,
    IngressSubmission, IngressTechnicalFailure, PersistenceFuture, PlatformTime,
};
use serde_json::Value;
use sqlx::{Postgres, Row, Transaction};

use super::PgStorage;

type PgTransaction<'a> = Transaction<'a, Postgres>;

const ACCEPT_INGRESS_SQL: &str = include_str!("../../sql/ingress/accept.sql");
const READ_INGRESS_SQL: &str = include_str!("../../sql/ingress/read.sql");
const LIST_RECOVERABLE_INGRESS_SQL: &str = include_str!("../../sql/ingress/list_recoverable.sql");
const SELECT_INGRESS_FOR_UPDATE_SQL: &str = include_str!("../../sql/ingress/select_for_update.sql");
const SELECT_INGRESS_BY_KEY_SQL: &str = include_str!("../../sql/ingress/select_by_key.sql");
const UPDATE_INGRESS_CLAIM_SQL: &str = include_str!("../../sql/ingress/update_claim.sql");
const UPDATE_INGRESS_RETRY_SQL: &str = include_str!("../../sql/ingress/update_retry.sql");
const UPDATE_INGRESS_COMPLETE_SQL: &str = include_str!("../../sql/ingress/update_complete.sql");
const UPDATE_INGRESS_FAIL_SQL: &str = include_str!("../../sql/ingress/update_fail.sql");

impl IngressStore for PgStorage {
    fn accept(
        &self,
        submission: IngressSubmission,
    ) -> PersistenceFuture<'_, Result<IngressAcceptance, IngressError>> {
        Box::pin(async move { accept_ingress(self, submission).await })
    }

    fn ingress(
        &self,
        ingress_id: IngressId,
    ) -> PersistenceFuture<'_, Result<IngressOperationalRecord, IngressError>> {
        Box::pin(async move { read_ingress(self, ingress_id).await })
    }

    fn list_recoverable(
        &self,
        now: PlatformTime,
        limit: usize,
    ) -> PersistenceFuture<'_, Result<Vec<IngressId>, IngressError>> {
        Box::pin(async move { list_recoverable_ingress(self, now, limit).await })
    }

    fn claim(
        &self,
        ingress_id: IngressId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    ) -> PersistenceFuture<'_, Result<IngressClaim, IngressError>> {
        Box::pin(async move { claim_ingress(self, ingress_id, now, claimed_until).await })
    }

    fn retry<'a>(
        &'a self,
        claim: &'a IngressClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        failure: IngressTechnicalFailure,
    ) -> PersistenceFuture<'a, Result<IngressOperationalRecord, IngressError>> {
        Box::pin(async move { retry_ingress(self, claim, now, available_at, failure).await })
    }

    fn complete<'a>(
        &'a self,
        claim: &'a IngressClaim,
        session_id: ExecutionSessionId,
        completion: IngressCompletion,
        completed_at: PlatformTime,
    ) -> PersistenceFuture<'a, Result<IngressOperationalRecord, IngressError>> {
        Box::pin(async move {
            complete_ingress(self, claim, session_id, completion, completed_at).await
        })
    }

    fn fail<'a>(
        &'a self,
        claim: &'a IngressClaim,
        completed_at: PlatformTime,
        failure: IngressTechnicalFailure,
    ) -> PersistenceFuture<'a, Result<IngressOperationalRecord, IngressError>> {
        Box::pin(async move { fail_ingress(self, claim, completed_at, failure).await })
    }
}

async fn accept_ingress(
    storage: &PgStorage,
    submission: IngressSubmission,
) -> Result<IngressAcceptance, IngressError> {
    let accepted = IngressOperationalRecord::accepted(submission.clone());
    let mut transaction = storage.pool.begin().await.map_err(sql_ingress_error)?;
    let inserted = sqlx::query(ACCEPT_INGRESS_SQL)
        .bind(accepted.ingress_id().as_str())
        .bind(accepted.idempotency_scope())
        .bind(accepted.idempotency_key().as_str())
        .bind(accepted.request_fingerprint())
        .bind(&accepted.submission.envelope.provenance.source)
        .bind(
            accepted
                .submission
                .envelope
                .provenance
                .external_id
                .as_deref(),
        )
        .bind(accepted.submission.envelope.provenance.metadata.clone())
        .bind(accepted.submission.envelope.target.world_id.to_string())
        .bind(accepted.submission.envelope.target.timeline_id.to_string())
        .bind(
            accepted
                .submission
                .envelope
                .authorization
                .as_value()
                .clone(),
        )
        .bind(
            accepted
                .submission
                .envelope
                .time_metadata
                .source_time
                .as_deref(),
        )
        .bind(
            accepted
                .submission
                .envelope
                .time_metadata
                .platform_time
                .as_deref(),
        )
        .bind(accepted.submission.received_at.value())
        .bind(
            serde_json::to_value(&accepted.submission.envelope.invocation)
                .map_err(serialization_error)?,
        )
        .bind(status_name(&accepted.status))
        .bind(i64::from(accepted.attempt_count))
        .bind(accepted.claim_fence.to_string())
        .bind(accepted.available_at.value())
        .bind(None::<i64>)
        .bind(None::<String>)
        .bind(None::<String>)
        .bind(None::<String>)
        .bind(None::<String>)
        .bind(serde_json::json!([]))
        .bind(None::<Value>)
        .bind(None::<i64>)
        .bind(serde_json::to_value(&accepted).map_err(serialization_error)?)
        .fetch_optional(&mut *transaction)
        .await;
    let inserted = match inserted {
        Ok(row) => row,
        Err(error) if super::is_unique_violation(&error) => {
            return Err(IngressError::IngressAlreadyExists {
                ingress_id: submission.ingress_id().clone(),
            });
        }
        Err(error) => return Err(sql_ingress_error(error)),
    };

    if inserted.is_some() {
        transaction.commit().await.map_err(sql_ingress_error)?;
        return Ok(IngressAcceptance::accepted(IngressReceipt::new(
            submission.ingress_id().clone(),
            submission.idempotency_key().clone(),
        )));
    }

    let existing = sqlx::query(SELECT_INGRESS_BY_KEY_SQL)
        .bind(submission.idempotency_scope.as_str())
        .bind(submission.idempotency_key().as_str())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(sql_ingress_error)?
        .ok_or_else(|| IngressError::StorageUnavailable {
            message: "Ingress idempotency conflict disappeared before read".to_owned(),
        })
        .and_then(|row| persisted_record(&row))?;
    transaction.commit().await.map_err(sql_ingress_error)?;
    if existing.request_fingerprint() == submission.request_fingerprint {
        return Ok(IngressAcceptance::deduplicated(IngressReceipt::new(
            existing.ingress_id().clone(),
            submission.idempotency_key().clone(),
        )));
    }
    Ok(IngressAcceptance::conflict(IdempotencyConflict::new(
        submission.idempotency_key().clone(),
        existing.ingress_id().clone(),
        existing.request_fingerprint(),
        submission.request_fingerprint,
    )))
}

async fn read_ingress(
    storage: &PgStorage,
    ingress_id: IngressId,
) -> Result<IngressOperationalRecord, IngressError> {
    let row = sqlx::query(READ_INGRESS_SQL)
        .bind(ingress_id.as_str())
        .fetch_optional(&storage.pool)
        .await
        .map_err(sql_ingress_error)?
        .ok_or(IngressError::IngressNotFound { ingress_id })?;
    persisted_record(&row)
}

async fn list_recoverable_ingress(
    storage: &PgStorage,
    now: PlatformTime,
    limit: usize,
) -> Result<Vec<IngressId>, IngressError> {
    let limit = i64::try_from(limit.min(1024)).map_err(|_| IngressError::StorageUnavailable {
        message: "Ingress recovery limit is outside the supported range".to_owned(),
    })?;
    let rows = sqlx::query(LIST_RECOVERABLE_INGRESS_SQL)
        .bind(now.value())
        .bind(limit)
        .fetch_all(&storage.pool)
        .await
        .map_err(sql_ingress_error)?;
    rows.into_iter()
        .map(|row| {
            row.try_get::<String, _>("ingress_id")
                .map(IngressId::from)
                .map_err(sql_ingress_error)
        })
        .collect()
}

async fn claim_ingress(
    storage: &PgStorage,
    ingress_id: IngressId,
    now: PlatformTime,
    claimed_until: PlatformTime,
) -> Result<IngressClaim, IngressError> {
    let mut transaction = storage.pool.begin().await.map_err(sql_ingress_error)?;
    let mut record = locked_record(&mut transaction, &ingress_id).await?;
    validate_claimable(&record, &ingress_id, now, claimed_until)?;
    let next_fence =
        record
            .claim_fence
            .checked_add(1)
            .ok_or_else(|| IngressError::AttemptOverflow {
                ingress_id: ingress_id.clone(),
            })?;
    let next_attempt =
        record
            .attempt_count
            .checked_add(1)
            .ok_or_else(|| IngressError::AttemptOverflow {
                ingress_id: ingress_id.clone(),
            })?;
    record.status = IngressStatus::Processing;
    record.attempt_count = next_attempt;
    record.claim_fence = next_fence;
    record.lease = Some(IngressLease::new(claimed_until, next_fence));
    let encoded = serde_json::to_value(&record).map_err(serialization_error)?;
    let updated = sqlx::query(UPDATE_INGRESS_CLAIM_SQL)
        .bind(ingress_id.as_str())
        .bind(status_name(&record.status))
        .bind(i64::from(next_attempt))
        .bind(next_fence.to_string())
        .bind(claimed_until.value())
        .bind(encoded)
        .execute(&mut *transaction)
        .await
        .map_err(sql_ingress_error)?;
    if updated.rows_affected() != 1 {
        return Err(IngressError::StaleClaim {
            ingress_id,
            expected_fence: next_fence,
            actual_fence: Some(record.claim_fence),
        });
    }
    transaction.commit().await.map_err(sql_ingress_error)?;
    Ok(IngressClaim::new(
        ingress_id,
        claimed_until,
        next_fence,
        next_attempt,
    ))
}

async fn retry_ingress(
    storage: &PgStorage,
    claim: &IngressClaim,
    now: PlatformTime,
    available_at: PlatformTime,
    failure: IngressTechnicalFailure,
) -> Result<IngressOperationalRecord, IngressError> {
    let mut transaction = storage.pool.begin().await.map_err(sql_ingress_error)?;
    let mut record = locked_record(&mut transaction, claim.ingress_id()).await?;
    validate_current_claim(&record, claim, now)?;
    record.status = IngressStatus::Retryable(failure.clone());
    record.available_at = available_at;
    record.last_error = Some(failure.clone());
    record.lease = None;
    let encoded = serde_json::to_value(&record).map_err(serialization_error)?;
    let updated = sqlx::query(UPDATE_INGRESS_RETRY_SQL)
        .bind(claim.ingress_id().as_str())
        .bind(status_name(&record.status))
        .bind(available_at.value())
        .bind(failure.code.as_str())
        .bind(failure.message.as_str())
        .bind(encoded)
        .bind(claim.fence().to_string())
        .bind(claim.claimed_until().value())
        .execute(&mut *transaction)
        .await
        .map_err(sql_ingress_error)?;
    if updated.rows_affected() != 1 {
        return Err(stale_claim_error(claim, record.lease));
    }
    transaction.commit().await.map_err(sql_ingress_error)?;
    Ok(record)
}

async fn complete_ingress(
    storage: &PgStorage,
    claim: &IngressClaim,
    session_id: ExecutionSessionId,
    completion: IngressCompletion,
    completed_at: PlatformTime,
) -> Result<IngressOperationalRecord, IngressError> {
    let mut transaction = storage.pool.begin().await.map_err(sql_ingress_error)?;
    let mut record = locked_record(&mut transaction, claim.ingress_id()).await?;
    validate_current_claim(&record, claim, completed_at)?;
    record.completed_event_refs = match &completion {
        IngressCompletion::Committed { event_refs, .. } => event_refs.clone(),
        IngressCompletion::NoChange | IngressCompletion::Rejected(_) => Vec::new(),
    };
    record.status = IngressStatus::Completed(completion.clone());
    record.completed_session_id = Some(session_id);
    record.completed_at = Some(completed_at);
    record.last_error = None;
    record.lease = None;
    let encoded = serde_json::to_value(&record).map_err(serialization_error)?;
    let event_refs =
        serde_json::to_value(&record.completed_event_refs).map_err(serialization_error)?;
    let completion = serde_json::to_value(&completion).map_err(serialization_error)?;
    let updated = sqlx::query(UPDATE_INGRESS_COMPLETE_SQL)
        .bind(claim.ingress_id().as_str())
        .bind(status_name(&record.status))
        .bind(session_id.to_string())
        .bind(event_refs)
        .bind(completion)
        .bind(completed_at.value())
        .bind(encoded)
        .bind(claim.fence().to_string())
        .bind(claim.claimed_until().value())
        .execute(&mut *transaction)
        .await
        .map_err(sql_ingress_error)?;
    if updated.rows_affected() != 1 {
        return Err(stale_claim_error(claim, record.lease));
    }
    transaction.commit().await.map_err(sql_ingress_error)?;
    Ok(record)
}

async fn fail_ingress(
    storage: &PgStorage,
    claim: &IngressClaim,
    completed_at: PlatformTime,
    failure: IngressTechnicalFailure,
) -> Result<IngressOperationalRecord, IngressError> {
    let mut transaction = storage.pool.begin().await.map_err(sql_ingress_error)?;
    let mut record = locked_record(&mut transaction, claim.ingress_id()).await?;
    validate_current_claim(&record, claim, completed_at)?;
    record.status = IngressStatus::Failed(failure.clone());
    record.last_error = Some(failure.clone());
    record.completed_at = Some(completed_at);
    record.lease = None;
    let encoded = serde_json::to_value(&record).map_err(serialization_error)?;
    let updated = sqlx::query(UPDATE_INGRESS_FAIL_SQL)
        .bind(claim.ingress_id().as_str())
        .bind(status_name(&record.status))
        .bind(failure.code.as_str())
        .bind(failure.message.as_str())
        .bind(completed_at.value())
        .bind(encoded)
        .bind(claim.fence().to_string())
        .bind(claim.claimed_until().value())
        .execute(&mut *transaction)
        .await
        .map_err(sql_ingress_error)?;
    if updated.rows_affected() != 1 {
        return Err(stale_claim_error(claim, record.lease));
    }
    transaction.commit().await.map_err(sql_ingress_error)?;
    Ok(record)
}

async fn locked_record(
    transaction: &mut PgTransaction<'_>,
    ingress_id: &IngressId,
) -> Result<IngressOperationalRecord, IngressError> {
    let row = sqlx::query(SELECT_INGRESS_FOR_UPDATE_SQL)
        .bind(ingress_id.as_str())
        .fetch_optional(&mut **transaction)
        .await
        .map_err(sql_ingress_error)?
        .ok_or_else(|| IngressError::IngressNotFound {
            ingress_id: ingress_id.clone(),
        })?;
    persisted_record(&row)
}

fn persisted_record(row: &sqlx::postgres::PgRow) -> Result<IngressOperationalRecord, IngressError> {
    let value: Value = row.try_get("record").map_err(sql_ingress_error)?;
    serde_json::from_value(value).map_err(serialization_error)
}

fn validate_claimable(
    record: &IngressOperationalRecord,
    ingress_id: &IngressId,
    now: PlatformTime,
    claimed_until: PlatformTime,
) -> Result<(), IngressError> {
    if matches!(
        record.status,
        IngressStatus::Completed(_) | IngressStatus::Failed(_)
    ) {
        return Err(IngressError::NotClaimable {
            ingress_id: ingress_id.clone(),
            status: record.status.clone(),
        });
    }
    if matches!(record.status, IngressStatus::Processing) && record.lease.is_none() {
        return Err(IngressError::MissingLease {
            ingress_id: ingress_id.clone(),
        });
    }
    if now < record.available_at {
        return Err(IngressError::NotAvailable {
            ingress_id: ingress_id.clone(),
            available_at: record.available_at,
            now,
        });
    }
    if let Some(lease) = record.lease
        && now < lease.claimed_until()
    {
        return Err(IngressError::AlreadyClaimed {
            ingress_id: ingress_id.clone(),
            claimed_until: lease.claimed_until(),
        });
    }
    if claimed_until <= now {
        return Err(IngressError::InvalidLease {
            ingress_id: ingress_id.clone(),
            now,
            claimed_until,
        });
    }
    Ok(())
}

fn validate_current_claim(
    record: &IngressOperationalRecord,
    claim: &IngressClaim,
    now: PlatformTime,
) -> Result<(), IngressError> {
    if !matches!(record.status, IngressStatus::Processing) {
        return Err(IngressError::NotClaimable {
            ingress_id: claim.ingress_id().clone(),
            status: record.status.clone(),
        });
    }
    let Some(lease) = record.lease else {
        return Err(IngressError::MissingLease {
            ingress_id: claim.ingress_id().clone(),
        });
    };
    if lease.fence() != claim.fence() || lease.claimed_until() != claim.claimed_until() {
        return Err(IngressError::StaleClaim {
            ingress_id: claim.ingress_id().clone(),
            expected_fence: claim.fence(),
            actual_fence: Some(lease.fence()),
        });
    }
    if now >= lease.claimed_until() {
        return Err(IngressError::LeaseExpired {
            ingress_id: claim.ingress_id().clone(),
            claimed_until: lease.claimed_until(),
            now,
        });
    }
    Ok(())
}

fn stale_claim_error(claim: &IngressClaim, lease: Option<IngressLease>) -> IngressError {
    IngressError::StaleClaim {
        ingress_id: claim.ingress_id().clone(),
        expected_fence: claim.fence(),
        actual_fence: lease.map(IngressLease::fence),
    }
}

fn status_name(status: &IngressStatus) -> &'static str {
    match status {
        IngressStatus::Accepted => "accepted",
        IngressStatus::Processing => "processing",
        IngressStatus::Completed(_) => "completed",
        IngressStatus::Retryable(_) => "retryable",
        IngressStatus::Failed(_) => "failed",
    }
}

fn serialization_error(error: serde_json::Error) -> IngressError {
    IngressError::StorageUnavailable {
        message: format!("Ingress persistence serialization failed: {error}"),
    }
}

fn sql_ingress_error(error: sqlx::Error) -> IngressError {
    IngressError::StorageUnavailable {
        message: format!("PostgreSQL Ingress persistence failed: {error}"),
    }
}
