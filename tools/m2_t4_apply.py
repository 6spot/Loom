from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text()
    if old not in text:
        raise SystemExit(f"expected source block not found in {path}")
    file.write_text(text.replace(old, new, 1))


# Runtime Work errors and executor-neutral WorkStore I/O.
persistence = Path("crates/loom-runtime/src/persistence.rs")
text = persistence.read_text()
text = text.replace(
    "    /// A scheduled Work points at an Event absent from the staged ledger.\n"
    "    MissingCausalEvent { work_id: WorkId, event_id: EventId },\n",
    "    /// A scheduled Work points at an Event absent from the staged ledger.\n"
    "    MissingCausalEvent { work_id: WorkId, event_id: EventId },\n"
    "    /// The persistence authority could not complete a Work I/O operation.\n"
    "    StorageUnavailable { message: String },\n",
    1,
)
text = text.replace(
    "            Self::MissingCausalEvent { work_id, event_id } => write!(\n"
    "                formatter,\n"
    "                \"Work {work_id} references missing causal Event {event_id}\"\n"
    "            ),\n",
    "            Self::MissingCausalEvent { work_id, event_id } => write!(\n"
    "                formatter,\n"
    "                \"Work {work_id} references missing causal Event {event_id}\"\n"
    "            ),\n"
    "            Self::StorageUnavailable { message } => formatter.write_str(message),\n",
    1,
)
marker = "pub trait WorkStore {"
start = text.index(marker)
text = text[:start] + '''pub trait WorkStore {
    /// Claims one Pending Work until an explicit platform deadline.
    ///
    /// Claiming only updates lease/attempt metadata. It does not change Work
    /// status or Timeline version. The returned Future is executor-neutral so
    /// SQL-backed adapters never need to block inside Runtime.
    ///
    /// # Errors
    ///
    /// Returns [`WorkError::AlreadyClaimed`], [`WorkError::NotAvailable`] or a
    /// typed identity/status/infrastructure error when the claim cannot linearize.
    fn claim<'a>(
        &'a self,
        timeline_id: TimelineId,
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    ) -> PersistenceFuture<'a, Result<WorkClaim, WorkError>>;

    /// Records a technical retry without changing World Truth.
    ///
    /// The same Work identity remains `Pending`; only platform availability,
    /// attempt metadata and the last error change. No Event, Facet, structure,
    /// Timeline version or World Time is advanced.
    ///
    /// # Errors
    ///
    /// Returns a typed stale/expired claim, Work lifecycle or infrastructure error.
    fn retry<'a>(
        &'a self,
        claim: &'a WorkClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        last_error: Option<String>,
    ) -> PersistenceFuture<'a, Result<WorkRecord, WorkError>>;

    /// Reads one Work record from a Timeline.
    ///
    /// `Ok(None)` means the Timeline exists but has no such Work identity.
    ///
    /// # Errors
    ///
    /// Returns [`ReadError::TimelineNotFound`] for an unknown Timeline or a
    /// storage-unavailable error when the authority cannot be read.
    fn work(
        &self,
        timeline_id: TimelineId,
        work_id: WorkId,
    ) -> PersistenceFuture<'_, Result<Option<WorkRecord>, ReadError>>;
}
'''
persistence.write_text(text)


# Runtime orchestration awaits Work I/O; Capability dispatch remains synchronous.
orchestration = Path("crates/loom-runtime/src/orchestration.rs")
text = orchestration.read_text()
text = text.replace(
    '''        let claim = self
            .store
            .claim(target.timeline_id, work_id, now, claimed_until)
            .map_err(|error| map_work_error(&error))?;
''',
    '''        let claim = self
            .store
            .claim(target.timeline_id, work_id, now, claimed_until)
            .await
            .map_err(|error| map_work_error(&error))?;
''',
    1,
)
text = text.replace(
    "return Err(self.retry_after_failure(&claim, now, retry_available_at, error));",
    "return Err(self.retry_after_failure(&claim, now, retry_available_at, error).await);",
)
text = text.replace(
    "Err(self.retry_after_failure(&claim, now, retry_available_at, error))",
    "Err(self.retry_after_failure(&claim, now, retry_available_at, error).await)",
)
retry_start = text.index("    pub fn retry_work(")
retry_end = text.index("    async fn snapshot_for_target", retry_start)
text = text[:retry_start] + '''    pub async fn retry_work(
        &self,
        claim: &WorkClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        last_error: Option<String>,
    ) -> Result<WorkRecord, WorkError> {
        self.store
            .retry(claim, now, available_at, last_error)
            .await
    }

''' + text[retry_end:]
helper_start = text.index("    fn retry_after_failure(")
helper_end = text.index("\n}\n\nimpl<T> WorldStore", helper_start)
text = text[:helper_start] + '''    async fn retry_after_failure(
        &self,
        claim: &WorkClaim,
        now: PlatformTime,
        retry_available_at: PlatformTime,
        error: ApiError,
    ) -> ApiError {
        if self
            .store
            .retry(claim, now, retry_available_at, Some(error.message.clone()))
            .await
            .is_err()
        {
            return ApiError::internal("Work failure could not be recorded for retry");
        }
        error
    }
''' + text[helper_end:]
work_impl_start = text.index("impl<T> WorkStore for &T")
work_impl_end = text.index("impl<S> ActionService for Runtime<S>", work_impl_start)
text = text[:work_impl_start] + '''impl<T> WorkStore for &T
where
    T: WorkStore + ?Sized,
{
    fn claim<'a>(
        &'a self,
        timeline_id: TimelineId,
        work_id: WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    ) -> PersistenceFuture<'a, Result<WorkClaim, WorkError>> {
        (**self).claim(timeline_id, work_id, now, claimed_until)
    }

    fn retry<'a>(
        &'a self,
        claim: &'a WorkClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        last_error: Option<String>,
    ) -> PersistenceFuture<'a, Result<WorkRecord, WorkError>> {
        (**self).retry(claim, now, available_at, last_error)
    }

    fn work(
        &self,
        timeline_id: TimelineId,
        work_id: WorkId,
    ) -> PersistenceFuture<'_, Result<Option<WorkRecord>, ReadError>> {
        (**self).work(timeline_id, work_id)
    }
}

''' + text[work_impl_end:]
text = text.replace(
    '''        WorkError::AttemptOverflow { .. }
        | WorkError::DuplicateWork { .. }
        | WorkError::MissingCausalEvent { .. } => {
            ApiError::internal("Work adapter rejected the execution metadata")
        }
''',
    '''        WorkError::StorageUnavailable { .. } => {
            ApiError::unavailable("Persistence authority is temporarily unavailable")
        }
        WorkError::AttemptOverflow { .. }
        | WorkError::DuplicateWork { .. }
        | WorkError::MissingCausalEvent { .. } => {
            ApiError::internal("Work adapter rejected the execution metadata")
        }
''',
    1,
)
orchestration.write_text(text)


