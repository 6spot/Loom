//! `PostgreSQL` implementation of Runtime Execution Session persistence.

use loom_core::ExecutionSessionId;
use loom_runtime::{
    CommitProvenance, EntropyEvidence, ExecutionSession, ExecutionSessionStatus,
    ExecutionSessionStore, IngressCompletion, PersistenceFuture, PlatformTime, SessionError,
};
use serde_json::Value;
use sqlx::Row;

use super::PgStorage;

const START_SESSION_SQL: &str = include_str!("../../sql/session/start.sql");
const FINISH_SESSION_SQL: &str = include_str!("../../sql/session/finish.sql");
const PREPARE_PROVENANCE_SQL: &str = include_str!("../../sql/session/prepare_provenance.sql");
const READ_SESSION_SQL: &str = include_str!("../../sql/session/read.sql");
const LIST_SESSIONS_SQL: &str = include_str!("../../sql/session/list.sql");

impl ExecutionSessionStore for PgStorage {
    fn start_session(
        &self,
        session: ExecutionSession,
    ) -> PersistenceFuture<'_, Result<(), SessionError>> {
        Box::pin(async move { start_session(self, session).await })
    }

    fn finish_session(
        &self,
        session_id: ExecutionSessionId,
        status: ExecutionSessionStatus,
        ended_at: PlatformTime,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        Box::pin(async move { finish_session(self, session_id, status, ended_at).await })
    }

    fn finish_session_with_entropy(
        &self,
        session_id: ExecutionSessionId,
        status: ExecutionSessionStatus,
        ended_at: PlatformTime,
        entropy_evidence: EntropyEvidence,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        Box::pin(async move {
            finish_session_with_entropy(self, session_id, status, ended_at, entropy_evidence).await
        })
    }

    fn finish_session_with_ingress_completion(
        &self,
        session_id: ExecutionSessionId,
        status: ExecutionSessionStatus,
        ended_at: PlatformTime,
        entropy_evidence: EntropyEvidence,
        completion: IngressCompletion,
        provenance: Option<CommitProvenance>,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        Box::pin(async move {
            finish_session_with_ingress_completion(
                self,
                session_id,
                status,
                ended_at,
                entropy_evidence,
                completion,
                provenance,
            )
            .await
        })
    }

    fn record_ingress_provenance(
        &self,
        session_id: ExecutionSessionId,
        provenance: CommitProvenance,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        Box::pin(async move { record_ingress_provenance(self, session_id, provenance).await })
    }

    fn read_session(
        &self,
        session_id: ExecutionSessionId,
    ) -> PersistenceFuture<'_, Result<ExecutionSession, SessionError>> {
        Box::pin(async move { read_session(self, session_id).await })
    }

    fn list_sessions(&self) -> PersistenceFuture<'_, Result<Vec<ExecutionSession>, SessionError>> {
        Box::pin(async move { list_sessions(self).await })
    }
}

async fn start_session(storage: &PgStorage, session: ExecutionSession) -> Result<(), SessionError> {
    if session.status() != ExecutionSessionStatus::Started {
        return Err(SessionError::InvalidTransition {
            session_id: session.id(),
            from: session.status(),
            to: ExecutionSessionStatus::Started,
        });
    }
    let record =
        serde_json::to_value(&session).map_err(|error| SessionError::StorageUnavailable {
            message: format!("Execution Session serialization failed: {error}"),
        })?;
    let result = sqlx::query(START_SESSION_SQL)
        .bind(session.id().to_string())
        .bind(session.assembly().world_id().to_string())
        .bind(session.assembly().timeline_id().to_string())
        .bind(session_origin(session.origin()))
        .bind(session_status(session.status()))
        .bind(session.started_at().value())
        .bind(record)
        .execute(&storage.pool)
        .await;
    if let Err(error) = result {
        if super::is_unique_violation(&error) {
            return Err(SessionError::SessionAlreadyExists {
                session_id: session.id(),
            });
        }
        return Err(sql_session_error(error));
    }
    Ok(())
}

async fn finish_session(
    storage: &PgStorage,
    session_id: ExecutionSessionId,
    status: ExecutionSessionStatus,
    ended_at: PlatformTime,
) -> Result<ExecutionSession, SessionError> {
    finish_session_inner(storage, session_id, status, ended_at, None, None, None).await
}

async fn finish_session_with_entropy(
    storage: &PgStorage,
    session_id: ExecutionSessionId,
    status: ExecutionSessionStatus,
    ended_at: PlatformTime,
    entropy_evidence: EntropyEvidence,
) -> Result<ExecutionSession, SessionError> {
    finish_session_inner(
        storage,
        session_id,
        status,
        ended_at,
        Some(entropy_evidence),
        None,
        None,
    )
    .await
}

async fn finish_session_with_ingress_completion(
    storage: &PgStorage,
    session_id: ExecutionSessionId,
    status: ExecutionSessionStatus,
    ended_at: PlatformTime,
    entropy_evidence: EntropyEvidence,
    completion: IngressCompletion,
    provenance: Option<CommitProvenance>,
) -> Result<ExecutionSession, SessionError> {
    if storage.take_test_ingress_finalization_failure() {
        return Err(SessionError::StorageUnavailable {
            message: "test Ingress finalization interruption".to_owned(),
        });
    }
    finish_session_inner(
        storage,
        session_id,
        status,
        ended_at,
        Some(entropy_evidence),
        Some(completion),
        provenance,
    )
    .await
}

