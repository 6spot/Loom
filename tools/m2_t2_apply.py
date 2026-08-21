from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def write(path: str, text: str) -> None:
    (ROOT / path).write_text(text)


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    if old not in text:
        raise SystemExit(f"expected snippet not found in {path}: {old[:80]!r}")
    write(path, text.replace(old, new, 1))


def sub_once(path: str, pattern: str, replacement: str) -> None:
    text = read(path)
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"expected one regex match in {path}: {pattern[:80]!r}; got {count}")
    write(path, updated)


def add_dependency(path: str, section: str, line: str) -> None:
    text = read(path)
    if line in text:
        return
    marker = f"[{section}]\n"
    if marker not in text:
        text += f"\n{marker}{line}\n"
    else:
        text = text.replace(marker, marker + line + "\n", 1)
    write(path, text)


def insert_await_after_calls(text: str, methods: list[str]) -> str:
    for method in methods:
        needle = f".{method}("
        cursor = 0
        while True:
            start = text.find(needle, cursor)
            if start < 0:
                break
            open_paren = start + len(needle) - 1
            depth = 0
            in_string = False
            escaped = False
            index = open_paren
            while index < len(text):
                ch = text[index]
                if in_string:
                    if escaped:
                        escaped = False
                    elif ch == "\\":
                        escaped = True
                    elif ch == '"':
                        in_string = False
                else:
                    if ch == '"':
                        in_string = True
                    elif ch == "(":
                        depth += 1
                    elif ch == ")":
                        depth -= 1
                        if depth == 0:
                            break
                index += 1
            if index >= len(text):
                raise SystemExit(f"unbalanced call for {method}")
            after = index + 1
            if text.startswith(".await", after):
                cursor = after + len(".await")
                continue
            text = text[:after] + ".await" + text[after:]
            cursor = after + len(".await")
    return text


def async_test_tail(path: str, methods: list[str]) -> None:
    text = read(path)
    marker = "#[test]"
    split = text.find(marker)
    if split < 0:
        raise SystemExit(f"no tests found in {path}")
    head, tail = text[:split], text[split:]
    tail = tail.replace("#[test]", "#[tokio::test]")
    tail = re.sub(r"(?m)^fn ([A-Za-z0-9_]+)\(\) \{", r"async fn \1() {", tail)
    tail = insert_await_after_calls(tail, methods)
    write(path, head + tail)


api_path = "crates/loom-api/src/lib.rs"
if "pub type ApiFuture<'a, T>" in read(api_path) and "impl WorldStore for PgStorage" in read(
    "crates/loom-storage/src/postgres.rs"
):
    print("M2-T2 source migration is already applied")
    raise SystemExit(0)

replace_once(api_path, "use std::fmt;", "use std::{fmt, future::Future, pin::Pin};")
replace_once(
    api_path,
    "/// A convenient result alias for public Loom service methods.\npub type ApiResult<T> = Result<T, ApiError>;",
    "/// A convenient result alias for public Loom service methods.\npub type ApiResult<T> = Result<T, ApiError>;\n\n/// Executor-neutral future returned by public Loom I/O service methods.\n///\n/// The boxed future keeps the focused service traits object-safe, so an\n/// application may continue to consume `&dyn LoomApi` while Runtime awaits\n/// asynchronous persistence. The contract chooses no executor and exposes no\n/// Runtime, database or transaction type.\npub type ApiFuture<'a, T> = Pin<Box<dyn Future<Output = ApiResult<T>> + 'a>>;",
)
sub_once(
    api_path,
    r"pub trait ActionService \{.*?\n\}\n\n/// Inspects the current version",
    '''pub trait ActionService {
    /// Resolves and attempts one Action request on the addressed Timeline.
    ///
    /// A semantic refusal is returned as `Ok(ExecutionResult::Rejected(_))`.
    /// Request, lookup, concurrency and infrastructure failures use
    /// `Err(ApiError)` instead. The returned future is executor-neutral and
    /// keeps persistence latency outside Capability semantic execution.
    ///
    /// # Errors
    ///
    /// Returns an `ApiError` when the request cannot be resolved or committed
    /// through the public service boundary.
    fn invoke(&self, request: ActionRequest) -> ApiFuture<'_, ExecutionResult>;

    /// Invokes an Action using separate World/Timeline identities.
    ///
    /// # Errors
    ///
    /// Propagates the `ApiError` returned by `invoke`.
    fn invoke_on(
        &self,
        world_id: WorldId,
        timeline_id: TimelineId,
        invocation: ActionInvocation,
    ) -> ApiFuture<'_, ExecutionResult> {
        self.invoke(ActionRequest::for_timeline(
            world_id,
            timeline_id,
            invocation,
        ))
    }
}

/// Inspects the current version''',
)
sub_once(
    api_path,
    r"pub trait TimelineService \{.*?\n\}\n\n/// Reads current materialized",
    '''pub trait TimelineService {
    /// Returns one consistent public Timeline snapshot.
    ///
    /// # Errors
    ///
    /// Returns an `ApiError` when the World/Timeline cannot be found or read.
    fn inspect_timeline(&self, target: TimelineTarget) -> ApiFuture<'_, TimelineSnapshot>;
}

/// Reads current materialized''',
)
sub_once(
    api_path,
    r"pub trait QueryService \{.*?\n\}\n\n/// Reads committed World history",
    '''pub trait QueryService {
    /// Reads one current Facet value, returning `None` when it is absent.
    ///
    /// # Errors
    ///
    /// Returns an `ApiError` when the target cannot be found or read.
    fn get_facet(&self, query: FacetQuery) -> ApiFuture<'_, Option<FacetSnapshot>>;
}

/// Reads committed World history''',
)
sub_once(
    api_path,
    r"pub trait HistoryService \{.*?\n\}\n\n/// Discovers centrally registered",
    '''pub trait HistoryService {
    /// Lists committed Events matching the bounded v0 history query.
    ///
    /// # Errors
    ///
    /// Returns an `ApiError` when the target cannot be found or its history
    /// cannot be read.
    fn list_events(&self, query: EventQuery) -> ApiFuture<'_, Vec<CommittedEvent>>;
}

/// Discovers centrally registered''',
)
text = read(api_path)
text = text.replace(
    "ActionDescriptor, ActionRequest, ActionService, ApiError, ApiErrorCode, ApiResult,",
    "ActionDescriptor, ActionRequest, ActionService, ApiError, ApiErrorCode, ApiFuture, ApiResult,",
    1,
)
text = re.sub(
    r"impl ActionService for StubApi \{.*?\n    \}\n\n    impl TimelineService",
    '''impl ActionService for StubApi {
        fn invoke(&self, request: ActionRequest) -> ApiFuture<'_, ExecutionResult> {
            Box::pin(async move {
                assert_eq!(request.target, target());
                assert_eq!(request.invocation.action.as_str(), "counter.increment");
                Ok(ExecutionResult::committed(
                    Vec::new(),
                    TimelineVersion::new(1.into(), 1.into()),
                ))
            })
        }
    }

    impl TimelineService''',
    text,
    count=1,
    flags=re.S,
)
text = re.sub(
    r"impl TimelineService for StubApi \{.*?\n    \}\n\n    impl QueryService",
    '''impl TimelineService for StubApi {
        fn inspect_timeline(&self, target: TimelineTarget) -> ApiFuture<'_, TimelineSnapshot> {
            Box::pin(async move {
                Ok(TimelineSnapshot::new(
                    target,
                    TimelineVersion::new(1.into(), 1.into()),
                    WorldInstant::new(7),
                ))
            })
        }
    }

    impl QueryService''',
    text,
    count=1,
    flags=re.S,
)
text = re.sub(
    r"impl QueryService for StubApi \{.*?\n    \}\n\n    impl HistoryService",
    '''impl QueryService for StubApi {
        fn get_facet(&self, query: FacetQuery) -> ApiFuture<'_, Option<FacetSnapshot>> {
            Box::pin(async move {
                Ok(Some(FacetSnapshot::new(
                    query.owner,
                    query.facet_type,
                    SchemaRevision::new(1),
                    json!({"value": 1}),
                )))
            })
        }
    }

    impl HistoryService''',
    text,
    count=1,
    flags=re.S,
)
text = re.sub(
    r"impl HistoryService for StubApi \{.*?\n    \}\n\n    impl CatalogService",
    '''impl HistoryService for StubApi {
        fn list_events(&self, _query: EventQuery) -> ApiFuture<'_, Vec<CommittedEvent>> {
            Box::pin(async { Ok(Vec::new()) })
        }
    }

    impl CatalogService''',
    text,
    count=1,
    flags=re.S,
)
text = text.replace(
    "#[test]\n    fn focused_services_form_one_public_world_api() {",
    "#[tokio::test]\n    async fn focused_services_form_one_public_world_api() {",
    1,
)
marker = "#[tokio::test]\n    async fn focused_services_form_one_public_world_api() {"
pos = text.find(marker)
if pos < 0:
    raise SystemExit("focused async API test not found")