# Keep the in-memory oracle synchronous internally but adapt its public port to Future I/O.
in_memory = Path("crates/loom-storage/src/in_memory.rs")
text = in_memory.read_text()
start = text.index("impl WorkStore for InMemoryStore {")
end = text.index("fn snapshot_from_timeline", start)
text = text[:start] + '''impl WorkStore for InMemoryStore {
    fn claim<'a>(
        &'a self,
        timeline_id: TimelineId,
        work_id: loom_core::WorkId,
        now: PlatformTime,
        claimed_until: PlatformTime,
    ) -> PersistenceFuture<'a, Result<WorkClaim, WorkError>> {
        Box::pin(async move {
            InMemoryStore::claim(self, timeline_id, work_id, now, claimed_until)
        })
    }

    fn retry<'a>(
        &'a self,
        claim: &'a WorkClaim,
        now: PlatformTime,
        available_at: PlatformTime,
        last_error: Option<String>,
    ) -> PersistenceFuture<'a, Result<WorkRecord, WorkError>> {
        Box::pin(async move {
            InMemoryStore::retry(self, claim, now, available_at, last_error)
        })
    }

    fn work(
        &self,
        timeline_id: TimelineId,
        work_id: loom_core::WorkId,
    ) -> PersistenceFuture<'_, Result<Option<WorkRecord>, ReadError>> {
        Box::pin(async move { InMemoryStore::work(self, timeline_id, work_id) })
    }
}

''' + text[end:]
in_memory.write_text(text)


# Wire the PostgreSQL Work adapter without exposing its concrete types.
replace_once(
    "crates/loom-storage/src/postgres.rs",
    "//! behavior plus the M2-T2 `WorldStore` read path. M2-T3 adds the atomic\n"
    "//! `CommitStore` path in a private child module; Durable Work claim/retry remains T4.\n\n"
    "mod commit;\n",
    "//! behavior plus the M2-T2 `WorldStore` read path. M2-T3 adds the atomic\n"
    "//! `CommitStore` path, and M2-T4 adds Durable Work claim/retry fencing in\n"
    "//! private child modules.\n\n"
    "mod commit;\n"
    "mod work;\n",
)


# Fix missing-row classification in the new PostgreSQL Work adapter with async SQL.
work = Path("crates/loom-storage/src/postgres/work.rs")
text = work.read_text()
text = text.replace(
    '''    let mut work = locked_work(&mut transaction, timeline_id, work_id)
        .await?
        .ok_or_else(|| missing_work(&mut transaction, timeline_id, work_id))?;
''',
    '''    let Some(mut work) = locked_work(&mut transaction, timeline_id, work_id).await? else {
        return Err(missing_work_error(&mut transaction, timeline_id, work_id).await);
    };
''',
)
old_helpers = '''fn missing_work(
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
'''
new_helpers = '''async fn missing_work_error(
    transaction: &mut PgTransaction<'_>,
    timeline_id: TimelineId,
    work_id: WorkId,
) -> WorkError {
    let exists = sqlx::query_scalar::<_, bool>(
        "SELECT EXISTS (SELECT 1 FROM loom_timeline WHERE timeline_id = $1::uuid)",
    )
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
'''
if old_helpers not in text:
    raise SystemExit("expected temporary missing Work helper not found")
work.write_text(text.replace(old_helpers, new_helpers, 1))
