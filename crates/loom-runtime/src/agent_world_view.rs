//! Runtime-owned construction of the subjective Agent context.
//!
//! The plan contains only value requests and semantic identities. Runtime
//! resolves those requests through the Session-pinned read boundary, applies
//! World Runtime Binding checks and context budgets, and returns the finite
//! `loom-agency` value. No plan or builder method exposes a `BaseWorldView`,
//! `WorldStore` or read-port handle to Agency or cognition.

use std::{error::Error, fmt};

use loom_agency::{
    AgentContextEntry, AgentContextRequest, AgentContextSnapshot, AgentWorldView, ContextBudget,
    ContextBudgetUsage, ContextSource,
};
use loom_capability::{
    CapabilityRegistry, SemanticQueryError, SemanticQueryRequest, SemanticQueryResult,
};
use loom_core::{
    EntityId, EventId, EventRef, FacetOwner, FacetTypeId, RelationshipId, TimelineVersion,
};
use serde_json::{Value, json};

use crate::{
    ExecutionAssembly, PinnedReadBoundary, PinnedReadPolicy, PinnedReadSession,
    PinnedWorldReadStore, ReadError, SemanticProjectionError, SemanticProjectionFilter,
    SemanticProjectionKey, SemanticProjectionQuery, SemanticProjectionStore,
    semantic_projection_hit_bytes,
};

/// One value or Runtime-mediated read selected for an Agent context.
///
/// The selection is explicit: there is no operation that enumerates the World
/// or serializes every Facet, Relationship or Event. A Capability/application
/// composition root supplies the semantic keys and visibility decisions, while
/// Runtime owns execution of the requested reads and their bounds.
#[derive(Clone, Debug, PartialEq)]
pub enum AgentContextItem {
    /// An already-filtered Agent-local observation or Capability-owned value.
    Value {
        /// Semantic key assigned by the selecting Capability/application.
        key: String,
        /// Subjective provenance category for the value.
        source: ContextSource,
        /// Value already selected for this Agent.
        value: Value,
    },
    /// A Runtime-mediated Entity read selected for the context.
    Entity {
        /// Semantic key assigned to the selected observation.
        key: String,
        /// Subjective provenance category for the observation.
        source: ContextSource,
        /// Entity identity to read at the pinned version.
        entity_id: EntityId,
    },
    /// A Runtime-mediated Relationship read selected for the context.
    Relationship {
        /// Semantic key assigned to the selected observation.
        key: String,
        /// Subjective provenance category for the observation.
        source: ContextSource,
        /// Relationship identity to read at the pinned version.
        relationship_id: RelationshipId,
    },
    /// A Runtime-mediated Facet read selected by its owning Capability.
    Facet {
        /// Semantic key assigned to the selected value.
        key: String,
        /// Subjective provenance category for the value.
        source: ContextSource,
        /// Structural owner of the Facet.
        owner: FacetOwner,
        /// Capability-owned Facet schema identity.
        facet_type: FacetTypeId,
    },
    /// A Runtime-mediated Event read selected by its owning Capability.
    Event {
        /// Semantic key assigned to the selected observation.
        key: String,
        /// Subjective provenance category for the observation.
        source: ContextSource,
        /// Event identity to read at the pinned version.
        event_id: EventId,
    },
    /// A bounded, Binding-checked semantic retrieval request.
    Semantic {
        /// Semantic key assigned to the selected retrieval result.
        key: String,
        /// Subjective provenance category for the result.
        source: ContextSource,
        /// Capability-owned semantic request mediated by Runtime.
        request: SemanticQueryRequest,
    },
}

impl AgentContextItem {
    /// Creates an already-filtered context value.
    #[must_use]
    pub fn value(key: impl Into<String>, source: ContextSource, value: Value) -> Self {
        Self::Value {
            key: key.into(),
            source,
            value,
        }
    }

    /// Creates an Entity read selection.
    #[must_use]
    pub fn entity(key: impl Into<String>, source: ContextSource, entity_id: EntityId) -> Self {
        Self::Entity {
            key: key.into(),
            source,
            entity_id,
        }
    }

    /// Creates a Relationship read selection.
    #[must_use]
    pub fn relationship(
        key: impl Into<String>,
        source: ContextSource,
        relationship_id: RelationshipId,
    ) -> Self {
        Self::Relationship {
            key: key.into(),
            source,
            relationship_id,
        }
    }

    /// Creates a Facet read selection.
    #[must_use]
    pub fn facet(
        key: impl Into<String>,
        source: ContextSource,
        owner: FacetOwner,
        facet_type: FacetTypeId,
    ) -> Self {
        Self::Facet {
            key: key.into(),
            source,
            owner,
            facet_type,
        }
    }