text = text[:pos] + insert_await_after_calls(
    text[pos:], ["invoke_on", "inspect_timeline", "get_facet"]
)
write(api_path, text)
add_dependency(
    "crates/loom-api/Cargo.toml",
    "dev-dependencies",
    'tokio = { version = "~1.51", features = ["macros", "rt"] }',
)

persistence_path = "crates/loom-runtime/src/persistence.rs"
replace_once(
    persistence_path,
    "use std::{\n    fmt,\n    sync::{",
    "use std::{\n    fmt,\n    future::Future,\n    pin::Pin,\n    sync::{",
)
replace_once(
    persistence_path,
    "    EventId, EventSeq, TimelineId, TimelineVersion, WorkHandlerId, WorkId, WorldEffect,\n    WorldInstant,",
    "    AssociationRole, EntityId, EventId, EventSeq, RelationshipId, TimelineId, TimelineVersion,\n    WorkHandlerId, WorkId, WorldEffect, WorldInstant,",
)
replace_once(
    persistence_path,
    "use crate::{BaseWorldSnapshot, BaseWorldView, ValidatedResolution};",
    "use crate::{BaseWorldSnapshot, BaseWorldView, ValidatedResolution};\n\n/// Executor-neutral future returned by Runtime persistence I/O ports.\n///\n/// Persistence adapters may use SQLx or another asynchronous driver without\n/// choosing an executor for Runtime. Capability code never receives this type:\n/// resolvers operate on the already-pinned in-memory `BaseWorldView`.\npub type PersistenceFuture<'a, T> = Pin<Box<dyn Future<Output = T> + 'a>>;",
)
replace_once(
    persistence_path,
    "    /// Returns the assigned sequence using the API-oriented name.\n    #[must_use]\n    pub const fn sequence(&self) -> EventSeq {",
    '''    /// Builds a committed read model from persisted scalar/Event data.
    ///
    /// Storage adapters may use this constructor while reconstructing history;
    /// it does not create commit authority or bypass Runtime validation.
    #[must_use]
    pub fn from_persisted(
        id: EventId,
        timeline_id: TimelineId,
        event_seq: EventSeq,
        event_type: loom_core::EventTypeId,
        schema_revision: loom_core::SchemaRevision,
        occurred_at: WorldInstant,
        payload: Value,
        effects: Vec<WorldEffect>,
    ) -> Self {
        Self {
            id,
            timeline_id,
            event_seq,
            event_type,
            schema_revision,
            occurred_at,
            participants: Vec::new(),
            relationship_refs: Vec::new(),
            causal_links: Vec::new(),
            payload,
            effects,
        }
    }

    /// Adds a persisted direct Entity association while rebuilding history.
    pub fn push_participant(&mut self, entity_id: EntityId, role: AssociationRole) {
        self.participants
            .push(loom_protocol::EventParticipant::new(entity_id, role));
    }

    /// Adds a persisted Relationship association while rebuilding history.
    pub fn push_relationship_ref(&mut self, relationship_id: RelationshipId, role: AssociationRole) {
        self.relationship_refs
            .push(loom_protocol::EventRelationshipRef::new(relationship_id, role));
    }

    /// Adds a persisted causal edge while rebuilding committed history.
    pub fn push_causal_link(&mut self, cause_event_id: EventId) {
        self.causal_links
            .push(loom_protocol::CausalLink::new(cause_event_id));
    }

    /// Returns the assigned sequence using the API-oriented name.
    #[must_use]
    pub const fn sequence(&self) -> EventSeq {''',
)
sub_once(
    persistence_path,
    r"pub enum ReadError \{.*?impl std::error::Error for ReadError \{\}",
    '''pub enum ReadError {
    /// The requested Timeline does not exist in the adapter authority.
    TimelineNotFound { timeline_id: TimelineId },
    /// The persistence authority could not complete a coherent read.
    StorageUnavailable { message: String },
}

impl fmt::Display for ReadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::TimelineNotFound { timeline_id } => {
                write!(formatter, "Timeline {timeline_id} was not found")
            }
            Self::StorageUnavailable { message } => formatter.write_str(message),
        }
    }
}

impl std::error::Error for ReadError {}''',
)
sub_once(
    persistence_path,
    r"pub trait WorldStore \{.*?\n\}\n\n/// Runtime commit port",
    '''pub trait WorldStore {
    /// Reads one coherent Timeline snapshot asynchronously.
    ///
    /// The returned base state, Event ledger and Work records correspond to
    /// one adapter snapshot. Implementations must not expose a mixture of
    /// revisions. The Future is executor-neutral and must not be exposed to
    /// Capability semantic code.
    ///
    /// # Errors
    ///
    /// Returns [`ReadError::TimelineNotFound`] when the Timeline is absent, or
    /// [`ReadError::StorageUnavailable`] when the authority cannot be read.
    fn snapshot(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<TimelineSnapshot, ReadError>>;

    /// Alias emphasizing the read-side operation for callers that use the
    /// port as a `read_snapshot` dependency.
    fn read_snapshot(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<TimelineSnapshot, ReadError>> {
        self.snapshot(timeline_id)
    }
}

/// Runtime commit port''',
)

