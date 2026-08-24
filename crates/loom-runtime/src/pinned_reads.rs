//! Runtime-owned, version-fenced point reads.
//!
//! The Capability view remains synchronous and storage-free.  This module is
//! the asynchronous Runtime/Storage boundary used to prepare bounded working
//! sets (or to refill them after a deterministic miss).  Every operation is
//! addressed by the exact [`ExecutionAssembly`] version and adapters must
//! verify that version in the same read-only database snapshot as the point
//! query.

use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
};

use loom_capability::SemanticIndexId;
use loom_core::{
    Entity, EntityId, EventId, EventRef, FacetOwner, FacetTypeId, Relationship, RelationshipId,
    SchemaRevision, TimelineId, TimelineVersion, WorldId, WorldInstant,
};
use serde_json::Value;

use crate::{
    CommittedEvent, ExecutionAssembly, PersistenceFuture, ReadDependency, ReadError, ReadSet,
};

/// Measurements for one Runtime point read or cache lookup.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct PinnedReadMetrics {
    rows_read: u64,
    bytes_read: u64,
    latency_micros: u64,
    cache_hits: u64,
}

impl PinnedReadMetrics {
    /// Creates measurements for one adapter query.
    #[must_use]
    pub const fn new(rows_read: u64, bytes_read: u64, latency_micros: u64) -> Self {
        Self {
            rows_read,
            bytes_read,
            latency_micros,
            cache_hits: 0,
        }
    }

    /// Returns the number of database rows observed by the read.
    #[must_use]
    pub const fn rows_read(self) -> u64 {
        self.rows_read
    }

    /// Returns the approximate bytes returned by the read.
    #[must_use]
    pub const fn bytes_read(self) -> u64 {
        self.bytes_read
    }

    /// Returns adapter-measured latency in microseconds.
    #[must_use]
    pub const fn latency_micros(self) -> u64 {
        self.latency_micros
    }

    /// Returns the number of cache hits represented by these measurements.
    #[must_use]
    pub const fn cache_hits(self) -> u64 {
        self.cache_hits
    }

    /// Combines measurements from a sequence of reads.
    pub fn add(&mut self, other: Self) {
        self.rows_read = self.rows_read.saturating_add(other.rows_read);
        self.bytes_read = self.bytes_read.saturating_add(other.bytes_read);
        self.latency_micros = self.latency_micros.saturating_add(other.latency_micros);
        self.cache_hits = self.cache_hits.saturating_add(other.cache_hits);
    }

    fn cache_hit() -> Self {
        Self {
            cache_hits: 1,
            ..Self::default()
        }
    }
}

/// A point-read value together with Runtime instrumentation.
#[derive(Clone, Debug, PartialEq)]
pub struct PinnedRead<T> {
    value: T,
    metrics: PinnedReadMetrics,
}

/// Runtime-owned Facet read model crossing the persistence boundary. It is
/// independent of the Capability crate so Storage only implements Runtime's
/// port and cannot hand a Capability contract object around.
#[derive(Clone, Debug, PartialEq)]
pub struct PinnedFacet {
    /// Schema revision of the complete Facet value.
    pub schema_revision: loom_core::SchemaRevision,
    /// Complete immutable Facet value.
    pub value: Value,
}

impl PinnedFacet {
    /// Creates one Runtime Facet read model.
    #[must_use]
    pub const fn new(schema_revision: loom_core::SchemaRevision, value: Value) -> Self {
        Self {
            schema_revision,
            value,
        }
    }
}

impl From<PinnedFacet> for loom_capability::FacetValue {
    fn from(value: PinnedFacet) -> Self {
        Self::new(value.schema_revision, value.value)
    }
}

impl<T> PinnedRead<T> {
    /// Creates an instrumented point-read result.
    #[must_use]
    pub const fn new(value: T, metrics: PinnedReadMetrics) -> Self {
        Self { value, metrics }
    }

    /// Borrows the read value.
    #[must_use]
    pub const fn value(&self) -> &T {
        &self.value
    }

    /// Consumes the result and returns its read value.
    #[must_use]
    pub fn into_value(self) -> T {
        self.value
    }