    /// Creates an Event read selection.
    #[must_use]
    pub fn event(key: impl Into<String>, source: ContextSource, event_id: EventId) -> Self {
        Self::Event {
            key: key.into(),
            source,
            event_id,
        }
    }

    /// Creates a semantic retrieval selection.
    #[must_use]
    pub fn semantic(
        key: impl Into<String>,
        source: ContextSource,
        request: SemanticQueryRequest,
    ) -> Self {
        Self::Semantic {
            key: key.into(),
            source,
            request,
        }
    }
}

/// Explicit context selection supplied to Runtime for one Agent wake.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct AgentContextPlan {
    items: Vec<AgentContextItem>,
}

impl AgentContextPlan {
    /// Creates an empty plan. Empty is the safe default; Runtime never scans
    /// the World to fill omitted context.
    #[must_use]
    pub const fn new() -> Self {
        Self { items: Vec::new() }
    }

    /// Appends one explicit selection.
    #[must_use]
    pub fn with_item(mut self, item: AgentContextItem) -> Self {
        self.items.push(item);
        self
    }

    /// Returns selections in the order Runtime will evaluate them.
    #[must_use]
    pub fn items(&self) -> &[AgentContextItem] {
        &self.items
    }
}

/// Typed failure while constructing a subjective Agent context.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AgentWorldViewError {
    /// A request did not match the already-pinned Session coordinate.
    PinnedContextMismatch {
        /// Coordinate field that differed.
        field: String,
        /// Session/request value expected by Runtime.
        expected: String,
        /// Value supplied by the context request.
        actual: String,
    },
    /// A Runtime point read failed or observed a version fence.
    Read(ReadError),
    /// A requested Capability semantic domain is not enabled in the pinned
    /// World Binding or is not present in the installed registry.
    VisibilityDenied {
        /// Semantic category that was denied.
        kind: String,
        /// Caller-supplied selection key.
        key: String,
    },
    /// A Runtime-mediated semantic retrieval failed.
    Semantic(SemanticQueryError),
    /// A context dimension exceeded its pinned budget.
    BudgetExceeded {
        /// Budget dimension that was exceeded.
        dimension: String,
        /// Maximum accepted value.
        limit: u32,
        /// Requested or measured value.
        actual: u32,
    },
    /// A selection could not be represented as a bounded context value.
    InvalidRequest {
        /// Boundary-safe explanation.
        message: String,
    },
}

impl fmt::Display for AgentWorldViewError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::PinnedContextMismatch {
                field,
                expected,
                actual,
            } => write!(
                formatter,
                "Agent context {field} mismatch: expected {expected}, got {actual}"
            ),
            Self::Read(error) => error.fmt(formatter),
            Self::VisibilityDenied { kind, key } => {
                write!(
                    formatter,
                    "Agent context {kind} visibility denied for {key}"
                )
            }
            Self::Semantic(error) => error.fmt(formatter),
            Self::BudgetExceeded {
                dimension,
                limit,
                actual,
            } => write!(
                formatter,
                "Agent context {dimension} budget exceeded: {actual} > {limit}"
            ),
            Self::InvalidRequest { message } => formatter.write_str(message),
        }
    }
}

impl Error for AgentWorldViewError {}

impl From<ReadError> for AgentWorldViewError {
    fn from(error: ReadError) -> Self {
        Self::Read(error)
    }
}

/// Runtime-owned builder for one finite, subjective Agent view.
pub struct AgentWorldViewBuilder<'store, S> {
    boundary: PinnedReadBoundary<'store, S>,
}