runtime_lib = "crates/loom-runtime/src/lib.rs"
replace_once(
    runtime_lib,
    "    CommitError, CommitResult, CommitStore, CommittedEvent, ManualPlatformClock, PlatformClock,\n    PlatformTime, ReadError, TimelineSnapshot, WorkClaim, WorkError, WorkLease, WorkRecord,",
    "    CommitError, CommitResult, CommitStore, CommittedEvent, ManualPlatformClock, PersistenceFuture,\n    PlatformClock, PlatformTime, ReadError, TimelineSnapshot, WorkClaim, WorkError, WorkLease, WorkRecord,",
)

orchestration = "crates/loom-runtime/src/orchestration.rs"
replace_once(
    orchestration,
    "    ActionDescriptor, ActionRequest, ActionService, ApiError, ApiResult, CatalogService,",
    "    ActionDescriptor, ActionRequest, ActionService, ApiError, ApiFuture, ApiResult, CatalogService,",
)
replace_once(
    orchestration,
    "    ManualPlatformClock, PlatformClock, PlatformTime, ReadError, ResolutionBudget, RuntimeError,",
    "    ManualPlatformClock, PersistenceFuture, PlatformClock, PlatformTime, ReadError, ResolutionBudget,\n    RuntimeError,",
)
replace_once(orchestration, "    pub fn execute_work(\n", "    pub async fn execute_work(\n")
replace_once(
    orchestration,
    "        let snapshot = self.snapshot_for_target(target)?;",
    "        let snapshot = self.snapshot_for_target(target).await?;",
)
replace_once(
    orchestration,
    "        let snapshot = match self.snapshot_for_target(target) {",
    "        let snapshot = match self.snapshot_for_target(target).await {",
)
sub_once(
    orchestration,
    r"    fn snapshot_for_target\(&self, target: TimelineTarget\) -> ApiResult<TimelineSnapshot> \{.*?\n    \}\n\n    fn retry_after_failure",
    '''    async fn snapshot_for_target(&self, target: TimelineTarget) -> ApiResult<TimelineSnapshot> {
        let snapshot = self
            .store
            .snapshot(target.timeline_id)
            .await
            .map_err(|error| map_read_error(&error))?;
        if snapshot.world_id() != target.world_id {
            return Err(ApiError::not_found(format!(
                "Timeline {} is not in World {}",
                target.timeline_id, target.world_id
            )));
        }
        Ok(snapshot)
    }

    fn retry_after_failure''',
)
sub_once(
    orchestration,
    r"impl<T> WorldStore for &T\nwhere\n    T: WorldStore \+ \?Sized,\n\{.*?\n\}\n\nimpl<T> CommitStore",
    '''impl<T> WorldStore for &T
where
    T: WorldStore + ?Sized,
{
    fn snapshot(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<TimelineSnapshot, ReadError>> {
        (**self).snapshot(timeline_id)
    }
}

impl<T> CommitStore''',
)
sub_once(
    orchestration,
    r"impl<S> ActionService for Runtime<S>.*?\n\}\n\nimpl<S> TimelineService",
    '''impl<S> ActionService for Runtime<S>
where
    S: WorldStore + CommitStore + WorkStore,
{
    fn invoke(&self, request: ActionRequest) -> ApiFuture<'_, ExecutionResult> {
        Box::pin(async move {
            let snapshot = self.snapshot_for_target(request.target).await?;
            let base = snapshot.world_view();
            if self.registry.action(&request.invocation.action).is_none() {
                return Err(ApiError::not_found(format!(
                    "Action {} was not registered",
                    request.invocation.action
                )));
            }
            let engine = EffectEngine::new(&self.registry).with_budget(self.resolution_budget);
            engine
                .validate_action_input(&request.invocation.action, &request.invocation.input)
                .map_err(|error| map_action_input_error(&error))?;
            let (outcome, execution) = dispatch_root_action(
                &base,
                &self.registry,
                self.resolution_budget,
                &request.invocation,
            )
            .map_err(map_dispatch_error)?;
            match outcome {
                ResolveOutcome::Rejected(rejection) => Ok(ExecutionResult::rejected(rejection)),
                ResolveOutcome::Resolved(_) => {
                    let validated = engine
                        .validate_segments(&base, &execution.segments, execution.call_provenance)
                        .map_err(|error| map_runtime_error(&error))?;
                    self.store
                        .commit(&validated, None, self.platform_clock.now())
                        .map(|result| {
                            execution_result(&result, changes_runtime_state(&validated, None))
                        })
                        .map_err(|error| map_commit_error(&error))
                }
            }
        })
    }
}

impl<S> TimelineService''',
)
sub_once(
    orchestration,
    r"impl<S> TimelineService for Runtime<S>.*?\n\}\n\nimpl<S> QueryService",
    '''impl<S> TimelineService for Runtime<S>
where
    S: WorldStore + CommitStore + WorkStore,
{
    fn inspect_timeline(&self, target: TimelineTarget) -> ApiFuture<'_, ApiTimelineSnapshot> {
        Box::pin(async move {
            let snapshot = self.snapshot_for_target(target).await?;
            Ok(ApiTimelineSnapshot::new(
                target,
                snapshot.version(),
                snapshot.world_time(),
            ))
        })
    }
}

impl<S> QueryService''',
)
sub_once(
    orchestration,
    r"impl<S> QueryService for Runtime<S>.*?\n\}\n\nimpl<S> HistoryService",
    '''impl<S> QueryService for Runtime<S>
where
    S: WorldStore + CommitStore + WorkStore,
{
    fn get_facet(&self, query: FacetQuery) -> ApiFuture<'_, Option<ApiFacetSnapshot>> {
        Box::pin(async move {
            let snapshot = self.snapshot_for_target(query.target).await?;
            let view = snapshot.world_view();
            Ok(view.facet(query.owner, &query.facet_type).map(|facet| {
                ApiFacetSnapshot::new(
                    facet.owner(),
                    facet.facet_type().clone(),
                    facet.schema_revision(),
                    facet.value().clone(),
                )
            }))
        })
    }
}

impl<S> HistoryService''',
)
sub_once(
    orchestration,
    r"impl<S> HistoryService for Runtime<S>.*?\n\}\n\nimpl<S> CatalogService",
    '''impl<S> HistoryService for Runtime<S>
where
    S: WorldStore + CommitStore + WorkStore,
{
    fn list_events(&self, query: EventQuery) -> ApiFuture<'_, Vec<ApiCommittedEvent>> {
        Box::pin(async move {
            let snapshot = self.snapshot_for_target(query.target).await?;
            let limit = query.limit.map_or(usize::MAX, |limit| {
                usize::try_from(limit).unwrap_or(usize::MAX)
            });
            Ok(snapshot
                .events
                .iter()
                .filter(|event| query.after.is_none_or(|after| event.event_seq > after))
                .take(limit)
                .map(api_event)
                .collect())
        })
    }
}

impl<S> CatalogService''',
)
replace_once(
    orchestration,
    '''        ReadError::TimelineNotFound { timeline_id } => {
            ApiError::not_found(format!("Timeline {timeline_id} was not found"))
        }
    }
}''',
    '''        ReadError::TimelineNotFound { timeline_id } => {
            ApiError::not_found(format!("Timeline {timeline_id} was not found"))
        }
        ReadError::StorageUnavailable { .. } => {
            ApiError::unavailable("Persistence authority is temporarily unavailable")
        }
    }
}''',
)