    /// Returns the Runtime measurements for this read.
    #[must_use]
    pub const fn metrics(&self) -> PinnedReadMetrics {
        self.metrics
    }
}

/// Immutable read identity shared by every point read in one Execution
/// Session.  It is deliberately not a transaction or a storage handle.
#[derive(Clone, Debug)]
pub struct PinnedReadSession {
    session_id: loom_core::ExecutionSessionId,
    world_id: WorldId,
    timeline_id: TimelineId,
    version: TimelineVersion,
    world_time: WorldInstant,
    reads: Arc<Mutex<ReadSet>>,
}

impl PinnedReadSession {
    /// Creates a Runtime read identity after an adapter has fenced the
    /// requested Timeline version.
    #[must_use]
    pub fn new(
        session_id: loom_core::ExecutionSessionId,
        world_id: WorldId,
        timeline_id: TimelineId,
        version: TimelineVersion,
        world_time: WorldInstant,
    ) -> Self {
        Self {
            session_id,
            world_id,
            timeline_id,
            version,
            world_time,
            reads: Arc::new(Mutex::new(ReadSet::default())),
        }
    }

    /// Returns the owning Execution Session identity.
    #[must_use]
    pub const fn session_id(&self) -> loom_core::ExecutionSessionId {
        self.session_id
    }

    /// Returns the pinned World identity.
    #[must_use]
    pub const fn world_id(&self) -> WorldId {
        self.world_id
    }

    /// Returns the pinned Timeline identity.
    #[must_use]
    pub const fn timeline_id(&self) -> TimelineId {
        self.timeline_id
    }

    /// Returns the exact `TimelineVersion` required by every read.
    #[must_use]
    pub const fn version(&self) -> TimelineVersion {
        self.version
    }

    /// Returns the pinned semantic World Time.
    #[must_use]
    pub const fn world_time(&self) -> WorldInstant {
        self.world_time
    }

    /// Returns the Runtime-owned observed dependencies for this read session.
    #[must_use]
    pub fn read_set(&self) -> ReadSet {
        self.reads
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    /// Records an actual Entity lookup, including a negative result.
    pub fn record_entity(&self, entity_id: EntityId, present: bool) {
        self.record(ReadDependency::Entity { entity_id, present });
    }

    /// Records an actual Relationship lookup, including an inactive/missing result.
    pub fn record_relationship(&self, relationship_id: RelationshipId, present: bool) {
        self.record(ReadDependency::Relationship {
            relationship_id,
            present,
        });
    }

    /// Records an actual Facet lookup, including a negative result.
    pub fn record_facet(
        &self,
        owner: FacetOwner,
        facet_type: FacetTypeId,
        schema_revision: Option<loom_core::SchemaRevision>,
    ) {
        self.record(ReadDependency::Facet {
            owner,
            facet_type,
            schema_revision,
        });
    }

    /// Records an actual Event lookup, including a negative result.
    pub fn record_event(&self, event_id: EventId, present: bool) {
        self.record(ReadDependency::Event { event_id, present });
    }

    /// Records one Runtime-mediated semantic projection read.
    #[expect(
        clippy::too_many_arguments,
        reason = "the provenance fields mirror one semantic ReadDependency"
    )]
    pub fn record_semantic(
        &self,
        index_id: SemanticIndexId,
        query_fingerprint: String,
        query_spec: String,
        source_schema_revision: SchemaRevision,
        projection_revision: u64,
        model_revision: String,
        source_refs: Vec<EventRef>,
    ) {
        self.record(ReadDependency::Semantic {
            index_id,
            query_fingerprint,
            query_spec,
            source_schema_revision,
            projection_revision,
            model_revision,
            source_refs,
        });
    }

    fn record(&self, dependency: ReadDependency) {
        self.reads
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .record(dependency);
    }
}

/// Deterministic policy for bounded cache/refill handling.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct PinnedReadPolicy {
    max_restarts: u32,
    cache_capacity: usize,
}

impl PinnedReadPolicy {
    /// Creates a policy.  A cache capacity of zero disables caching.
    #[must_use]
    pub const fn new(max_restarts: u32, cache_capacity: usize) -> Self {
        Self {
            max_restarts,
            cache_capacity,
        }
    }