impl<'store, S> AgentWorldViewBuilder<'store, S>
where
    S: PinnedWorldReadStore,
{
    /// Creates a builder over the Runtime-owned pinned-read port.
    #[must_use]
    pub fn new(store: &'store S, policy: PinnedReadPolicy) -> Self {
        Self {
            boundary: PinnedReadBoundary::new(store, policy),
        }
    }

    /// Returns point-read metrics collected during context construction.
    #[must_use]
    pub const fn metrics(&self) -> crate::PinnedReadMetrics {
        self.boundary.metrics()
    }

    /// Builds a subjective view from one Session-pinned read identity.
    ///
    /// The caller supplies explicit local observations and Capability-owned
    /// selections. Runtime executes only those selections, checks semantic
    /// owners against the pinned Binding/revision, and records every actual
    /// point/semantic dependency in the supplied Session's `ReadSet`.
    ///
    /// # Errors
    ///
    /// Returns a typed error when the request is not pinned to the supplied
    /// Session, a selected semantic domain is not enabled, a point read is
    /// fenced, or a context budget is exceeded.
    #[expect(
        clippy::too_many_lines,
        reason = "the ordered selection loop is the single context assembly boundary"
    )]
    pub async fn build(
        &mut self,
        session: &PinnedReadSession,
        request: AgentContextRequest,
        plan: &AgentContextPlan,
        registry: &CapabilityRegistry,
        assembly: &ExecutionAssembly,
    ) -> Result<AgentWorldView, AgentWorldViewError>
    where
        S: SemanticProjectionStore,
    {
        validate_assembly_coordinate(session, assembly)?;
        validate_request_coordinate(session, &request)?;
        let mut entries = Vec::new();
        let mut usage = ContextUsage::default();
        for item in plan.items() {
            match item {
                AgentContextItem::Value { key, source, value } => {
                    append_entry(
                        &mut entries,
                        &mut usage,
                        AgentContextEntry::new(key.clone(), *source, value.clone()),
                        request.budget,
                    )?;
                }
                AgentContextItem::Entity {
                    key,
                    source,
                    entity_id,
                } => {
                    usage.entities =
                        bounded_increment("entities", usage.entities, request.budget.max_entities)?;
                    if let Some(entity) = self
                        .boundary
                        .entity(session, *entity_id)
                        .await?
                        .into_value()
                    {
                        append_entry(
                            &mut entries,
                            &mut usage,
                            AgentContextEntry::new(
                                key.clone(),
                                *source,
                                serde_json::to_value(entity)
                                    .map_err(|error| value_error(&error))?,
                            ),
                            request.budget,
                        )?;
                    }
                }
                AgentContextItem::Relationship {
                    key,
                    source,
                    relationship_id,
                } => {
                    usage.relationships = bounded_increment(
                        "relationships",
                        usage.relationships,
                        request.budget.max_relationships,
                    )?;
                    let relationship = self
                        .boundary
                        .relationship(session, *relationship_id)
                        .await?
                        .into_value();
                    let Some(relationship) = relationship else {
                        continue;
                    };
                    let registered = registry.relationship(&relationship.relationship_type);
                    if registered.is_none_or(|registered| {
                        !enabled_capability(registry, assembly, &registered.owner)
                    }) {
                        return Err(AgentWorldViewError::VisibilityDenied {
                            kind: "relationship".to_owned(),
                            key: key.clone(),
                        });
                    }
                    append_entry(
                        &mut entries,
                        &mut usage,
                        AgentContextEntry::new(
                            key.clone(),
                            *source,
                            serde_json::to_value(relationship)
                                .map_err(|error| value_error(&error))?,
                        ),
                        request.budget,
                    )?;
                }
                AgentContextItem::Facet {
                    key,
                    source,
                    owner,
                    facet_type,
                } => {
                    let Some(registered) = registry.facet(facet_type) else {
                        return Err(AgentWorldViewError::VisibilityDenied {
                            kind: "facet".to_owned(),
                            key: key.clone(),
                        });
                    };
                    if !enabled_capability(registry, assembly, &registered.owner) {
                        return Err(AgentWorldViewError::VisibilityDenied {
                            kind: "facet".to_owned(),
                            key: key.clone(),
                        });
                    }
                    if let Some(facet) = self
                        .boundary
                        .facet(session, *owner, facet_type)
                        .await?
                        .into_value()
                    {
                        append_entry(
                            &mut entries,
                            &mut usage,
                            AgentContextEntry::new(key.clone(), *source, facet.value),
                            request.budget,
                        )?;
                    }
                }
                AgentContextItem::Event {
                    key,
                    source,
                    event_id,
                } => {
                    usage.events =
                        bounded_increment("events", usage.events, request.budget.max_events)?;
                    let event = self.boundary.event(session, *event_id).await?.into_value();
                    let Some(event) = event else {
                        continue;
                    };
                    let Some(registered) = registry.event(&event.event_type) else {
                        return Err(AgentWorldViewError::VisibilityDenied {
                            kind: "event".to_owned(),
                            key: key.clone(),
                        });
                    };
                    if !enabled_capability(registry, assembly, &registered.owner) {
                        return Err(AgentWorldViewError::VisibilityDenied {
                            kind: "event".to_owned(),
                            key: key.clone(),
                        });
                    }
                    append_entry(
                        &mut entries,
                        &mut usage,
                        AgentContextEntry::new(key.clone(), *source, event_value(&event)),
                        request.budget,
                    )?;
                }
                AgentContextItem::Semantic {
                    key,
                    source,
                    request: semantic_request,
                } => {
                    usage.semantic_queries = bounded_increment(
                        "semantic_queries",
                        usage.semantic_queries,
                        request.budget.max_semantic_queries,
                    )?;
                    if semantic_request.depth > request.budget.max_depth {
                        return Err(AgentWorldViewError::BudgetExceeded {
                            dimension: "depth".to_owned(),
                            limit: request.budget.max_depth,
                            actual: semantic_request.depth,
                        });
                    }
                    let result = self
                        .semantic(
                            session,
                            semantic_request,
                            registry,
                            assembly,
                            request.budget,
                        )
                        .await?;
                    usage.semantic_results = usage
                        .semantic_results
                        .checked_add(u32::try_from(result.hits.len()).unwrap_or(u32::MAX))
                        .ok_or_else(|| AgentWorldViewError::BudgetExceeded {
                            dimension: "semantic_results".to_owned(),
                            limit: request.budget.max_semantic_results,
                            actual: u32::MAX,
                        })?;
                    if usage.semantic_results > request.budget.max_semantic_results {
                        return Err(AgentWorldViewError::BudgetExceeded {
                            dimension: "semantic_results".to_owned(),
                            limit: request.budget.max_semantic_results,
                            actual: usage.semantic_results,
                        });
                    }
                    usage.depth = usage.depth.max(semantic_request.depth);
                    append_entry(
                        &mut entries,
                        &mut usage,
                        AgentContextEntry::new(
                            key.clone(),
                            *source,
                            serde_json::to_value(result).map_err(|error| value_error(&error))?,
                        ),
                        request.budget,
                    )?;
                }
            }
        }

        let snapshot = AgentContextSnapshot::new(
            entries,
            ContextBudgetUsage::with_reads(
                usage.entries,
                usage.bytes,
                usage.entities,
                usage.relationships,
                usage.events,
                usage.semantic_results,
                usage.depth,
                usage.semantic_queries,
            ),
        );
        Ok(AgentWorldView::new(
            request.agent,
            request.timeline_id,
            request.version,
            request.world_time,
            snapshot,
        ))
    }

    #[expect(
        clippy::too_many_lines,
        reason = "semantic retrieval keeps validation, fencing and provenance together"
    )]
    async fn semantic(
        &self,
        session: &PinnedReadSession,
        request: &SemanticQueryRequest,
        registry: &CapabilityRegistry,
        assembly: &ExecutionAssembly,
        budget: ContextBudget,
    ) -> Result<SemanticQueryResult, AgentWorldViewError>
    where
        S: SemanticProjectionStore,
    {
        let Some(index) = registry.semantic_index(&request.index_id) else {
            return Err(AgentWorldViewError::Semantic(SemanticQueryError::Missing {
                index_id: request.index_id.clone(),
            }));
        };
        if !enabled_capability(registry, assembly, &index.owner) {
            return Err(AgentWorldViewError::VisibilityDenied {
                kind: "semantic".to_owned(),
                key: request.index_id.to_string(),
            });
        }
        if request.limit > budget.max_semantic_results {
            return Err(AgentWorldViewError::BudgetExceeded {
                dimension: "semantic_results".to_owned(),
                limit: budget.max_semantic_results,
                actual: request.limit,
            });
        }
        let max_result_bytes = assembly
            .execution_policy()
            .max_semantic_result_bytes()
            .unwrap_or(crate::MAX_SEMANTIC_QUERY_RESULT_BYTES as usize)
            .min(crate::MAX_SEMANTIC_QUERY_RESULT_BYTES as usize)
            .min(usize::try_from(budget.max_bytes).unwrap_or(usize::MAX));
        let max_result_bytes = u32::try_from(max_result_bytes).unwrap_or(u32::MAX);
        if max_result_bytes == 0 {
            return Err(AgentWorldViewError::BudgetExceeded {
                dimension: "bytes".to_owned(),
                limit: 0,
                actual: 1,
            });
        }
        let mut query = SemanticProjectionQuery::new(
            SemanticProjectionKey::new(
                assembly.world_id(),
                assembly.timeline_id(),
                request.index_id.clone(),
            ),
            request.source_schema_revision,
            request.projection_revision,
            request.model_revision.clone(),
            request.vector.clone(),
            request.limit,
        )
        .map_err(map_semantic_projection_error)?
        .with_max_result_bytes(max_result_bytes)
        .with_depth(request.depth);
        for filter in &request.filters {
            query = query.with_filter(SemanticProjectionFilter {
                source_hash: filter.source_hash.clone(),
            });
        }
        let hits = self
            .boundary
            .store()
            .query_semantic_projection(query)
            .await
            .map_err(map_semantic_projection_error)?;
        if hits
            .iter()
            .any(|hit| !version_at_or_before(hit.source_revision, session.version()))
        {
            let hit = hits
                .iter()
                .find(|hit| !version_at_or_before(hit.source_revision, session.version()))
                .expect("a future semantic source revision exists");
            return Err(AgentWorldViewError::Semantic(SemanticQueryError::Stale {
                field: "source_revision".to_owned(),
                expected: format!("at most {:?}", session.version()),
                actual: format!("{:?}", hit.source_revision),
            }));
        }
        let result_bytes = hits
            .iter()
            .map(semantic_projection_hit_bytes)
            .sum::<usize>();
        if result_bytes > max_result_bytes as usize {
            return Err(AgentWorldViewError::Semantic(SemanticQueryError::Bounds {
                dimension: "semantic_result_bytes".to_owned(),
                limit: max_result_bytes as usize,
                actual: result_bytes,
            }));
        }
        let source_refs = hits
            .iter()
            .map(|hit| hit.source_ref)
            .collect::<Vec<EventRef>>();
        let query_spec = normalized_semantic_query_spec(request);
        session.record_semantic(
            request.index_id.clone(),
            semantic_query_fingerprint(&query_spec),
            query_spec,
            request.source_schema_revision,
            request.projection_revision,
            request.model_revision.clone(),
            source_refs,
        );
        Ok(SemanticQueryResult {
            hits: hits
                .into_iter()
                .map(|hit| loom_capability::SemanticQueryHit {
                    source_ref: hit.source_ref,
                    source_hash: hit.source_hash,
                    source_revision: hit.source_revision,
                    projection_revision: hit.projection_revision,
                    model_revision: hit.model_revision,
                    distance: hit.distance,
                })
                .collect(),
        })
    }
}