in_memory = "crates/loom-storage/src/in_memory.rs"
replace_once(
    in_memory,
    "    BaseWorldSnapshot, CommitError, CommitResult, CommitStore, CommittedEvent, PlatformTime,\n    ProposedEvent, ReadError, TimelineSnapshot, ValidatedResolution, WorkClaim, WorkError,",
    "    BaseWorldSnapshot, CommitError, CommitResult, CommitStore, CommittedEvent, PersistenceFuture,\n    PlatformTime, ProposedEvent, ReadError, TimelineSnapshot, ValidatedResolution, WorkClaim, WorkError,",
)
sub_once(
    in_memory,
    r"impl WorldStore for InMemoryStore \{.*?\n\}\n\nimpl CommitStore",
    '''impl WorldStore for InMemoryStore {
    fn snapshot(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<TimelineSnapshot, ReadError>> {
        Box::pin(async move { InMemoryStore::snapshot(self, timeline_id) })
    }
}

impl CommitStore''',
)

add_dependency(
    "tests/loom-composition/Cargo.toml",
    "dependencies",
    'tokio = { version = "~1.51", features = ["macros", "rt-multi-thread"] }',
)
async_test_tail(
    "tests/loom-composition/vertical_slice.rs",
    ["invoke", "get_facet", "list_events", "execute_work", "inspect_timeline"],
)
sub_path = "tests/loom-composition/subresolution.rs"
replace_once(
    sub_path,
    "    CallProvenance, CommitError, CommitResult, CommitStore, PlatformTime, ReadError,\n    ResolutionBudget, Runtime, TimelineSnapshot, ValidatedResolution, WorkClaim, WorkError,",
    "    CallProvenance, CommitError, CommitResult, CommitStore, PersistenceFuture, PlatformTime,\n    ReadError, ResolutionBudget, Runtime, TimelineSnapshot, ValidatedResolution, WorkClaim, WorkError,",
)
sub_once(
    sub_path,
    r"impl WorldStore for CountingStore \{.*?\n\}\n\nimpl CommitStore",
    '''impl WorldStore for CountingStore {
    fn snapshot(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<TimelineSnapshot, ReadError>> {
        Box::pin(async move { self.inner.snapshot(timeline_id) })
    }
}

impl CommitStore''',
)
async_test_tail(sub_path, ["invoke", "snapshot"])