    /// Returns the bounded number of re-resolution attempts permitted after a
    /// version-fenced read observes a changed Timeline.
    #[must_use]
    pub const fn max_restarts(self) -> u32 {
        self.max_restarts
    }

    /// Returns the maximum number of exact-version cache entries.
    #[must_use]
    pub const fn cache_capacity(self) -> usize {
        self.cache_capacity
    }

    /// Reports whether this attempt may restart after a version mismatch.
    #[must_use]
    pub const fn should_restart(self, attempt: u32, error: &ReadError) -> bool {
        attempt < self.max_restarts && matches!(error, ReadError::PinnedVersionMismatch { .. })
    }
}

impl Default for PinnedReadPolicy {
    fn default() -> Self {
        Self::new(1, 256)
    }
}

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
enum CacheKey {
    Entity {
        timeline_id: TimelineId,
        version: TimelineVersion,
        entity_id: EntityId,
    },
    Relationship {
        timeline_id: TimelineId,
        version: TimelineVersion,
        relationship_id: RelationshipId,
    },
    Facet {
        timeline_id: TimelineId,
        version: TimelineVersion,
        owner: FacetOwner,
        facet_type: FacetTypeId,
    },
    Event {
        timeline_id: TimelineId,
        version: TimelineVersion,
        event_id: EventId,
    },
}

#[derive(Clone, Debug, PartialEq)]
enum CacheValue {
    Entity(Option<Entity>),
    Relationship(Option<Relationship>),
    Facet(Option<PinnedFacet>),
    Event(Option<CommittedEvent>),
}

/// Runtime-owned bounded cache.  Entries are keyed by the full Timeline
/// version, so a commit can never make an older result appear current.  When
/// full, new entries are not admitted; this deterministic policy avoids an
/// eviction clock or a hidden ordering source in semantic execution.
#[derive(Clone, Debug)]
pub struct PinnedReadCache {
    capacity: usize,
    values: HashMap<CacheKey, CacheValue>,
}

impl PinnedReadCache {
    /// Creates an empty exact-version cache.
    #[must_use]
    pub fn new(capacity: usize) -> Self {
        Self {
            capacity,
            values: HashMap::new(),
        }
    }

    /// Returns the number of entries currently retained.
    #[must_use]
    pub fn len(&self) -> usize {
        self.values.len()
    }

    /// Reports whether no entries are retained.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.values.is_empty()
    }

    /// Removes all entries for one Timeline after a fenced mismatch/restart.
    pub fn invalidate_timeline(&mut self, timeline_id: TimelineId) {
        self.values.retain(|key, _| match key {
            CacheKey::Entity {
                timeline_id: key_timeline,
                ..
            }
            | CacheKey::Relationship {
                timeline_id: key_timeline,
                ..
            }
            | CacheKey::Facet {
                timeline_id: key_timeline,
                ..
            }
            | CacheKey::Event {
                timeline_id: key_timeline,
                ..
            } => *key_timeline != timeline_id,
        });
    }

    fn get(&self, key: &CacheKey) -> Option<CacheValue> {
        self.values.get(key).cloned()
    }

    fn insert(&mut self, key: CacheKey, value: CacheValue) {
        if self.capacity == 0
            || (!self.values.contains_key(&key) && self.values.len() >= self.capacity)
        {
            return;
        }
        self.values.insert(key, value);
    }
}

/// Runtime convenience boundary combining the async port, exact-version
/// cache, restart policy and read instrumentation.  It is never passed to a
/// Capability; Capability code continues to receive only its synchronous
/// storage-free `BaseWorldView` trait object.
pub struct PinnedReadBoundary<'store, S> {
    store: &'store S,
    policy: PinnedReadPolicy,
    cache: PinnedReadCache,
    metrics: PinnedReadMetrics,
}