#[derive(Clone, Copy, Debug, Default)]
struct ContextUsage {
    entries: u32,
    bytes: u64,
    entities: u32,
    relationships: u32,
    events: u32,
    semantic_results: u32,
    depth: u32,
    semantic_queries: u32,
}

fn validate_request_coordinate(
    session: &PinnedReadSession,
    request: &AgentContextRequest,
) -> Result<(), AgentWorldViewError> {
    for (field, expected, actual) in [
        (
            "timeline_id",
            session.timeline_id().to_string(),
            request.timeline_id.to_string(),
        ),
        (
            "version",
            format!("{:?}", session.version()),
            format!("{:?}", request.version),
        ),
        (
            "world_time",
            format!("{:?}", session.world_time()),
            format!("{:?}", request.world_time),
        ),
    ] {
        if expected != actual {
            return Err(AgentWorldViewError::PinnedContextMismatch {
                field: field.to_owned(),
                expected,
                actual,
            });
        }
    }
    Ok(())
}

fn validate_assembly_coordinate(
    session: &PinnedReadSession,
    assembly: &ExecutionAssembly,
) -> Result<(), AgentWorldViewError> {
    for (field, expected, actual) in [
        (
            "session_id",
            session.session_id().to_string(),
            assembly.session_id().to_string(),
        ),
        (
            "world_id",
            session.world_id().to_string(),
            assembly.world_id().to_string(),
        ),
        (
            "timeline_id",
            session.timeline_id().to_string(),
            assembly.timeline_id().to_string(),
        ),
        (
            "version",
            format!("{:?}", session.version()),
            format!("{:?}", assembly.expected_version()),
        ),
        (
            "world_time",
            format!("{:?}", session.world_time()),
            format!("{:?}", assembly.world_time()),
        ),
    ] {
        if expected != actual {
            return Err(AgentWorldViewError::PinnedContextMismatch {
                field: field.to_owned(),
                expected,
                actual,
            });
        }
    }
    Ok(())
}

