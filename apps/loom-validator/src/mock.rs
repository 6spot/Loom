//! In-memory mock Loom API for validator InMemory variants.
//!
//! This mock implements the public `loom-api` contract using only `std`,
//! `loom-api` and `uuid`. It does not import `loom-runtime` or `loom-storage`
//! and therefore satisfies the validator fence. It provides deterministic
//! behavior for replay/fork scenarios.

#![allow(clippy::all, clippy::pedantic, clippy::nursery, clippy::restriction)]
#![allow(unused_imports, dead_code)]

use std::collections::{HashMap, HashSet};
use std::str::FromStr;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use loom_api::{
    ActionRequest, ActionService, ApiError, ApiResult, CatalogService, CatalogSnapshot,
    CommittedEvent, CreateWorldFromTemplateRequest, EventId, EventQuery, EventRef, EventSeq,
    EventTypeId, ExecutionResult, FacetOwner, FacetQuery, FacetSnapshot, FacetTypeId,
    ForkTimelineRequest, HistoryService, QueryService, SchemaRevision, StateRevision,
    TimelineAncestry, TimelineId, TimelineService, TimelineSnapshot, TimelineTarget,
    TimelineVersion, WorldId, WorldInstant, WorldService,
};
use serde_json::json;
use tokio::sync::Mutex;
use uuid::Uuid;

#[derive(Debug, Clone)]
struct TimelineData {
    world_id: WorldId,
    timeline_id: TimelineId,
    version: TimelineVersion,
    world_time: WorldInstant,
    ancestry: TimelineAncestry,
    facets: HashMap<(FacetOwner, FacetTypeId), FacetSnapshot>,
    events: Vec<CommittedEvent>,
    entities: HashSet<loom_api::EntityId>,
}

#[derive(Debug, Clone)]
struct WorldData {
    world_id: WorldId,
    timelines: Vec<TimelineId>,
}

#[derive(Debug, Default)]
struct MockStateInner {
    worlds: HashMap<WorldId, WorldData>,
    timelines: HashMap<TimelineId, TimelineData>,
    next_world_counter: AtomicU64,
    next_timeline_counter: AtomicU64,
}

#[derive(Clone, Debug)]
pub struct MockApi {
    state: Arc<Mutex<MockStateInner>>,
}

impl MockApi {
    pub fn new() -> Self {
        Self {
            state: Arc::new(Mutex::new(MockStateInner {
                worlds: HashMap::new(),
                timelines: HashMap::new(),
                next_world_counter: AtomicU64::new(1),
                next_timeline_counter: AtomicU64::new(1),
            })),
        }
    }
}

impl Default for MockApi {
    fn default() -> Self {
        Self::new()
    }
}

// WorldService
impl MockApi {
    async fn create_world_inner(
        &self,
        req: CreateWorldFromTemplateRequest,
    ) -> ApiResult<TimelineSnapshot> {
        let mut state = self.state.lock().await;
        let world_id = {
            let c = state.next_world_counter.fetch_add(1, Ordering::Relaxed) as u128;
            WorldId::new(Uuid::from_u128(
                c + 0x1000_0000_0000_0000_0000_0000_00000001,
            ))
        };
        let timeline_id = {
            let c = state.next_timeline_counter.fetch_add(1, Ordering::Relaxed) as u128;
            TimelineId::new(Uuid::from_u128(
                c + 0x2000_0000_0000_0000_0000_0000_00000001,
            ))
        };
        let version = TimelineVersion::new(EventSeq::new(0), StateRevision::new(0));
        let world_time = req.template.initial_world_time;
        let target = TimelineTarget::new(world_id, timeline_id);
        let snapshot = TimelineSnapshot::new(target, version, world_time);
        let timeline_data = TimelineData {
            world_id,
            timeline_id,
            version,
            world_time,
            ancestry: TimelineAncestry::root(),
            facets: HashMap::new(),
            events: Vec::new(),
            entities: HashSet::new(),
        };
        state.timelines.insert(timeline_id, timeline_data);
        state.worlds.insert(
            world_id,
            WorldData {
                world_id,
                timelines: vec![timeline_id],
            },
        );
        Ok(snapshot)
    }