impl<'store, S> PinnedReadBoundary<'store, S>
where
    S: PinnedWorldReadStore,
{
    /// Creates a Runtime-owned boundary over one injected persistence port.
    #[must_use]
    pub fn new(store: &'store S, policy: PinnedReadPolicy) -> Self {
        Self {
            store,
            policy,
            cache: PinnedReadCache::new(policy.cache_capacity()),
            metrics: PinnedReadMetrics::default(),
        }
    }

    /// Opens a fenced read identity for one Execution Session.
    ///
    /// # Errors
    ///
    /// Returns the persistence port's error when the assembly cannot be
    /// opened at its requested world and timeline version.
    pub async fn open(&self, assembly: &ExecutionAssembly) -> Result<PinnedReadSession, ReadError> {
        self.store.open_pinned_read(assembly).await
    }

    /// Returns aggregate point-read instrumentation collected by this boundary.
    #[must_use]
    pub const fn metrics(&self) -> PinnedReadMetrics {
        self.metrics
    }

    /// Returns the configured restart/cache policy.
    #[must_use]
    pub const fn policy(&self) -> PinnedReadPolicy {
        self.policy
    }

    pub(crate) const fn store(&self) -> &'store S {
        self.store
    }

    /// Reads one Entity, using only an exact-version cache hit or the fenced port.
    ///
    /// # Errors
    ///
    /// Returns the persistence port's error, including a pinned-version
    /// mismatch that requires the caller to apply the configured restart policy.
    pub async fn entity(
        &mut self,
        session: &PinnedReadSession,
        entity_id: EntityId,
    ) -> Result<PinnedRead<Option<Entity>>, ReadError> {
        let key = CacheKey::Entity {
            timeline_id: session.timeline_id(),
            version: session.version(),
            entity_id,
        };
        if let Some(CacheValue::Entity(value)) = self.cache.get(&key) {
            session.record_entity(entity_id, value.is_some());
            let read = PinnedRead::new(value, PinnedReadMetrics::cache_hit());
            self.metrics.add(read.metrics());
            return Ok(read);
        }
        let read = match self.store.read_entity(session, entity_id).await {
            Ok(read) => read,
            Err(error) => return self.fenced_error(session, error),
        };
        session.record_entity(entity_id, read.value().is_some());
        self.cache
            .insert(key, CacheValue::Entity(read.value().clone()));
        self.metrics.add(read.metrics());
        Ok(read)
    }

    /// Reads one active Relationship and its fixed participant structure.
    ///
    /// # Errors
    ///
    /// Returns the persistence port's error, including a pinned-version
    /// mismatch that requires the caller to apply the configured restart policy.
    pub async fn relationship(
        &mut self,
        session: &PinnedReadSession,
        relationship_id: RelationshipId,
    ) -> Result<PinnedRead<Option<Relationship>>, ReadError> {
        let key = CacheKey::Relationship {
            timeline_id: session.timeline_id(),
            version: session.version(),
            relationship_id,
        };
        if let Some(CacheValue::Relationship(value)) = self.cache.get(&key) {
            session.record_relationship(relationship_id, value.is_some());
            let read = PinnedRead::new(value, PinnedReadMetrics::cache_hit());
            self.metrics.add(read.metrics());
            return Ok(read);
        }
        let read = match self.store.read_relationship(session, relationship_id).await {
            Ok(read) => read,
            Err(error) => return self.fenced_error(session, error),
        };
        session.record_relationship(relationship_id, read.value().is_some());
        self.cache
            .insert(key, CacheValue::Relationship(read.value().clone()));
        self.metrics.add(read.metrics());
        Ok(read)
    }

    /// Reads one Entity- or Relationship-owned Facet.
    ///
    /// # Errors
    ///
    /// Returns the persistence port's error, including a pinned-version
    /// mismatch that requires the caller to apply the configured restart policy.
    pub async fn facet(
        &mut self,
        session: &PinnedReadSession,
        owner: FacetOwner,
        facet_type: &FacetTypeId,
    ) -> Result<PinnedRead<Option<PinnedFacet>>, ReadError> {
        let key = CacheKey::Facet {
            timeline_id: session.timeline_id(),
            version: session.version(),
            owner,
            facet_type: facet_type.clone(),
        };
        if let Some(CacheValue::Facet(value)) = self.cache.get(&key) {
            session.record_facet(
                owner,
                facet_type.clone(),
                value.as_ref().map(|facet| facet.schema_revision),
            );
            let read = PinnedRead::new(value, PinnedReadMetrics::cache_hit());
            self.metrics.add(read.metrics());
            return Ok(read);
        }
        let read = match self.store.read_facet(session, owner, facet_type).await {
            Ok(read) => read,
            Err(error) => return self.fenced_error(session, error),
        };
        session.record_facet(
            owner,
            facet_type.clone(),
            read.value().as_ref().map(|facet| facet.schema_revision),
        );
        self.cache
            .insert(key, CacheValue::Facet(read.value().clone()));
        self.metrics.add(read.metrics());
        Ok(read)
    }

    /// Reads one visible Event through the pinned Timeline ancestry boundary.
    ///
    /// # Errors
    ///
    /// Returns the persistence port's error, including a pinned-version
    /// mismatch that requires the caller to apply the configured restart policy.
    pub async fn event(
        &mut self,
        session: &PinnedReadSession,
        event_id: EventId,
    ) -> Result<PinnedRead<Option<CommittedEvent>>, ReadError> {
        let key = CacheKey::Event {
            timeline_id: session.timeline_id(),
            version: session.version(),
            event_id,
        };
        if let Some(CacheValue::Event(value)) = self.cache.get(&key) {
            session.record_event(event_id, value.is_some());
            let read = PinnedRead::new(value, PinnedReadMetrics::cache_hit());
            self.metrics.add(read.metrics());
            return Ok(read);
        }
        let read = match self.store.read_event(session, event_id).await {
            Ok(read) => read,
            Err(error) => return self.fenced_error(session, error),
        };
        session.record_event(event_id, read.value().is_some());
        self.cache
            .insert(key, CacheValue::Event(read.value().clone()));
        self.metrics.add(read.metrics());
        Ok(read)
    }

    fn fenced_error<T>(
        &mut self,
        session: &PinnedReadSession,
        error: ReadError,
    ) -> Result<PinnedRead<T>, ReadError> {
        if matches!(error, ReadError::PinnedVersionMismatch { .. }) {
            self.cache.invalidate_timeline(session.timeline_id());
        }
        Err(error)
    }
}