fn bounded_increment(
    dimension: &str,
    current: u32,
    limit: u32,
) -> Result<u32, AgentWorldViewError> {
    let actual = current.saturating_add(1);
    if actual > limit {
        return Err(AgentWorldViewError::BudgetExceeded {
            dimension: dimension.to_owned(),
            limit,
            actual,
        });
    }
    Ok(actual)
}

fn append_entry(
    entries: &mut Vec<AgentContextEntry>,
    usage: &mut ContextUsage,
    entry: AgentContextEntry,
    budget: ContextBudget,
) -> Result<(), AgentWorldViewError> {
    usage.entries = bounded_increment("entries", usage.entries, budget.max_entries)?;
    let bytes = serde_json::to_vec(&entry)
        .map_err(|error| value_error(&error))?
        .len() as u64;
    usage.bytes =
        usage
            .bytes
            .checked_add(bytes)
            .ok_or_else(|| AgentWorldViewError::BudgetExceeded {
                dimension: "bytes".to_owned(),
                limit: u32::try_from(budget.max_bytes).unwrap_or(u32::MAX),
                actual: u32::MAX,
            })?;
    if usage.bytes > budget.max_bytes {
        return Err(AgentWorldViewError::BudgetExceeded {
            dimension: "bytes".to_owned(),
            limit: u32::try_from(budget.max_bytes).unwrap_or(u32::MAX),
            actual: u32::try_from(usage.bytes).unwrap_or(u32::MAX),
        });
    }
    entries.push(entry);
    Ok(())
}