async fn finish_session_inner(
    storage: &PgStorage,
    session_id: ExecutionSessionId,
    status: ExecutionSessionStatus,
    ended_at: PlatformTime,
    entropy_evidence: Option<EntropyEvidence>,
    ingress_completion: Option<IngressCompletion>,
    provenance: Option<CommitProvenance>,
) -> Result<ExecutionSession, SessionError> {
    let current = read_session(storage, session_id).await?;
    if current.status() != ExecutionSessionStatus::Started {
        if current.status() == status {
            return Ok(current);
        }
        return Err(SessionError::InvalidTransition {
            session_id,
            from: current.status(),
            to: status,
        });
    }
    let finished = match entropy_evidence {
        Some(entropy_evidence) => match ingress_completion {
            Some(completion) => current.finish_with_ingress_completion(
                status,
                ended_at,
                entropy_evidence,
                completion,
                provenance,
            )?,
            None => current.finish_with_entropy(status, ended_at, entropy_evidence)?,
        },
        None => match ingress_completion {
            Some(_) => {
                return Err(SessionError::IngressCompletionUnavailable { session_id });
            }
            None => current.finish(status, ended_at)?,
        },
    };
    let record =
        serde_json::to_value(&finished).map_err(|error| SessionError::StorageUnavailable {
            message: format!("Execution Session serialization failed: {error}"),
        })?;
    let result = sqlx::query(FINISH_SESSION_SQL)
        .bind(session_id.to_string())
        .bind(session_status(status))
        .bind(ended_at.value())
        .bind(record)
        .execute(&storage.pool)
        .await
        .map_err(sql_session_error)?;
    if result.rows_affected() == 0 {
        let actual = read_session(storage, session_id).await?;
        if actual.status() == status {
            return Ok(actual);
        }
        return Err(SessionError::InvalidTransition {
            session_id,
            from: actual.status(),
            to: status,
        });
    }
    Ok(finished)
}

async fn record_ingress_provenance(
    storage: &PgStorage,
    session_id: ExecutionSessionId,
    provenance: CommitProvenance,
) -> Result<ExecutionSession, SessionError> {
    let current = read_session(storage, session_id).await?;
    let prepared = current.with_commit_provenance(provenance)?;
    let record =
        serde_json::to_value(&prepared).map_err(|error| SessionError::StorageUnavailable {
            message: format!("Execution Session serialization failed: {error}"),
        })?;
    let result = sqlx::query(PREPARE_PROVENANCE_SQL)
        .bind(session_id.to_string())
        .bind(record)
        .execute(&storage.pool)
        .await
        .map_err(sql_session_error)?;
    if result.rows_affected() == 0 {
        return Err(SessionError::StorageUnavailable {
            message: "Execution Session provenance update was lost".to_owned(),
        });
    }
    Ok(prepared)
}

async fn read_session(
    storage: &PgStorage,
    session_id: ExecutionSessionId,
) -> Result<ExecutionSession, SessionError> {
    let row = sqlx::query(READ_SESSION_SQL)
        .bind(session_id.to_string())
        .fetch_optional(&storage.pool)
        .await
        .map_err(sql_session_error)?;
    let Some(row) = row else {
        return Err(SessionError::SessionNotFound { session_id });
    };
    let record: Value = row.try_get("record").map_err(sql_session_error)?;
    serde_json::from_value(record).map_err(|error| SessionError::StorageUnavailable {
        message: format!("invalid persisted Execution Session: {error}"),
    })
}

async fn list_sessions(storage: &PgStorage) -> Result<Vec<ExecutionSession>, SessionError> {
    let rows = sqlx::query(LIST_SESSIONS_SQL)
        .fetch_all(&storage.pool)
        .await
        .map_err(sql_session_error)?;
    rows.into_iter()
        .map(|row| {
            let record: Value = row.try_get("record").map_err(sql_session_error)?;
            serde_json::from_value(record).map_err(|error| SessionError::StorageUnavailable {
                message: format!("invalid persisted Execution Session: {error}"),
            })
        })
        .collect()
}

fn sql_session_error(error: sqlx::Error) -> SessionError {
    SessionError::StorageUnavailable {
        message: format!("PostgreSQL Execution Session persistence failed: {error}"),
    }
}

fn session_origin(origin: loom_runtime::ExecutionOrigin) -> &'static str {
    match origin {
        loom_runtime::ExecutionOrigin::Application => "Application",
        loom_runtime::ExecutionOrigin::Ingress => "Ingress",
        loom_runtime::ExecutionOrigin::Operator => "Operator",
        loom_runtime::ExecutionOrigin::Runtime => "Runtime",
    }
}

fn session_status(status: ExecutionSessionStatus) -> &'static str {
    match status {
        ExecutionSessionStatus::Started => "Started",
        ExecutionSessionStatus::Committed => "Committed",
        ExecutionSessionStatus::Rejected => "Rejected",
        ExecutionSessionStatus::Failed => "Failed",
    }
}