/// Runtime-owned point-read port implemented by concrete Storage adapters.
pub trait PinnedWorldReadStore {
    /// Opens one Session-addressed read identity after checking the exact
    /// expected `TimelineVersion` in a read-only consistent database snapshot.
    fn open_pinned_read<'a>(
        &'a self,
        assembly: &'a ExecutionAssembly,
    ) -> PersistenceFuture<'a, Result<PinnedReadSession, ReadError>>;

    /// Reads one Entity without scanning the World.
    fn read_entity<'a>(
        &'a self,
        session: &'a PinnedReadSession,
        entity_id: EntityId,
    ) -> PersistenceFuture<'a, Result<PinnedRead<Option<Entity>>, ReadError>>;

    /// Reads one active Relationship and its participants without scanning
    /// unrelated Relationships.
    fn read_relationship<'a>(
        &'a self,
        session: &'a PinnedReadSession,
        relationship_id: RelationshipId,
    ) -> PersistenceFuture<'a, Result<PinnedRead<Option<Relationship>>, ReadError>>;

    /// Reads one Facet value for one structural owner and semantic key.
    fn read_facet<'a>(
        &'a self,
        session: &'a PinnedReadSession,
        owner: FacetOwner,
        facet_type: &'a FacetTypeId,
    ) -> PersistenceFuture<'a, Result<PinnedRead<Option<PinnedFacet>>, ReadError>>;

    /// Reads one visible Event and its associations through Timeline ancestry.
    fn read_event<'a>(
        &'a self,
        session: &'a PinnedReadSession,
        event_id: EventId,
    ) -> PersistenceFuture<'a, Result<PinnedRead<Option<CommittedEvent>>, ReadError>>;
}