postgres = "crates/loom-storage/src/postgres.rs"
replace_once(
    postgres,
    "use sqlx::{PgPool, postgres::PgPoolOptions};",
    '''use std::{fmt::Display, str::FromStr};

use loom_core::{
    AssociationRole, Entity, EntityId, EventId, EventSeq, EventTypeId, FacetOwner, FacetTypeId,
    Relationship, RelationshipId, RelationshipParticipant, RelationshipTypeId, SchemaRevision,
    StateRevision, TimelineId, TimelineVersion, WorkHandlerId, WorkId, WorldEffect, WorldId,
    WorldInstant,
};
use loom_runtime::{
    BaseWorldSnapshot, CommittedEvent, PersistenceFuture, PlatformTime, ReadError, TimelineSnapshot,
    WorkLease, WorkRecord, WorkStatus, WorldStore,
};
use serde_json::Value;
use sqlx::{PgPool, Row, postgres::PgPoolOptions};''',
)
replace_once(
    postgres,
    "//! behavior only; `WorldStore`, `CommitStore` and `WorkStore` implementations are\n//! introduced by their dedicated Milestone 2 tasks.",
    "//! behavior plus the M2-T2 `WorldStore` read path. Commit/CAS and Durable Work\n//! mutation ports remain owned by their dedicated Milestone 2 tasks.",
)
read_impl = r'''

impl PgStorage {
    async fn read_snapshot(&self, timeline_id: TimelineId) -> Result<TimelineSnapshot, ReadError> {
        let mut transaction = self.pool.begin().await.map_err(sql_read_error)?;
        sqlx::query("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            .execute(&mut *transaction)
            .await
            .map_err(sql_read_error)?;

        let timeline_row = sqlx::query(
            "SELECT world_id::text AS world_id, head_event_seq::text AS head_event_seq, \
                    state_revision::text AS state_revision, world_time \
             FROM loom_timeline WHERE timeline_id = $1::uuid",
        )
        .bind(timeline_id.to_string())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(sql_read_error)?;
        let Some(timeline_row) = timeline_row else {
            let _ = transaction.rollback().await;
            return Err(ReadError::TimelineNotFound { timeline_id });
        };

        let world_id = parse_identity::<WorldId>(row_string(&timeline_row, "world_id")?, "WorldId")?;
        let head_event_seq = EventSeq::new(parse_u64(
            &row_string(&timeline_row, "head_event_seq")?,
            "head_event_seq",
        )?);
        let state_revision = StateRevision::new(parse_u64(
            &row_string(&timeline_row, "state_revision")?,
            "state_revision",
        )?);
        let world_time = WorldInstant::new(row_i64(&timeline_row, "world_time")?);
        let mut base = BaseWorldSnapshot::new(
            world_id,
            timeline_id,
            TimelineVersion::new(head_event_seq, state_revision),
            world_time,
        );

        let entity_rows = sqlx::query(
            "SELECT entity_id::text AS entity_id FROM loom_entity \
             WHERE timeline_id = $1::uuid ORDER BY entity_id",
        )
        .bind(timeline_id.to_string())
        .fetch_all(&mut *transaction)
        .await
        .map_err(sql_read_error)?;
        for row in entity_rows {
            let entity_id = parse_identity::<EntityId>(&row_string(&row, "entity_id")?, "EntityId")?;
            base.insert_entity(Entity { entity_id: entity_id, id: entity_id, world_id });
        }

        let relationship_rows = sqlx::query(
            "SELECT relationship_id::text AS relationship_id, relationship_type, active \
             FROM loom_relationship WHERE timeline_id = $1::uuid ORDER BY relationship_id",
        )
        .bind(timeline_id.to_string())
        .fetch_all(&mut *transaction)
        .await
        .map_err(sql_read_error)?;
        for row in relationship_rows {
            let relationship_id = parse_identity::<RelationshipId>(
                &row_string(&row, "relationship_id")?,
                "RelationshipId",
            )?;
            let relationship_type = RelationshipTypeId::from(row_string(&row, "relationship_type")?);
            let active: bool = row.try_get("active").map_err(sql_read_error)?;
            let participant_rows = sqlx::query(
                "SELECT entity_id::text AS entity_id, role \
                 FROM loom_relationship_participant \
                 WHERE timeline_id = $1::uuid AND relationship_id = $2::uuid \
                 ORDER BY participant_order",
            )
            .bind(timeline_id.to_string())
            .bind(relationship_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
            let mut participants = Vec::with_capacity(participant_rows.len());
            for participant in participant_rows {
                participants.push(RelationshipParticipant::new(
                    parse_identity::<EntityId>(
                        &row_string(&participant, "entity_id")?,
                        "EntityId",
                    )?,
                    AssociationRole::from(row_string(&participant, "role")?),
                ));
            }
            base.insert_relationship(
                Relationship::new(
                    relationship_id,
                    world_id,
                    relationship_type,
                    participants,
                ),
                active,
            );
        }

        let entity_facet_rows = sqlx::query(
            "SELECT entity_id::text AS owner_id, facet_type, schema_revision, value \
             FROM loom_entity_facet WHERE timeline_id = $1::uuid \
             ORDER BY entity_id, facet_type",
        )
        .bind(timeline_id.to_string())
        .fetch_all(&mut *transaction)
        .await
        .map_err(sql_read_error)?;
        for row in entity_facet_rows {
            base.insert_facet(
                FacetOwner::entity(parse_identity::<EntityId>(
                    &row_string(&row, "owner_id")?,
                    "EntityId",
                )?),
                FacetTypeId::from(row_string(&row, "facet_type")?),
                schema_revision(&row)?,
                row_json(&row, "value")?,
            );
        }

        let relationship_facet_rows = sqlx::query(
            "SELECT relationship_id::text AS owner_id, facet_type, schema_revision, value \
             FROM loom_relationship_facet WHERE timeline_id = $1::uuid \
             ORDER BY relationship_id, facet_type",
        )
        .bind(timeline_id.to_string())
        .fetch_all(&mut *transaction)
        .await
        .map_err(sql_read_error)?;
        for row in relationship_facet_rows {
            base.insert_facet(
                FacetOwner::relationship(parse_identity::<RelationshipId>(
                    &row_string(&row, "owner_id")?,
                    "RelationshipId",
                )?),
                FacetTypeId::from(row_string(&row, "facet_type")?),
                schema_revision(&row)?,
                row_json(&row, "value")?,
            );
        }

        let event_rows = sqlx::query(
            "SELECT event_id::text AS event_id, event_seq::text AS event_seq, event_type, \
                    schema_revision, occurred_at, payload, effects \
             FROM loom_event WHERE timeline_id = $1::uuid ORDER BY event_seq",
        )
        .bind(timeline_id.to_string())
        .fetch_all(&mut *transaction)
        .await
        .map_err(sql_read_error)?;
        let mut events = Vec::with_capacity(event_rows.len());
        for row in event_rows {
            let event_id = parse_identity::<EventId>(&row_string(&row, "event_id")?, "EventId")?;
            let effects_value = row_json(&row, "effects")?;
            let effects: Vec<WorldEffect> = serde_json::from_value(effects_value)
                .map_err(|error| corrupt(format!("invalid persisted Event effects: {error}")))?;
            let mut event = CommittedEvent::from_persisted(
                event_id,
                timeline_id,
                EventSeq::new(parse_u64(&row_string(&row, "event_seq")?, "event_seq")?),
                EventTypeId::from(row_string(&row, "event_type")?),
                schema_revision(&row)?,
                WorldInstant::new(row_i64(&row, "occurred_at")?),
                row_json(&row, "payload")?,
                effects,
            );

            let participant_rows = sqlx::query(
                "SELECT entity_id::text AS entity_id, role FROM loom_event_participant \
                 WHERE timeline_id = $1::uuid AND event_id = $2::uuid ORDER BY participant_order",
            )
            .bind(timeline_id.to_string())
            .bind(event_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
            for participant in participant_rows {
                event.push_participant(
                    parse_identity::<EntityId>(&row_string(&participant, "entity_id")?, "EntityId")?,
                    AssociationRole::from(row_string(&participant, "role")?),
                );
            }

            let relationship_rows = sqlx::query(
                "SELECT relationship_id::text AS relationship_id, role \
                 FROM loom_event_relationship_ref \
                 WHERE timeline_id = $1::uuid AND event_id = $2::uuid ORDER BY reference_order",
            )
            .bind(timeline_id.to_string())
            .bind(event_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
            for relationship in relationship_rows {
                event.push_relationship_ref(
                    parse_identity::<RelationshipId>(
                        &row_string(&relationship, "relationship_id")?,
                        "RelationshipId",
                    )?,
                    AssociationRole::from(row_string(&relationship, "role")?),
                );
            }

            let causal_rows = sqlx::query(
                "SELECT cause_event_id::text AS cause_event_id FROM loom_event_causal_link \
                 WHERE timeline_id = $1::uuid AND event_id = $2::uuid ORDER BY causal_order",
            )
            .bind(timeline_id.to_string())
            .bind(event_id.to_string())
            .fetch_all(&mut *transaction)
            .await
            .map_err(sql_read_error)?;
            for causal in causal_rows {
                event.push_causal_link(parse_identity::<EventId>(
                    &row_string(&causal, "cause_event_id")?,
                    "EventId",
                )?);
            }
            base.insert_event(event_id);
            events.push(event);
        }

        let work_rows = sqlx::query(
            "SELECT work_id::text AS work_id, handler, schema_revision, payload, due_world_time, \
                    causal_event_id::text AS causal_event_id, origin_work_id::text AS origin_work_id, \
                    status, attempt_count, claim_generation::text AS claim_generation, available_at, \
                    last_error, lease_claimed_until, lease_fence::text AS lease_fence \
             FROM loom_work WHERE timeline_id = $1::uuid ORDER BY work_id",
        )
        .bind(timeline_id.to_string())
        .fetch_all(&mut *transaction)
        .await
        .map_err(sql_read_error)?;
        let mut works = Vec::with_capacity(work_rows.len());
        for row in work_rows {
            let work_id = parse_identity::<WorkId>(&row_string(&row, "work_id")?, "WorkId")?;
            let lease_until: Option<i64> = row.try_get("lease_claimed_until").map_err(sql_read_error)?;
            let lease_fence: Option<String> = row.try_get("lease_fence").map_err(sql_read_error)?;
            let lease = match (lease_until, lease_fence) {
                (None, None) => None,
                (Some(until), Some(fence)) => Some(WorkLease::new(
                    PlatformTime::new(until),
                    parse_u64(&fence, "lease_fence")?,
                )),
                _ => return Err(corrupt("persisted Work lease columns disagree")),
            };
            let attempt_count = u32::try_from(row_i64(&row, "attempt_count")?)
                .map_err(|_| corrupt("attempt_count exceeds u32"))?;
            works.push(WorkRecord {
                id: work_id,
                timeline_id,
                handler: WorkHandlerId::from(row_string(&row, "handler")?),
                schema_revision: schema_revision(&row)?,
                payload: row_json(&row, "payload")?,
                due_world_time: row
                    .try_get::<Option<i64>, _>("due_world_time")
                    .map_err(sql_read_error)?
                    .map(WorldInstant::new),
                causal_event_id: optional_identity::<EventId>(&row, "causal_event_id", "EventId")?,
                origin_work_id: optional_identity::<WorkId>(&row, "origin_work_id", "WorkId")?,
                status: parse_work_status(&row_string(&row, "status")?)?,
                attempt_count,
                claim_generation: parse_u64(
                    &row_string(&row, "claim_generation")?,
                    "claim_generation",
                )?,
                available_at: PlatformTime::new(row_i64(&row, "available_at")?),
                last_error: row.try_get("last_error").map_err(sql_read_error)?,
                lease,
            });
        }

        transaction.commit().await.map_err(sql_read_error)?;
        Ok(TimelineSnapshot::new(base, events, works))
    }
}

impl WorldStore for PgStorage {
    fn snapshot(
        &self,
        timeline_id: TimelineId,
    ) -> PersistenceFuture<'_, Result<TimelineSnapshot, ReadError>> {
        Box::pin(async move { self.read_snapshot(timeline_id).await })
    }
}

fn corrupt(message: impl Into<String>) -> ReadError {
    ReadError::StorageUnavailable {
        message: message.into(),
    }
}

fn sql_read_error(error: sqlx::Error) -> ReadError {
    corrupt(format!("PostgreSQL authority read failed: {error}"))
}

fn parse_identity<T>(value: &str, label: &str) -> Result<T, ReadError>
where
    T: FromStr,
    T::Err: Display,
{
    value
        .parse()
        .map_err(|error| corrupt(format!("invalid persisted {label}: {error}")))
}

fn parse_u64(value: &str, label: &str) -> Result<u64, ReadError> {
    value
        .parse()
        .map_err(|error| corrupt(format!("invalid persisted {label}: {error}")))
}

fn row_string(row: &sqlx::postgres::PgRow, column: &str) -> Result<String, ReadError> {
    row.try_get(column).map_err(sql_read_error)
}

fn row_i64(row: &sqlx::postgres::PgRow, column: &str) -> Result<i64, ReadError> {
    row.try_get(column).map_err(sql_read_error)
}

fn row_json(row: &sqlx::postgres::PgRow, column: &str) -> Result<Value, ReadError> {
    row.try_get(column).map_err(sql_read_error)
}

fn schema_revision(row: &sqlx::postgres::PgRow) -> Result<SchemaRevision, ReadError> {
    let value = u32::try_from(row_i64(row, "schema_revision")?)
        .map_err(|_| corrupt("schema_revision exceeds u32"))?;
    Ok(SchemaRevision::new(value))
}

fn optional_identity<T>(
    row: &sqlx::postgres::PgRow,
    column: &str,
    label: &str,
) -> Result<Option<T>, ReadError>
where
    T: FromStr,
    T::Err: Display,
{
    row.try_get::<Option<String>, _>(column)
        .map_err(sql_read_error)?
        .map(|value| parse_identity(&value, label))
        .transpose()
}

fn parse_work_status(value: &str) -> Result<WorkStatus, ReadError> {
    match value {
        "pending" => Ok(WorkStatus::Pending),
        "completed" => Ok(WorkStatus::Completed),
        "cancelled" => Ok(WorkStatus::Cancelled),
        "dead" => Ok(WorkStatus::Dead),
        other => Err(corrupt(format!("invalid persisted Work status {other}"))),
    }
}
'''
text = read(postgres)
marker = "\n#[cfg(test)]\nmod tests"
if marker not in text:
    raise SystemExit("postgres test module marker not found")