fn enabled_capability(
    registry: &CapabilityRegistry,
    assembly: &ExecutionAssembly,
    capability: &loom_capability::CapabilityId,
) -> bool {
    let Some(manifest) = registry.capability(capability) else {
        return false;
    };
    assembly.binding().allows(capability, &manifest.version)
        && assembly
            .implementations()
            .capability(capability)
            .is_some_and(|implementation| {
                implementation.version() == &manifest.version
                    && implementation.loom_compatibility() == &manifest.loom_compatibility
            })
}

fn event_value(event: &crate::CommittedEvent) -> Value {
    json!({
        "id": event.id,
        "timeline_id": event.timeline_id,
        "event_seq": event.event_seq,
        "event_type": event.event_type,
        "schema_revision": event.schema_revision,
        "occurred_at": event.occurred_at,
        "participants": event.participants,
        "relationship_refs": event.relationship_refs,
        "causal_links": event.causal_links,
        "payload": event.payload,
    })
}

fn version_at_or_before(candidate: TimelineVersion, pinned: TimelineVersion) -> bool {
    candidate.head_event_seq.value() <= pinned.head_event_seq.value()
        && candidate.state_revision.value() <= pinned.state_revision.value()
}

fn normalized_semantic_query_spec(request: &SemanticQueryRequest) -> String {
    let mut filters = request
        .filters
        .iter()
        .map(|filter| filter.source_hash.as_deref().unwrap_or("<none>").to_owned())
        .collect::<Vec<_>>();
    filters.sort();
    let vector = request
        .vector
        .iter()
        .map(|value| value.to_bits().to_string())
        .collect::<Vec<_>>()
        .join(",");
    format!(
        "index={}|source_schema={}|projection={}|model={}|limit={}|depth={}|filters={}|vector={}",
        request.index_id,
        request.source_schema_revision,
        request.projection_revision,
        request.model_revision,
        request.limit,
        request.depth,
        filters.join(","),
        vector,
    )
}

fn semantic_query_fingerprint(spec: &str) -> String {
    let mut hash = 14_695_981_039_346_656_037_u64;
    for byte in spec.bytes() {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(1_099_511_628_211);
    }
    format!("{hash:016x}")
}

fn value_error(error: &serde_json::Error) -> AgentWorldViewError {
    AgentWorldViewError::InvalidRequest {
        message: format!("Agent context value is not serializable: {error}"),
    }
}

fn map_semantic_projection_error(error: SemanticProjectionError) -> AgentWorldViewError {
    let error = match error {
        SemanticProjectionError::InvalidRequest { message } => {
            SemanticQueryError::InvalidRequest { message }
        }
        SemanticProjectionError::ScopeNotFound { .. } => SemanticQueryError::Missing {
            index_id: loom_capability::SemanticIndexId::from("unknown"),
        },
        SemanticProjectionError::IndexNotRegistered { key } => SemanticQueryError::Missing {
            index_id: key.index_id,
        },
        SemanticProjectionError::MetadataMismatch {
            field,
            expected,
            actual,
        } => SemanticQueryError::Mismatch {
            field,
            expected,
            actual,
        },
        SemanticProjectionError::SourceMismatch { expected, actual } => SemanticQueryError::Stale {
            field: "source_schema_revision".to_owned(),
            expected,
            actual,
        },
        SemanticProjectionError::RevisionMismatch { expected, actual } => {
            SemanticQueryError::Stale {
                field: "projection_revision".to_owned(),
                expected: expected.to_string(),
                actual: actual.to_string(),
            }
        }
        SemanticProjectionError::DimensionMismatch { expected, actual } => {
            SemanticQueryError::Mismatch {
                field: "dimensions".to_owned(),
                expected,
                actual,
            }
        }
        SemanticProjectionError::LimitExceeded { limit, actual } => SemanticQueryError::Bounds {
            dimension: "semantic_result_bytes".to_owned(),
            limit: limit as usize,
            actual: actual as usize,
        },
        SemanticProjectionError::StorageUnavailable { message } => {
            SemanticQueryError::Unavailable { message }
        }
    };
    AgentWorldViewError::Semantic(error)
}

#[cfg(test)]
mod tests {
    use std::{future::Future, str::FromStr, task::Waker};

    use loom_agency::{AgentContextRequest, AgentRef};
    use loom_capability::{
        Capability, CapabilityId, CapabilityManifest, CapabilityRegistrar, RegistrationError,
        SemanticIndexDefinition, SemanticIndexMetric, SemanticIndexSource, SemanticQueryRequest,
    };
    use loom_core::{
        Entity, EntityId, EventId, FacetOwner, FacetTypeId, Relationship, RelationshipId,
        SchemaRevision, TimelineId, TimelineVersion, WorldId, WorldInstant,
    };
    use semver::{Version, VersionReq};
    use serde_json::json;