    async fn invoke_inner(&self, req: ActionRequest) -> ApiResult<ExecutionResult> {
        let mut state = self.state.lock().await;
        let target = req.target;
        let timeline_id = target.timeline_id;
        let timeline_exists = state.timelines.contains_key(&timeline_id);
        if !timeline_exists {
            return Err(ApiError::not_found("Timeline not found"));
        }
        let mut timeline = state
            .timelines
            .get(&timeline_id)
            .cloned()
            .ok_or_else(|| ApiError::not_found("Timeline not found"))?;
        if timeline.world_id != target.world_id {
            return Err(ApiError::not_found("World/Timeline mismatch"));
        }
        let invocation = req.invocation;
        let action_type = invocation.action.as_str();
        let input = invocation.input;

        let (event_type, payload, effects, entity_id, event_id, facet_snapshot) = match action_type
        {
            "neutral.counter.seed" => {
                let event_id_str = input
                    .get("event_id")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| ApiError::invalid_request("event_id must be a UUID string"))?;
                let entity_id_str = input
                    .get("entity_id")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| ApiError::invalid_request("entity_id must be a UUID string"))?;
                let value = input
                    .get("value")
                    .and_then(|v| v.as_i64())
                    .ok_or_else(|| ApiError::invalid_request("value must be an integer"))?;
                let event_id = EventId::from_str(event_id_str)
                    .map_err(|_| ApiError::invalid_request("event_id must be a UUID"))?;
                let entity_id = loom_api::EntityId::from_str(entity_id_str)
                    .map_err(|_| ApiError::invalid_request("entity_id must be a UUID"))?;
                if timeline.entities.contains(&entity_id) {
                    return Err(ApiError::conflict("Entity already exists"));
                }
                let owner = FacetOwner::entity(entity_id);
                let facet_type = FacetTypeId::from("neutral.counter.value");
                let snap = FacetSnapshot::new(
                    owner,
                    facet_type.clone(),
                    SchemaRevision::new(1),
                    json!({"value": value}),
                );
                let eff1 = loom_api::WorldEffect::CreateEntity { entity_id };
                let eff2 = loom_api::WorldEffect::PutFacet {
                    owner,
                    facet_type: facet_type.clone(),
                    schema_revision: SchemaRevision::new(1),
                    value: json!({"value": value}),
                };
                let payload = json!({"entity_id": entity_id.to_string(), "value": value});
                (
                    EventTypeId::from("neutral.counter.seeded"),
                    payload,
                    vec![eff1, eff2],
                    entity_id,
                    event_id,
                    snap,
                )
            }
            "neutral.counter.increment" => {
                let event_id_str = input
                    .get("event_id")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| ApiError::invalid_request("event_id must be a UUID string"))?;
                let entity_id_str = input
                    .get("entity_id")
                    .and_then(|v| v.as_str())
                    .ok_or_else(|| ApiError::invalid_request("entity_id must be a UUID string"))?;
                let amount = input
                    .get("amount")
                    .and_then(|v| v.as_i64())
                    .ok_or_else(|| ApiError::invalid_request("amount must be an integer"))?;
                let event_id = EventId::from_str(event_id_str)
                    .map_err(|_| ApiError::invalid_request("event_id must be a UUID"))?;
                let entity_id = loom_api::EntityId::from_str(entity_id_str)
                    .map_err(|_| ApiError::invalid_request("entity_id must be a UUID"))?;
                let owner = FacetOwner::entity(entity_id);
                let facet_type = FacetTypeId::from("neutral.counter.value");
                let current = timeline
                    .facets
                    .get(&(owner, facet_type.clone()))
                    .and_then(|snap| snap.value.get("value").and_then(|v| v.as_i64()))
                    .unwrap_or(0);
                if !timeline.entities.contains(&entity_id) {
                    return Err(ApiError::not_found("counter Facet is missing"));
                }
                let new_value = current
                    .checked_add(amount)
                    .ok_or_else(|| ApiError::invalid_request("counter value overflowed"))?;
                let snap = FacetSnapshot::new(
                    owner,
                    facet_type.clone(),
                    SchemaRevision::new(1),
                    json!({"value": new_value}),
                );
                let eff = loom_api::WorldEffect::PutFacet {
                    owner,
                    facet_type: facet_type.clone(),
                    schema_revision: SchemaRevision::new(1),
                    value: json!({"value": new_value}),
                };
                let payload = json!({
                    "entity_id": entity_id.to_string(),
                    "previous": current,
                    "amount": amount,
                    "value": new_value
                });
                (
                    EventTypeId::from("neutral.counter.incremented"),
                    payload,
                    vec![eff],
                    entity_id,
                    event_id,
                    snap,
                )
            }
            _ => {
                return Err(ApiError::not_found(format!(
                    "Unknown action type {action_type}"
                )));
            }
        };

        let next_seq = EventSeq::new(timeline.version.head_event_seq.value() + 1);
        let next_rev = StateRevision::new(timeline.version.state_revision.value() + 1);
        let new_version = TimelineVersion::new(next_seq, next_rev);
        let new_world_time = WorldInstant::new(timeline.world_time.value() + 1);
        timeline.entities.insert(entity_id);
        let owner = FacetOwner::entity(entity_id);
        let facet_type = FacetTypeId::from("neutral.counter.value");
        timeline.facets.insert((owner, facet_type), facet_snapshot);
        let committed = CommittedEvent {
            id: event_id,
            timeline_id,
            sequence: next_seq,
            event_type,
            schema_revision: SchemaRevision::new(1),
            occurred_at: new_world_time,
            participants: vec![loom_api::EventParticipant::new(entity_id, "subject")],
            relationship_refs: Vec::new(),
            causal_links: Vec::new(),
            payload,
            effects,
        };
        timeline.events.push(committed);
        timeline.version = new_version;
        timeline.world_time = new_world_time;
        state.timelines.insert(timeline_id, timeline.clone());
        Ok(ExecutionResult::Committed {
            event_ids: vec![event_id],
            timeline_version: new_version,
        })
    }

    async fn inspect_inner(&self, target: TimelineTarget) -> ApiResult<TimelineSnapshot> {
        let state = self.state.lock().await;
        let timeline = state
            .timelines
            .get(&target.timeline_id)
            .ok_or_else(|| ApiError::not_found("Timeline not found"))?;
        if timeline.world_id != target.world_id {
            return Err(ApiError::not_found("World/Timeline mismatch"));
        }
        Ok(TimelineSnapshot::with_ancestry(
            target,
            timeline.version,
            timeline.world_time,
            timeline.ancestry,
        ))
    }

    async fn fork_inner(&self, req: ForkTimelineRequest) -> ApiResult<TimelineSnapshot> {
        let mut state = self.state.lock().await;
        let source_target = req.source;
        let source_timeline = state
            .timelines
            .get(&source_target.timeline_id)
            .cloned()
            .ok_or_else(|| ApiError::not_found("Source Timeline not found"))?;
        if source_timeline.world_id != source_target.world_id {
            return Err(ApiError::not_found("Source World/Timeline mismatch"));
        }
        let fork_version = req.source_version.unwrap_or(source_timeline.version);
        if fork_version.head_event_seq.value() > source_timeline.version.head_event_seq.value() {
            return Err(ApiError::invalid_request("fork version beyond source head"));
        }
        if fork_version.state_revision.value() > source_timeline.version.state_revision.value() {
            return Err(ApiError::invalid_request(
                "fork version state revision beyond source head",
            ));
        }
        let fork_parent_event = source_timeline
            .events
            .iter()
            .find(|e| e.sequence == fork_version.head_event_seq)
            .map(|e| EventRef::new(source_timeline.timeline_id, e.id));
        let new_timeline_id = {
            let c = state.next_timeline_counter.fetch_add(1, Ordering::Relaxed) as u128;
            TimelineId::new(Uuid::from_u128(
                c + 0x2000_0000_0000_0000_0000_0000_00000001,
            ))
        };
        let world_id = source_timeline.world_id;
        let filtered_events: Vec<CommittedEvent> = source_timeline
            .events
            .iter()
            .filter(|e| e.sequence.value() <= fork_version.head_event_seq.value())
            .cloned()
            .collect();
        let mut new_facets: HashMap<(FacetOwner, FacetTypeId), FacetSnapshot> = HashMap::new();
        let mut new_entities: HashSet<loom_api::EntityId> = HashSet::new();
        for event in &filtered_events {
            for effect in &event.effects {
                match effect {
                    loom_api::WorldEffect::CreateEntity { entity_id } => {
                        new_entities.insert(*entity_id);
                    }
                    loom_api::WorldEffect::PutFacet {
                        owner,
                        facet_type,
                        schema_revision,
                        value,
                    } => {
                        let snap = FacetSnapshot::new(
                            *owner,
                            facet_type.clone(),
                            *schema_revision,
                            value.clone(),
                        );
                        new_facets.insert((*owner, facet_type.clone()), snap);
                    }
                    _ => {}
                }
            }
            for participant in &event.participants {
                new_entities.insert(participant.entity_id);
            }
        }
        let new_world_time = source_timeline.world_time;
        let new_ancestry =
            TimelineAncestry::fork(source_timeline.timeline_id, fork_version, fork_parent_event);
        let new_timeline = TimelineData {
            world_id,
            timeline_id: new_timeline_id,
            version: fork_version,
            world_time: new_world_time,
            ancestry: new_ancestry,
            facets: new_facets,
            events: filtered_events,
            entities: new_entities,
        };
        state.timelines.insert(new_timeline_id, new_timeline);
        if let Some(world) = state.worlds.get_mut(&world_id) {
            world.timelines.push(new_timeline_id);
        }
        let target = TimelineTarget::new(world_id, new_timeline_id);
        Ok(TimelineSnapshot::with_ancestry(
            target,
            fork_version,
            new_world_time,
            new_ancestry,
        ))
    }

    async fn get_facet_inner(&self, query: FacetQuery) -> ApiResult<Option<FacetSnapshot>> {
        let state = self.state.lock().await;
        let timeline = state
            .timelines
            .get(&query.target.timeline_id)
            .ok_or_else(|| ApiError::not_found("Timeline not found"))?;
        if timeline.world_id != query.target.world_id {
            return Err(ApiError::not_found("World/Timeline mismatch"));
        }
        Ok(timeline
            .facets
            .get(&(query.owner, query.facet_type.clone()))
            .cloned())
    }

    async fn list_events_inner(&self, query: EventQuery) -> ApiResult<Vec<CommittedEvent>> {
        let state = self.state.lock().await;
        let timeline = state
            .timelines
            .get(&query.target.timeline_id)
            .ok_or_else(|| ApiError::not_found("Timeline not found"))?;
        if timeline.world_id != query.target.world_id {
            return Err(ApiError::not_found("World/Timeline mismatch"));
        }
        let mut events = timeline.events.clone();
        if let Some(after) = query.after {
            events.retain(|e| e.sequence.value() > after.value());
        }
        if let Some(limit) = query.limit {
            events.truncate(limit as usize);
        }
        Ok(events)
    }

    async fn list_events_page_inner(&self, query: EventQuery) -> ApiResult<loom_api::EventPage> {
        let events = self.list_events_inner(query).await?;
        Ok(loom_api::EventPage {
            events,
            next_after: None,
        })
    }
}