text = text.replace(marker, read_impl + marker, 1)
write(postgres, text)

postgres_test = r'''

    #[tokio::test]
    async fn postgres_18_read_snapshot_parity() {
        let Some(database_url) = postgres_url() else {
            return;
        };
        let storage = PgStorage::connect(&database_url)
            .await
            .expect("PostgreSQL test database should accept connections");
        storage.migrate().await.expect("migrations should be current");

        let world_id = "00000000-0000-0000-0000-000000000201";
        let timeline_id = "00000000-0000-0000-0000-000000000202";
        let entity_a = "00000000-0000-0000-0000-000000000203";
        let entity_b = "00000000-0000-0000-0000-000000000204";
        let relationship_id = "00000000-0000-0000-0000-000000000205";
        let event_first = "00000000-0000-0000-0000-000000000299";
        let event_second = "00000000-0000-0000-0000-000000000210";
        let work_id = "00000000-0000-0000-0000-000000000211";

        sqlx::query("INSERT INTO loom_world (world_id) VALUES ($1::uuid) ON CONFLICT DO NOTHING")
            .bind(world_id)
            .execute(&storage.pool)
            .await
            .expect("read fixture World should insert");
        sqlx::query(
            "INSERT INTO loom_timeline \
             (timeline_id, world_id, head_event_seq, state_revision, world_time) \
             VALUES ($1::uuid, $2::uuid, 2, 3, 42) ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(world_id)
        .execute(&storage.pool)
        .await
        .expect("read fixture Timeline should insert");
        for entity_id in [entity_a, entity_b] {
            sqlx::query(
                "INSERT INTO loom_entity (timeline_id, entity_id) VALUES ($1::uuid, $2::uuid) \
                 ON CONFLICT DO NOTHING",
            )
            .bind(timeline_id)
            .bind(entity_id)
            .execute(&storage.pool)
            .await
            .expect("read fixture Entity should insert");
        }
        sqlx::query(
            "INSERT INTO loom_relationship \
             (timeline_id, relationship_id, relationship_type, active) \
             VALUES ($1::uuid, $2::uuid, 'test.membership', FALSE) ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(relationship_id)
        .execute(&storage.pool)
        .await
        .expect("read fixture Relationship should insert");
        sqlx::query(
            "INSERT INTO loom_relationship_participant \
             (timeline_id, relationship_id, participant_order, entity_id, role) \
             VALUES ($1::uuid, $2::uuid, 0, $3::uuid, 'member') ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(relationship_id)
        .bind(entity_a)
        .execute(&storage.pool)
        .await
        .expect("Relationship participant should insert");
        sqlx::query(
            "INSERT INTO loom_entity_facet \
             (timeline_id, entity_id, facet_type, schema_revision, value) \
             VALUES ($1::uuid, $2::uuid, 'test.counter', 1, '{\"value\":7}'::jsonb) \
             ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(entity_a)
        .execute(&storage.pool)
        .await
        .expect("Entity Facet should insert");
        sqlx::query(
            "INSERT INTO loom_relationship_facet \
             (timeline_id, relationship_id, facet_type, schema_revision, value) \
             VALUES ($1::uuid, $2::uuid, 'test.relationship_state', 2, '{\"ended\":true}'::jsonb) \
             ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(relationship_id)
        .execute(&storage.pool)
        .await
        .expect("Relationship Facet should insert");

        // Insert EventSeq 2 first and give EventSeq 1 the lexicographically larger UUID.
        // A correct adapter must still return [1, 2].
        for (event_id, sequence, event_type, occurred_at) in [
            (event_second, 2_i64, "test.second", 42_i64),
            (event_first, 1_i64, "test.first", 40_i64),
        ] {
            sqlx::query(
                "INSERT INTO loom_event \
                 (timeline_id, event_id, event_seq, event_type, schema_revision, occurred_at, payload, effects) \
                 VALUES ($1::uuid, $2::uuid, $3, $4, 1, $5, '{}'::jsonb, '[]'::jsonb) \
                 ON CONFLICT DO NOTHING",
            )
            .bind(timeline_id)
            .bind(event_id)
            .bind(sequence)
            .bind(event_type)
            .bind(occurred_at)
            .execute(&storage.pool)
            .await
            .expect("Event fixture should insert");
        }
        sqlx::query(
            "INSERT INTO loom_event_participant \
             (timeline_id, event_id, participant_order, entity_id, role) \
             VALUES ($1::uuid, $2::uuid, 0, $3::uuid, 'actor') ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(event_first)
        .bind(entity_a)
        .execute(&storage.pool)
        .await
        .expect("Event participant should insert");
        sqlx::query(
            "INSERT INTO loom_event_relationship_ref \
             (timeline_id, event_id, reference_order, relationship_id, role) \
             VALUES ($1::uuid, $2::uuid, 0, $3::uuid, 'subject') ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(event_first)
        .bind(relationship_id)
        .execute(&storage.pool)
        .await
        .expect("Event Relationship reference should insert");
        sqlx::query(
            "INSERT INTO loom_event_causal_link \
             (timeline_id, event_id, causal_order, cause_event_id) \
             VALUES ($1::uuid, $2::uuid, 0, $3::uuid) ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(event_second)
        .bind(event_first)
        .execute(&storage.pool)
        .await
        .expect("Event causal link should insert");
        sqlx::query(
            "INSERT INTO loom_work \
             (timeline_id, work_id, handler, schema_revision, payload, due_world_time, status, \
              attempt_count, claim_generation, available_at) \
             VALUES ($1::uuid, $2::uuid, 'test.handler', 1, '{}'::jsonb, 50, 'pending', 2, 4, 9) \
             ON CONFLICT DO NOTHING",
        )
        .bind(timeline_id)
        .bind(work_id)
        .execute(&storage.pool)
        .await
        .expect("Work fixture should insert");

        let timeline: loom_core::TimelineId = timeline_id.parse().expect("TimelineId should parse");
        let snapshot = WorldStore::snapshot(&storage, timeline)
            .await
            .expect("PostgreSQL snapshot should reconstruct the fixture");
        assert_eq!(snapshot.version().head_event_seq.value(), 2);
        assert_eq!(snapshot.version().state_revision.value(), 3);
        assert_eq!(snapshot.world_time().value(), 42);
        assert_eq!(snapshot.events.len(), 2);
        assert_eq!(snapshot.events[0].event_seq.value(), 1);
        assert_eq!(snapshot.events[1].event_seq.value(), 2);
        assert_eq!(snapshot.events[0].id.to_string(), event_first);
        assert_eq!(snapshot.events[0].participants.len(), 1);
        assert_eq!(snapshot.events[0].relationship_refs.len(), 1);
        assert_eq!(snapshot.events[1].causal_links[0].event_id(), snapshot.events[0].id);
        assert_eq!(snapshot.works.len(), 1);
        assert_eq!(snapshot.works[0].attempt_count, 2);
        assert_eq!(snapshot.works[0].claim_generation, 4);
        assert_eq!(snapshot.works[0].available_at.value(), 9);

        let view = snapshot.world_view();
        let entity: loom_core::EntityId = entity_a.parse().expect("EntityId should parse");
        assert!(view.entity(entity).is_some());
        let relationship: loom_core::RelationshipId = relationship_id
            .parse()
            .expect("RelationshipId should parse");
        assert!(view.relationship(relationship).is_none(), "ended Relationship must not be active");
        assert_eq!(
            view.facet(
                loom_core::FacetOwner::entity(entity),
                &loom_core::FacetTypeId::from("test.counter"),
            )
            .expect("Entity Facet should be reconstructed")
            .value(),
            &serde_json::json!({"value": 7}),
        );

        let missing: loom_core::TimelineId =
            "00000000-0000-0000-0000-000000000298".parse().expect("missing TimelineId should parse");
        assert!(matches!(
            WorldStore::snapshot(&storage, missing).await,
            Err(loom_runtime::ReadError::TimelineNotFound { .. })
        ));
        storage.close().await;
    }
'''
text = read(postgres)
last = text.rfind("\n}")
if last < 0:
    raise SystemExit("postgres module closing brace not found")
text = text[:last] + postgres_test + text[last:]
write(postgres, text)

contracts = "docs/architecture/runtime-contracts.md"
replace_once(
    contracts,
    "Application composition root 负责实例化 concrete Storage 并注入 Runtime。",
    "Application composition root 负责实例化 concrete Storage 并注入 Runtime。\n\nPersistence I/O port 返回 executor-neutral Future；Runtime 可以 await SQLx 等异步 adapter，但不会把 executor、database handle 或 Future 传给 Capability。Resolver/Invariant/WorkHandler 始终只读取 Runtime 已经 pin 好的内存 `BaseWorldView`，因此 Capability semantic execution 不承担数据库 I/O。",
)

print("M2-T2 source migration applied")