impl<T> PinnedWorldReadStore for &T
where
    T: PinnedWorldReadStore + ?Sized,
{
    fn open_pinned_read<'a>(
        &'a self,
        assembly: &'a ExecutionAssembly,
    ) -> PersistenceFuture<'a, Result<PinnedReadSession, ReadError>> {
        (**self).open_pinned_read(assembly)
    }

    fn read_entity<'a>(
        &'a self,
        session: &'a PinnedReadSession,
        entity_id: EntityId,
    ) -> PersistenceFuture<'a, Result<PinnedRead<Option<Entity>>, ReadError>> {
        (**self).read_entity(session, entity_id)
    }

    fn read_relationship<'a>(
        &'a self,
        session: &'a PinnedReadSession,
        relationship_id: RelationshipId,
    ) -> PersistenceFuture<'a, Result<PinnedRead<Option<Relationship>>, ReadError>> {
        (**self).read_relationship(session, relationship_id)
    }

    fn read_facet<'a>(
        &'a self,
        session: &'a PinnedReadSession,
        owner: FacetOwner,
        facet_type: &'a FacetTypeId,
    ) -> PersistenceFuture<'a, Result<PinnedRead<Option<PinnedFacet>>, ReadError>> {
        (**self).read_facet(session, owner, facet_type)
    }

    fn read_event<'a>(
        &'a self,
        session: &'a PinnedReadSession,
        event_id: EventId,
    ) -> PersistenceFuture<'a, Result<PinnedRead<Option<CommittedEvent>>, ReadError>> {
        (**self).read_event(session, event_id)
    }
}

#[cfg(test)]
mod tests {
    use loom_core::{EventSeq, StateRevision};

    use super::*;

    #[test]
    fn policy_allows_only_bounded_version_restarts() {
        let policy = PinnedReadPolicy::new(2, 4);
        let timeline_id: TimelineId = "00000000-0000-0000-0000-000000000901"
            .parse()
            .expect("Timeline ID");
        let error = ReadError::PinnedVersionMismatch {
            timeline_id,
            expected: TimelineVersion::default(),
            actual: TimelineVersion::new(EventSeq::new(1), StateRevision::new(1)),
        };
        assert!(policy.should_restart(0, &error));
        assert!(policy.should_restart(1, &error));
        assert!(!policy.should_restart(2, &error));
        assert!(!policy.should_restart(
            0,
            &ReadError::StorageUnavailable {
                message: "read failed".to_owned(),
            }
        ));
    }

    #[test]
    fn read_session_records_actual_positive_and_negative_dependencies() {
        let session_id: loom_core::ExecutionSessionId = "00000000-0000-0000-0000-000000000902"
            .parse()
            .expect("Session ID");
        let world_id: WorldId = "00000000-0000-0000-0000-000000000903"
            .parse()
            .expect("World ID");
        let timeline_id: TimelineId = "00000000-0000-0000-0000-000000000904"
            .parse()
            .expect("Timeline ID");
        let entity_id: EntityId = "00000000-0000-0000-0000-000000000905"
            .parse()
            .expect("Entity ID");
        let session = PinnedReadSession::new(
            session_id,
            world_id,
            timeline_id,
            TimelineVersion::default(),
            WorldInstant::default(),
        );
        session.record_entity(entity_id, false);
        session.record_entity(entity_id, true);
        assert_eq!(session.read_set().len(), 2);
        assert!(matches!(
            session.read_set().entries()[0],
            ReadDependency::Entity { present: false, .. }
        ));
        assert!(matches!(
            session.read_set().entries()[1],
            ReadDependency::Entity { present: true, .. }
        ));
    }

    #[test]
    fn cache_capacity_and_timeline_invalidation_are_deterministic() {
        let mut cache = PinnedReadCache::new(1);
        let timeline: TimelineId = "00000000-0000-0000-0000-000000000906"
            .parse()
            .expect("Timeline ID");
        let entity_id: EntityId = "00000000-0000-0000-0000-000000000907"
            .parse()
            .expect("Entity ID");
        let event_id: EventId = "00000000-0000-0000-0000-000000000908"
            .parse()
            .expect("Event ID");
        let version = TimelineVersion::default();
        let key = CacheKey::Entity {
            timeline_id: timeline,
            version,
            entity_id,
        };
        cache.insert(key.clone(), CacheValue::Entity(None));
        cache.insert(
            CacheKey::Event {
                timeline_id: timeline,
                version,
                event_id,
            },
            CacheValue::Event(None),
        );
        assert_eq!(cache.len(), 1);
        cache.invalidate_timeline(timeline);
        assert!(cache.is_empty());
    }
}