// Implement traits
impl WorldService for MockApi {
    fn create_world_from_template(
        &self,
        request: CreateWorldFromTemplateRequest,
    ) -> loom_api::ApiFuture<'_, loom_api::CreateWorldFromTemplateResult> {
        let this = self.clone();
        Box::pin(async move { this.create_world_inner(request).await })
    }
}

impl ActionService for MockApi {
    fn invoke(&self, request: ActionRequest) -> loom_api::ApiFuture<'_, ExecutionResult> {
        let this = self.clone();
        Box::pin(async move { this.invoke_inner(request).await })
    }
}

impl TimelineService for MockApi {
    fn inspect_timeline(
        &self,
        target: TimelineTarget,
    ) -> loom_api::ApiFuture<'_, TimelineSnapshot> {
        let this = self.clone();
        Box::pin(async move { this.inspect_inner(target).await })
    }
    fn fork(&self, request: ForkTimelineRequest) -> loom_api::ApiFuture<'_, TimelineSnapshot> {
        let this = self.clone();
        Box::pin(async move { this.fork_inner(request).await })
    }
}

impl QueryService for MockApi {
    fn get_facet(&self, query: FacetQuery) -> loom_api::ApiFuture<'_, Option<FacetSnapshot>> {
        let this = self.clone();
        Box::pin(async move { this.get_facet_inner(query).await })
    }
}