    use super::*;
    use crate::{
        CommittedEvent, EntropySourceId, PersistenceFuture, PinnedFacet, PinnedRead,
        ReadDependency, ReadError, RuntimeRevisionCapability, RuntimeRevisionDescriptor,
        RuntimeRevisionId, RuntimeRevisionSelection, SemanticProjectionError,
        SemanticProjectionHit, SemanticProjectionKey, SemanticProjectionQuery,
        SemanticProjectionRebuild, SemanticProjectionRegistration, WorldRuntimeBinding,
    };

    struct SemanticTestCapability {
        manifest: CapabilityManifest,
    }

    impl Capability for SemanticTestCapability {
        fn manifest(&self) -> &CapabilityManifest {
            &self.manifest
        }

        fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
            registrar.register_semantic_index(SemanticIndexDefinition::new(
                "semantic.test.index",
                SemanticIndexSource::new("facet", "semantic.test.facet", SchemaRevision::new(1)),
                SchemaRevision::new(1),
                1,
                "semantic-model-1",
                2,
                SemanticIndexMetric::Cosine,
                json!({}),
            ))
        }
    }

    #[derive(Default)]
    struct SemanticOnlyStore;

    impl PinnedWorldReadStore for SemanticOnlyStore {
        fn open_pinned_read<'a>(
            &'a self,
            assembly: &'a ExecutionAssembly,
        ) -> PersistenceFuture<'a, Result<PinnedReadSession, ReadError>> {
            let session = PinnedReadSession::new(
                assembly.session_id(),
                assembly.world_id(),
                assembly.timeline_id(),
                assembly.expected_version(),
                assembly.world_time(),
            );
            Box::pin(async move { Ok(session) })
        }

        fn read_entity<'a>(
            &'a self,
            _session: &'a PinnedReadSession,
            _entity_id: EntityId,
        ) -> PersistenceFuture<'a, Result<PinnedRead<Option<Entity>>, ReadError>> {
            Box::pin(async {
                Err(ReadError::StorageUnavailable {
                    message: "point read not used by semantic context test".to_owned(),
                })
            })
        }

        fn read_relationship<'a>(
            &'a self,
            _session: &'a PinnedReadSession,
            _relationship_id: RelationshipId,
        ) -> PersistenceFuture<'a, Result<PinnedRead<Option<Relationship>>, ReadError>> {
            Box::pin(async {
                Err(ReadError::StorageUnavailable {
                    message: "point read not used by semantic context test".to_owned(),
                })
            })
        }

        fn read_facet<'a>(
            &'a self,
            _session: &'a PinnedReadSession,
            _owner: FacetOwner,
            _facet_type: &'a FacetTypeId,
        ) -> PersistenceFuture<'a, Result<PinnedRead<Option<PinnedFacet>>, ReadError>> {
            Box::pin(async {
                Err(ReadError::StorageUnavailable {
                    message: "point read not used by semantic context test".to_owned(),
                })
            })
        }

        fn read_event<'a>(
            &'a self,
            _session: &'a PinnedReadSession,
            _event_id: EventId,
        ) -> PersistenceFuture<'a, Result<PinnedRead<Option<CommittedEvent>>, ReadError>> {
            Box::pin(async {
                Err(ReadError::StorageUnavailable {
                    message: "point read not used by semantic context test".to_owned(),
                })
            })
        }
    }

    impl SemanticProjectionStore for SemanticOnlyStore {
        fn register_semantic_projection(
            &self,
            _registration: SemanticProjectionRegistration,
        ) -> PersistenceFuture<'_, Result<(), SemanticProjectionError>> {
            Box::pin(async { Ok(()) })
        }

        fn query_semantic_projection(
            &self,
            _query: SemanticProjectionQuery,
        ) -> PersistenceFuture<'_, Result<Vec<SemanticProjectionHit>, SemanticProjectionError>>
        {
            Box::pin(async { Ok(Vec::new()) })
        }

        fn rebuild_semantic_projection<'a>(
            &'a self,
            _rebuild: &'a SemanticProjectionRebuild,
        ) -> PersistenceFuture<'a, Result<(), SemanticProjectionError>> {
            Box::pin(async { Ok(()) })
        }

        fn delete_semantic_projection(
            &self,
            _key: SemanticProjectionKey,
        ) -> PersistenceFuture<'_, Result<(), SemanticProjectionError>> {
            Box::pin(async { Ok(()) })
        }
    }

    fn id<T>(value: u128) -> T
    where
        T: FromStr,
        T::Err: std::fmt::Debug,
    {
        format!("00000000-0000-0000-0000-{value:012x}")
            .parse()
            .expect("test identity should parse")
    }

    fn registry() -> CapabilityRegistry {
        CapabilityRegistry::assemble(vec![Box::new(SemanticTestCapability {
            manifest: CapabilityManifest::parse("semantic.test", "0.1.0")
                .expect("semantic test manifest should parse"),
        })])
        .expect("semantic registry should assemble")
    }

    fn binding() -> WorldRuntimeBinding {
        WorldRuntimeBinding::new(
            [(
                CapabilityId::from("semantic.test"),
                VersionReq::parse("^0.1.0").expect("semantic requirement should parse"),
            )],
            json!({"fixture": "semantic-context"}),
            1,
            Some("semantic-context-test".to_owned()),
        )
    }

    fn assembly(
        registry: &CapabilityRegistry,
        session_id: loom_core::ExecutionSessionId,
    ) -> ExecutionAssembly {
        let binding = binding();
        let revision = RuntimeRevisionDescriptor::new(
            RuntimeRevisionId::from("semantic-context-test-revision"),
            crate::PlatformTime::default(),
            "semantic-context-test-build",
            Version::new(0, 1, 0),
            registry.capabilities().map(|manifest| {
                RuntimeRevisionCapability::from_manifest(
                    manifest,
                    format!("test:{}@{}", manifest.id, manifest.version),
                )
            }),
        )
        .expect("test registry should form a Runtime Revision");
        let selection =
            RuntimeRevisionSelection::new(revision.clone(), 1, crate::PlatformTime::default());
        let implementations = revision
            .compatible_with(&binding)
            .expect("test binding should be compatible");
        ExecutionAssembly::new(
            session_id,
            id::<WorldId>(10),
            id::<TimelineId>(11),
            TimelineVersion::default(),
            WorldInstant::default(),
            binding,
            selection,
            implementations,
            crate::ResolutionBudget::unlimited(),
            EntropySourceId::from("semantic-context-test-entropy"),
        )
    }

    fn session_for(assembly: &ExecutionAssembly) -> PinnedReadSession {
        PinnedReadSession::new(
            assembly.session_id(),
            assembly.world_id(),
            assembly.timeline_id(),
            assembly.expected_version(),
            assembly.world_time(),
        )
    }

    fn request_for(assembly: &ExecutionAssembly) -> AgentContextRequest {
        AgentContextRequest::new(
            AgentRef::new(id::<EntityId>(12)),
            assembly.timeline_id(),
            assembly.expected_version(),
            assembly.world_time(),
            ContextBudget::default(),
        )
    }

    fn semantic_plan() -> AgentContextPlan {
        AgentContextPlan::new().with_item(AgentContextItem::semantic(
            "semantic.matches",
            ContextSource::Knowledge,
            SemanticQueryRequest::new(
                "semantic.test.index",
                SchemaRevision::new(1),
                1,
                "semantic-model-1",
                vec![1.0, 0.0],
                1,
            ),
        ))
    }

    fn block_on<F: Future>(future: F) -> F::Output {
        let mut future = Box::pin(future);
        let waker = Waker::noop();
        let mut context = std::task::Context::from_waker(waker);
        loop {
            match future.as_mut().poll(&mut context) {
                std::task::Poll::Ready(output) => return output,
                std::task::Poll::Pending => std::thread::yield_now(),
            }
        }
    }

    #[test]
    fn semantic_context_rejects_session_a_with_assembly_b() {
        let registry = registry();
        let assembly_a = assembly(&registry, id(13));
        let assembly_b = assembly(&registry, id(14));
        let session_a = session_for(&assembly_a);
        let request_a = request_for(&assembly_a);
        let mut builder =
            AgentWorldViewBuilder::new(&SemanticOnlyStore, PinnedReadPolicy::default());

        let error = block_on(builder.build(
            &session_a,
            request_a,
            &semantic_plan(),
            &registry,
            &assembly_b,
        ))
        .expect_err("an assembly from another Session must be rejected");

        assert!(matches!(
            error,
            AgentWorldViewError::PinnedContextMismatch { ref field, .. }
                if field == "session_id"
        ));
        assert!(session_a.read_set().is_empty());
    }

    #[test]
    fn semantic_context_accepts_matching_assembly_and_records_session_read() {
        let registry = registry();
        let assembly = assembly(&registry, id(15));
        let session = session_for(&assembly);
        let mut builder =
            AgentWorldViewBuilder::new(&SemanticOnlyStore, PinnedReadPolicy::default());

        let view = block_on(builder.build(
            &session,
            request_for(&assembly),
            &semantic_plan(),
            &registry,
            &assembly,
        ))
        .expect("a matching assembly and pinned Session should build");

        assert_eq!(view.context.entries.len(), 1);
        assert_eq!(view.context.usage.semantic_queries, 1);
        assert_eq!(session.read_set().len(), 1);
        assert!(matches!(
            session.read_set().entries()[0],
            ReadDependency::Semantic { ref index_id, .. }
                if index_id == &loom_capability::SemanticIndexId::from("semantic.test.index")
        ));
    }
}