impl HistoryService for MockApi {
    fn list_events(&self, query: EventQuery) -> loom_api::ApiFuture<'_, Vec<CommittedEvent>> {
        let this = self.clone();
        Box::pin(async move { this.list_events_inner(query).await })
    }
    fn list_events_page(&self, query: EventQuery) -> loom_api::ApiFuture<'_, loom_api::EventPage> {
        let this = self.clone();
        Box::pin(async move { this.list_events_page_inner(query).await })
    }
    fn get_event(&self, _event_ref: EventRef) -> loom_api::ApiFuture<'_, Option<CommittedEvent>> {
        Box::pin(async { Ok(None) })
    }
    fn direct_causes(&self, _event_ref: EventRef) -> loom_api::ApiFuture<'_, Vec<EventRef>> {
        Box::pin(async { Ok(Vec::new()) })
    }
    fn direct_effects(&self, _event_ref: EventRef) -> loom_api::ApiFuture<'_, Vec<EventRef>> {
        Box::pin(async { Ok(Vec::new()) })
    }
    fn causal_walk(
        &self,
        _query: loom_api::CausalQuery,
    ) -> loom_api::ApiFuture<'_, loom_api::CausalTraversal> {
        Box::pin(async {
            Ok(loom_api::CausalTraversal {
                events: Vec::new(),
                truncated: false,
            })
        })
    }
    fn entity_trajectory(
        &self,
        _query: loom_api::EntityTrajectoryQuery,
    ) -> loom_api::ApiFuture<'_, loom_api::TrajectoryPage> {
        Box::pin(async {
            Ok(loom_api::TrajectoryPage {
                events: Vec::new(),
                next_after: None,
            })
        })
    }
    fn relationship_trajectory(
        &self,
        _query: loom_api::RelationshipTrajectoryQuery,
    ) -> loom_api::ApiFuture<'_, loom_api::TrajectoryPage> {
        Box::pin(async {
            Ok(loom_api::TrajectoryPage {
                events: Vec::new(),
                next_after: None,
            })
        })
    }
}

impl CatalogService for MockApi {
    fn catalog(&self) -> ApiResult<CatalogSnapshot> {
        Ok(CatalogSnapshot::default())
    }
    fn catalog_for_world(&self, _world_id: WorldId) -> loom_api::ApiFuture<'_, CatalogSnapshot> {
        Box::pin(async { Ok(CatalogSnapshot::default()) })
    }
}

impl loom_api::SubscriptionService for MockApi {
    fn subscribe(
        &self,
        _request: loom_api::SubscriptionRequest,
    ) -> loom_api::ApiFuture<'_, loom_api::SubscriptionResult> {
        Box::pin(async {
            Err(ApiError::unavailable(
                "Subscription not implemented in mock",
            ))
        })
    }
}

impl loom_api::IngressService for MockApi {
    fn submit_ingress(
        &self,
        _request: loom_api::IngressEnvelope,
    ) -> loom_api::ApiFuture<'_, loom_api::IngressAcceptance> {
        Box::pin(async { Err(ApiError::unavailable("Ingress not implemented in mock")) })
    }
    fn ingress_status(
        &self,
        _ingress_id: loom_api::IngressId,
    ) -> loom_api::ApiFuture<'_, loom_api::IngressStatusRecord> {
        Box::pin(async { Err(ApiError::unavailable("Ingress status not implemented")) })
    }
}
