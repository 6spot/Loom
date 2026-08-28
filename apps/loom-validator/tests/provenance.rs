//! T16 public-consumer provenance integration tests.

mod common;

use std::{
    collections::HashSet,
    env,
    path::Path,
    process::Command,
    str::FromStr,
    sync::{Arc, Mutex as StdMutex, OnceLock},
};

use loom_api::{
    ActionTypeId, AdminService, EntityId, EventId, EventTypeId, FacetOwner, FacetTypeId,
    SchemaRevision, WorldEffect,
};
use loom_boundary::{BoundaryConfig, RequireAdminAuthorization, router_with_admin};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityManifest, CapabilityRegistrar,
    CapabilityRegistry, EntropyRequest, EntropySample, EventDefinition, FacetDefinition,
    RegistrationError, ResolutionContext, ResolverError,
};
use loom_client::LoomClient;
use loom_neutral::registry as neutral_registry;
use loom_protocol::{ActionInvocation, ProposedEvent, Resolution, ResolveOutcome};
use loom_runtime::{
    EntropySource, EntropySourceError, EntropySourceId, PlatformTime, Runtime,
    RuntimeRevisionCapability, RuntimeRevisionDescriptor, RuntimeRevisionId, RuntimeRevisionStore,
};
use loom_storage::{InMemoryStore, PgStorage};
use serde_json::{Value, json};
use tokio::sync::Mutex;

use loom_validator::{BackendContext, BackendKind, ScenarioResult, provenance, validator_registry};

const DEFAULT_POSTGRES_CONTROL_URL: &str = "postgresql://loom:loom@127.0.0.1:15432/loom_control";
const PROVENANCE_CAPABILITY: &str = "validator.t16.provenance";
const PROVENANCE_FACET: &str = "validator.t16.provenance.value";
const PROVENANCE_SEED: &str = "validator.t16.provenance.seed";
const PROVENANCE_ROOT: &str = "validator.t16.provenance.root";
const PROVENANCE_CHILD: &str = "validator.t16.provenance.child";
const PROVENANCE_SEED_EVENT: &str = "validator.t16.provenance.seeded";
const PROVENANCE_ROOT_EVENT: &str = "validator.t16.provenance.committed";
const PROVENANCE_R1_ID: &str = "validator-t16-cv033-r1";
const PROVENANCE_R2_ID: &str = "validator-t16-cv033-r2";

static POSTGRES_REVISION_STATE_GUARD: OnceLock<StdMutex<()>> = OnceLock::new();

fn postgres_revision_state_guard() -> std::sync::MutexGuard<'static, ()> {
    POSTGRES_REVISION_STATE_GUARD
        .get_or_init(|| StdMutex::new(()))
        .lock()
        .expect("T16 PostgreSQL revision-state guard should not be poisoned")
}

#[test]
fn provenance_suite_scaffold_is_non_registering_and_disjoint() {
    assert_eq!(provenance::SUITE, "provenance");
    assert_eq!(provenance::CV_RANGE, "CV-031..CV-033");
    assert_eq!(provenance::CAPABILITY_AREA, "provenance");
    assert_eq!(provenance::suite_name(), "provenance");
    assert!(provenance::owns_cv("CV-031"));
    assert!(provenance::owns_cv("CV-033"));
    assert!(!provenance::owns_cv("CV-030"));
    assert!(!provenance::owns_cv("CV-034"));

    let registry = validator_registry();
    assert_eq!(registry.len(), 32);
    assert!(registry.get("CV-031").is_some());
    assert!(registry.get("CV-040").is_some());
}

#[test]
fn provenance_descriptors_are_three_and_deterministic() {
    let first = provenance::descriptors();
    assert_eq!(first, provenance::descriptors());
    assert_eq!(first.len(), 3);
    assert_eq!(
        first
            .iter()
            .map(loom_validator::ScenarioDescriptor::id_str)
            .collect::<Vec<_>>(),
        vec!["CV-031", "CV-032", "CV-033"]
    );
    for descriptor in &first {
        assert_eq!(
            descriptor.supported_backends(),
            &[BackendKind::InMemory, BackendKind::PostgreSQL]
        );
    }
}

fn descriptor(id: &str) -> loom_validator::ScenarioDescriptor {
    provenance::descriptors()
        .into_iter()
        .find(|candidate| candidate.id_str() == id)
        .unwrap_or_else(|| panic!("missing descriptor {id}"))
}

fn context(
    client: LoomClient,
    backend: BackendKind,
    scope: &str,
    restart: Arc<dyn Fn() -> Result<LoomClient, String> + Send + Sync>,
) -> BackendContext {
    BackendContext::new(client)
        .with_backend_kind(backend)
        .with_scope(scope)
        .with_restart_strategy(restart)
        .with_controlled_boundary_restart()
}

fn assert_pass(result: &ScenarioResult, id: &str) {
    assert!(
        result.outcome().is_pass(),
        "{id} should pass through public surface: {result:?}"
    );
    assert!(
        result
            .finding()
            .evidence()
            .iter()
            .any(|evidence| evidence.as_str()
                == "public-surface:loom-client::AdminService::session_for_event")
    );
}

fn public_session_for_event(
    client: &LoomClient,
    event_ref: loom_api::EventRef,
) -> Result<loom_api::ExecutionSessionId, String> {
    common::leaked_runtime()
        .block_on(async { client.session_for_event(event_ref).await })
        .map_err(|error| format!("post-restart Event-to-Session lookup failed: {error:?}"))?
        .session_id
        .ok_or_else(|| format!("post-restart Event {event_ref:?} has no producing Session"))
}

fn public_sessions(client: &LoomClient) -> Result<Vec<loom_api::AdminExecutionSession>, String> {
    common::leaked_runtime()
        .block_on(async { client.list_execution_sessions().await })
        .map_err(|error| format!("post-restart Session list failed: {error:?}"))
}

fn public_session(
    client: &LoomClient,
    session_id: loom_api::ExecutionSessionId,
) -> Result<loom_api::AdminExecutionSession, String> {
    common::leaked_runtime()
        .block_on(async {
            client
                .get_execution_session(loom_api::AdminExecutionSessionRequest { session_id })
                .await
        })
        .map_err(|error| format!("post-restart Session read failed: {error:?}"))
}

fn assert_restarted_event_session_links(
    scenario_id: &str,
    client: &LoomClient,
    expected: &[loom_api::AdminExecutionSession],
) -> Result<(), String> {
    if scenario_id == "CV-031" {
        let session = expected.first().ok_or_else(|| {
            "CV-031 did not expose an Event-linked Session before restart".to_owned()
        })?;
        if session.event_refs.len() != 1 {
            return Err(format!(
                "CV-031 expected one E1 ref, got {:?}",
                session.event_refs
            ));
        }
        let event_ref = session.event_refs[0];
        let post_session = public_session(client, session.id)?;
        if session.runtime_revision_id != "validator-t16-r1"
            || public_session_for_event(client, event_ref)? != session.id
            || post_session.event_refs != vec![event_ref]
            || post_session.runtime_revision_id != "validator-t16-r1"
        {
            return Err(format!(
                "CV-031 post-restart E1/S1 projection mismatch: {post_session:?}"
            ));
        }
        return Ok(());
    }
    if scenario_id == "CV-032" {
        let s1 = expected
            .iter()
            .find(|session| session.runtime_revision_id == "validator-t16-r1")
            .ok_or_else(|| "CV-032 did not expose R1 Session before restart".to_owned())?;
        let s2 = expected
            .iter()
            .find(|session| session.runtime_revision_id == "validator-t16-r2")
            .ok_or_else(|| "CV-032 did not expose R2 Session before restart".to_owned())?;
        if s1.event_refs.len() != 1 || s2.event_refs.len() != 1 {
            return Err(format!(
                "CV-032 expected one E1 and one E2 ref, got S1={:?} S2={:?}",
                s1.event_refs, s2.event_refs
            ));
        }
        let e1_ref = s1.event_refs[0];
        let e2_ref = s2.event_refs[0];
        let s1_post = public_session(client, s1.id)?;
        let s2_post = public_session(client, s2.id)?;
        if public_session_for_event(client, e1_ref)? != s1.id
            || public_session_for_event(client, e2_ref)? != s2.id
            || s1_post.event_refs != vec![e1_ref]
            || s2_post.event_refs != vec![e2_ref]
            || s1_post.runtime_revision_id != "validator-t16-r1"
            || s2_post.runtime_revision_id != "validator-t16-r2"
        {
            return Err(format!(
                "CV-032 post-restart E1/E2 Session projection mismatch: S1={s1_post:?} S2={s2_post:?}"
            ));
        }
        return Ok(());
    }
    for session in expected {
        for event_ref in session.event_refs.iter().copied() {
            if public_session_for_event(client, event_ref)? != session.id {
                return Err(format!(
                    "post-restart Event {event_ref:?} no longer resolves to Session {:?}",
                    session.id
                ));
            }
        }
    }
    Ok(())
}

fn revision(id: &str, build: &str, registry: &CapabilityRegistry) -> RuntimeRevisionDescriptor {
    RuntimeRevisionDescriptor::new(
        RuntimeRevisionId::from(id),
        PlatformTime::default(),
        build,
        registry.loom_version().clone(),
        registry.capabilities().map(|manifest| {
            RuntimeRevisionCapability::from_manifest(
                manifest,
                format!("{build}:{}@{}", manifest.id, manifest.version),
            )
        }),
    )
    .expect("T16 test Runtime Revision should be valid")
}

fn confirm_in_memory_revisions_with(
    store: &InMemoryStore,
    registry: &CapabilityRegistry,
    provenance: bool,
) -> Result<(), String> {
    let (r1_id, r2_id) = if provenance {
        (PROVENANCE_R1_ID, PROVENANCE_R2_ID)
    } else {
        ("validator-t16-r1", "validator-t16-r2")
    };
    let r1 = revision(r1_id, &format!("{r1_id}-build"), registry);
    let r2 = revision(r2_id, &format!("{r2_id}-build"), registry);
    store
        .confirm_revision(r1)
        .map_err(|error| format!("confirm R1 failed: {error:?}"))?;
    store
        .confirm_revision(r2)
        .map_err(|error| format!("confirm R2 failed: {error:?}"))?;
    let active = store
        .read_active_revision()
        .map_err(|error| format!("read active revision failed: {error:?}"))?;
    if active
        .as_ref()
        .is_none_or(|value| value.revision().id() != &RuntimeRevisionId::from(r1_id))
    {
        store
            .activate_revision(
                RuntimeRevisionId::from(r1_id),
                active
                    .as_ref()
                    .map(loom_runtime::RuntimeRevisionSelection::generation),
                PlatformTime::default(),
            )
            .map_err(|error| format!("activate R1 failed: {error:?}"))?;
    }
    Ok(())
}

struct ProvenanceCapability {
    manifest: CapabilityManifest,
}

impl Capability for ProvenanceCapability {
    fn manifest(&self) -> &CapabilityManifest {
        &self.manifest
    }

    fn register(&self, registrar: &mut CapabilityRegistrar) -> Result<(), RegistrationError> {
        registrar.register_facet(FacetDefinition::new(
            FacetTypeId::from(PROVENANCE_FACET),
            SchemaRevision::new(1),
            json!({
                "type": "object",
                "required": ["value"],
                "properties": {"value": {"type": "integer"}}
            }),
        ))?;
        registrar.register_event(
            EventDefinition::new(
                EventTypeId::from(PROVENANCE_SEED_EVENT),
                SchemaRevision::new(1),
            )
            .with_payload_schema(json!({"type": "object"})),
        )?;
        registrar.register_event(
            EventDefinition::new(
                EventTypeId::from(PROVENANCE_ROOT_EVENT),
                SchemaRevision::new(1),
            )
            .with_payload_schema(json!({"type": "object"})),
        )?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(PROVENANCE_SEED), SchemaRevision::new(1))
                .with_input_schema(json!({
                    "type": "object",
                    "required": ["event_id", "entity_id"],
                    "properties": {
                        "event_id": {"type": "string"},
                        "entity_id": {"type": "string"}
                    }
                })),
            ProvenanceSeedResolver,
        )?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(PROVENANCE_ROOT), SchemaRevision::new(1))
                .with_input_schema(json!({
                    "type": "object",
                    "required": ["event_id", "entity_id"],
                    "properties": {
                        "event_id": {"type": "string"},
                        "entity_id": {"type": "string"}
                    }
                })),
            ProvenanceRootResolver,
        )?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(PROVENANCE_CHILD), SchemaRevision::new(1)),
            ProvenanceChildResolver,
        )
    }
}

fn parse_id<T>(input: &Value, key: &str) -> Result<T, ResolverError>
where
    T: FromStr,
    T::Err: std::fmt::Display,
{
    input
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| ResolverError::new(format!("{key} must be a string")))?
        .parse()
        .map_err(|error| ResolverError::new(format!("invalid {key}: {error}")))
}

struct ProvenanceSeedResolver;

impl ActionResolver for ProvenanceSeedResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = parse_id::<EventId>(input, "event_id")?;
        let entity_id = parse_id::<EntityId>(input, "entity_id")?;
        let event = ProposedEvent::new(
            event_id,
            EventTypeId::from(PROVENANCE_SEED_EVENT),
            SchemaRevision::new(1),
            json!({"entity_id": entity_id.to_string()}),
        )
        .with_effect(WorldEffect::CreateEntity { entity_id })
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(entity_id),
            facet_type: FacetTypeId::from(PROVENANCE_FACET),
            schema_revision: SchemaRevision::new(1),
            value: json!({"value": 11}),
        });
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![event],
            Vec::new(),
        )))
    }
}

struct ProvenanceRootResolver;

impl ActionResolver for ProvenanceRootResolver {
    fn resolve(
        &self,
        context: &dyn ResolutionContext,
        input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        let event_id = parse_id::<EventId>(input, "event_id")?;
        let entity_id = parse_id::<EntityId>(input, "entity_id")?;
        let facet = context
            .base_world()
            .get_facet(
                FacetOwner::entity(entity_id),
                &FacetTypeId::from(PROVENANCE_FACET),
            )?
            .ok_or_else(|| ResolverError::new("provenance Facet was not seeded"))?;
        if facet.value.get("value").and_then(Value::as_i64) != Some(11) {
            return Err(ResolverError::new("provenance Facet has unexpected value"));
        }
        let child = context.subresolve(&ActionInvocation::new(
            ActionTypeId::from(PROVENANCE_CHILD),
            json!({}),
        ))?;
        if !matches!(child, ResolveOutcome::Resolved(ref resolution) if resolution.is_empty()) {
            return Err(ResolverError::new("provenance child did not resolve empty"));
        }
        let entropy = context.request_entropy(&EntropyRequest::new(4))?;
        if entropy.as_bytes() != [0xA5; 4] {
            return Err(ResolverError::new("unexpected controlled entropy sample"));
        }
        let event = ProposedEvent::new(
            event_id,
            EventTypeId::from(PROVENANCE_ROOT_EVENT),
            SchemaRevision::new(1),
            json!({"entity_id": entity_id.to_string(), "facet_value": 11}),
        );
        Ok(ResolveOutcome::Resolved(Resolution::new(
            vec![event],
            Vec::new(),
        )))
    }
}

struct ProvenanceChildResolver;

impl ActionResolver for ProvenanceChildResolver {
    fn resolve(
        &self,
        _context: &dyn ResolutionContext,
        _input: &Value,
    ) -> Result<ResolveOutcome, ResolverError> {
        Ok(ResolveOutcome::Resolved(Resolution::default()))
    }
}

fn provenance_registry() -> CapabilityRegistry {
    CapabilityRegistry::assemble([Box::new(ProvenanceCapability {
        manifest: CapabilityManifest::parse(PROVENANCE_CAPABILITY, "0.1.0")
            .expect("provenance manifest should parse"),
    }) as Box<dyn Capability>])
    .expect("provenance Capability registry should assemble")
}

#[derive(Clone, Copy, Debug, Default)]
struct T16EntropySource;

impl EntropySource for T16EntropySource {
    fn source_id(&self) -> EntropySourceId {
        EntropySourceId::from("validator-t16-entropy")
    }

    fn sample(&self, request: &EntropyRequest) -> Result<EntropySample, EntropySourceError> {
        Ok(EntropySample::new(vec![0xA5; request.byte_count()]))
    }
}

struct InMemoryHandle {
    store: &'static InMemoryStore,
    server: tokio::task::JoinHandle<()>,
    provenance: bool,
}

#[derive(Clone)]
struct InMemoryRevisionServer {
    inner: Arc<Mutex<InMemoryHandle>>,
}

impl InMemoryRevisionServer {
    fn start() -> Result<(Self, LoomClient), String> {
        Self::start_with(false)
    }

    fn start_with(provenance: bool) -> Result<(Self, LoomClient), String> {
        let store = Box::leak(Box::new(InMemoryStore::new()));
        let (client, handle) =
            common::leaked_runtime().block_on(start_in_memory(store, provenance))?;
        Ok((
            Self {
                inner: Arc::new(Mutex::new(handle)),
            },
            client,
        ))
    }

    fn restart(&self) -> Result<LoomClient, String> {
        let inner = Arc::clone(&self.inner);
        std::thread::spawn(move || {
            common::leaked_runtime().block_on(async move {
                let mut guard = inner.lock().await;
                guard.server.abort();
                let (client, handle) = start_in_memory(guard.store, guard.provenance).await?;
                *guard = handle;
                Ok::<LoomClient, String>(client)
            })
        })
        .join()
        .map_err(|_| "in-memory restart thread panicked".to_owned())?
    }
}

async fn start_in_memory(
    store: &'static InMemoryStore,
    provenance: bool,
) -> Result<(LoomClient, InMemoryHandle), String> {
    let registry = if provenance {
        provenance_registry()
    } else {
        neutral_registry()
    };
    registry
        .validate()
        .map_err(|error| format!("registry invalid: {error:?}"))?;
    confirm_in_memory_revisions_with(store, &registry, provenance)?;
    let runtime =
        Runtime::new(store, registry).map_err(|error| format!("Runtime failed: {error:?}"))?;
    let runtime = if provenance {
        runtime.with_entropy_source(T16EntropySource)
    } else {
        runtime
    };
    let router = router_with_admin(
        Arc::new(runtime),
        Arc::new(RequireAdminAuthorization),
        BoundaryConfig::default(),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .map_err(|error| error.to_string())?;
    let address = listener.local_addr().map_err(|error| error.to_string())?;
    let server = tokio::spawn(async move {
        if let Err(error) = axum::serve(listener, router).await {
            eprintln!("T16 InMemory server failed: {error}");
        }
    });
    tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    let client = LoomClient::builder(format!("http://{address}"))
        .admin_token("validator-test-admin")
        .map_err(|error| error.to_string())?
        .build()
        .map_err(|error| error.to_string())?;
    Ok((
        client,
        InMemoryHandle {
            store,
            server,
            provenance,
        },
    ))
}

fn postgres_url() -> (String, bool) {
    match env::var("LOOM_TEST_POSTGRES_URL") {
        Ok(url) if !url.trim().is_empty() => (url, false),
        _ => (DEFAULT_POSTGRES_CONTROL_URL.to_owned(), true),
    }
}

fn start_repository_postgres() -> Result<(), String> {
    let script = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tools/postgres-test.sh");
    let status = Command::new("bash")
        .arg(&script)
        .arg("up")
        .status()
        .map_err(|error| format!("failed to start {}: {error}", script.display()))?;
    status
        .success()
        .then_some(())
        .ok_or_else(|| format!("{} exited with {status}", script.display()))
}

async fn confirm_postgres_revisions(
    store: &PgStorage,
    registry: &CapabilityRegistry,
    provenance: bool,
) -> Result<(), String> {
    let (r1_id, r2_id) = if provenance {
        (PROVENANCE_R1_ID, PROVENANCE_R2_ID)
    } else {
        ("validator-t16-r1", "validator-t16-r2")
    };
    let r1 = revision(r1_id, &format!("{r1_id}-build"), registry);
    let r2 = revision(r2_id, &format!("{r2_id}-build"), registry);
    confirm_pg(store, r1).await?;
    confirm_pg(store, r2).await?;
    let active = RuntimeRevisionStore::read_active_revision(store)
        .await
        .map_err(|error| format!("read active revision failed: {error:?}"))?;
    if active
        .as_ref()
        .is_none_or(|value| value.revision().id() != &RuntimeRevisionId::from(r1_id))
    {
        RuntimeRevisionStore::activate_revision(
            store,
            RuntimeRevisionId::from(r1_id),
            active
                .as_ref()
                .map(loom_runtime::RuntimeRevisionSelection::generation),
            PlatformTime::default(),
        )
        .await
        .map_err(|error| format!("activate R1 failed: {error:?}"))?;
    }
    Ok(())
}

async fn confirm_pg(
    store: &PgStorage,
    descriptor: RuntimeRevisionDescriptor,
) -> Result<(), String> {
    match RuntimeRevisionStore::confirm_revision(store, descriptor).await {
        Ok(_) => Ok(()),
        Err(error) if format!("{error:?}").contains("already exists") => Ok(()),
        Err(error) => Err(format!("confirm revision failed: {error:?}")),
    }
}

struct PgHandle {
    store: PgStorage,
    server: tokio::task::JoinHandle<()>,
    provenance: bool,
}

#[derive(Clone)]
struct PgRevisionServer {
    inner: Arc<Mutex<PgHandle>>,
}

impl PgRevisionServer {
    fn start() -> Result<(Self, LoomClient), String> {
        Self::start_with(false)
    }

    fn start_with(provenance: bool) -> Result<(Self, LoomClient), String> {
        let (url, repository_default) = postgres_url();
        let store = common::leaked_runtime().block_on(async {
            match PgStorage::connect(&url).await {
                Ok(store) => Ok(store),
                Err(error) if repository_default => {
                    start_repository_postgres()?;
                    PgStorage::connect(&url).await.map_err(|retry| {
                        format!("PostgreSQL remained unavailable: {error:?}; {retry:?}")
                    })
                }
                Err(error) => Err(format!("PostgreSQL unavailable: {error:?}")),
            }
        })?;
        common::leaked_runtime()
            .block_on(async { store.health().await })
            .map_err(|error| format!("PostgreSQL health failed: {error:?}"))?;
        common::leaked_runtime()
            .block_on(async { store.migrate().await })
            .map_err(|error| format!("PostgreSQL migration failed: {error:?}"))?;
        let (client, handle) =
            common::leaked_runtime().block_on(start_postgres(store.clone(), provenance))?;
        Ok((
            Self {
                inner: Arc::new(Mutex::new(handle)),
            },
            client,
        ))
    }

    fn restart(&self) -> Result<LoomClient, String> {
        let inner = Arc::clone(&self.inner);
        std::thread::spawn(move || {
            common::leaked_runtime().block_on(async move {
                let mut guard = inner.lock().await;
                guard.server.abort();
                let (client, handle) =
                    start_postgres(guard.store.clone(), guard.provenance).await?;
                *guard = handle;
                Ok::<LoomClient, String>(client)
            })
        })
        .join()
        .map_err(|_| "PostgreSQL restart thread panicked".to_owned())?
    }
}

async fn start_postgres(
    store: PgStorage,
    provenance: bool,
) -> Result<(LoomClient, PgHandle), String> {
    let registry = if provenance {
        provenance_registry()
    } else {
        neutral_registry()
    };
    registry
        .validate()
        .map_err(|error| format!("registry invalid: {error:?}"))?;
    confirm_postgres_revisions(&store, &registry, provenance).await?;
    let runtime = Runtime::new(store.clone(), registry)
        .map_err(|error| format!("Runtime failed: {error:?}"))?;
    let runtime = if provenance {
        runtime.with_entropy_source(T16EntropySource)
    } else {
        runtime
    };
    let router = router_with_admin(
        Arc::new(runtime),
        Arc::new(RequireAdminAuthorization),
        BoundaryConfig::default(),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .map_err(|error| error.to_string())?;
    let address = listener.local_addr().map_err(|error| error.to_string())?;
    let server = tokio::spawn(async move {
        if let Err(error) = axum::serve(listener, router).await {
            eprintln!("T16 PostgreSQL server failed: {error}");
        }
    });
    tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    let client = LoomClient::builder(format!("http://{address}"))
        .admin_token("validator-test-admin")
        .map_err(|error| error.to_string())?
        .build()
        .map_err(|error| error.to_string())?;
    Ok((
        client,
        PgHandle {
            store,
            server,
            provenance,
        },
    ))
}

fn run_in_memory(id: &str) -> ScenarioResult {
    let (server, client) =
        InMemoryRevisionServer::start().expect("T16 InMemory server should start");
    let baseline = public_sessions(&client)
        .expect("T16 InMemory baseline Session list should be readable")
        .into_iter()
        .map(|session| session.id)
        .collect::<HashSet<_>>();
    let before_client = client.clone();
    let scenario_id = id.to_owned();
    let restart_server = server.clone();
    let restart = Arc::new(move || {
        let expected = public_sessions(&before_client)?
            .into_iter()
            .filter(|session| !baseline.contains(&session.id) && !session.event_refs.is_empty())
            .collect::<Vec<_>>();
        let restarted = restart_server.restart()?;
        assert_restarted_event_session_links(&scenario_id, &restarted, &expected)?;
        Ok(restarted)
    });
    let ctx = context(client, BackendKind::InMemory, id, restart);
    provenance::execute(&descriptor(id), &ctx)
}

fn run_postgres(id: &str) -> ScenarioResult {
    let _revision_state_guard = postgres_revision_state_guard();
    let (server, client) = PgRevisionServer::start().expect("T16 PostgreSQL server should start");
    let baseline = public_sessions(&client)
        .expect("T16 PostgreSQL baseline Session list should be readable")
        .into_iter()
        .map(|session| session.id)
        .collect::<HashSet<_>>();
    let before_client = client.clone();
    let scenario_id = id.to_owned();
    let restart_server = server.clone();
    let restart = Arc::new(move || {
        let expected = public_sessions(&before_client)?
            .into_iter()
            .filter(|session| !baseline.contains(&session.id) && !session.event_refs.is_empty())
            .collect::<Vec<_>>();
        let restarted = restart_server.restart()?;
        assert_restarted_event_session_links(&scenario_id, &restarted, &expected)?;
        Ok(restarted)
    });
    let ctx = context(client, BackendKind::PostgreSQL, id, restart);
    provenance::execute(&descriptor(id), &ctx)
}

fn run_provenance_in_memory() -> ScenarioResult {
    let (server, client) = InMemoryRevisionServer::start_with(true)
        .expect("T16 provenance InMemory server should start");
    let baseline = public_sessions(&client)
        .expect("T16 provenance InMemory baseline Session list should be readable")
        .into_iter()
        .map(|session| session.id)
        .collect::<HashSet<_>>();
    let before_client = client.clone();
    let restart_server = server.clone();
    let restart = Arc::new(move || {
        let expected = public_sessions(&before_client)?
            .into_iter()
            .filter(|session| !baseline.contains(&session.id) && !session.event_refs.is_empty())
            .collect::<Vec<_>>();
        let restarted = restart_server.restart()?;
        assert_restarted_event_session_links("CV-033", &restarted, &expected)?;
        Ok(restarted)
    });
    let ctx = context(client, BackendKind::InMemory, "CV-033", restart);
    provenance::execute(&descriptor("CV-033"), &ctx)
}

fn run_provenance_postgres() -> ScenarioResult {
    let _revision_state_guard = postgres_revision_state_guard();
    let (server, client) =
        PgRevisionServer::start_with(true).expect("T16 provenance PostgreSQL server should start");
    let baseline = public_sessions(&client)
        .expect("T16 provenance PostgreSQL baseline Session list should be readable")
        .into_iter()
        .map(|session| session.id)
        .collect::<HashSet<_>>();
    let before_client = client.clone();
    let restart_server = server.clone();
    let restart = Arc::new(move || {
        let expected = public_sessions(&before_client)?
            .into_iter()
            .filter(|session| !baseline.contains(&session.id) && !session.event_refs.is_empty())
            .collect::<Vec<_>>();
        let restarted = restart_server.restart()?;
        assert_restarted_event_session_links("CV-033", &restarted, &expected)?;
        Ok(restarted)
    });
    let ctx = context(client, BackendKind::PostgreSQL, "CV-033", restart);
    provenance::execute(&descriptor("CV-033"), &ctx)
}

#[test]
fn cv031_event_session_revision_survives_activation_and_inmemory_restart() {
    assert_pass(&run_in_memory("CV-031"), "CV-031");
}

#[test]
fn cv032_new_session_uses_r2_and_inmemory_history_does_not_drift() {
    assert_pass(&run_in_memory("CV-032"), "CV-032");
}

#[test]
fn cv031_event_session_revision_survives_live_postgres_restart() {
    assert_pass(&run_postgres("CV-031"), "CV-031");
}

#[test]
fn cv032_new_session_uses_r2_and_live_postgres_history_does_not_drift() {
    assert_pass(&run_postgres("CV-032"), "CV-032");
}

#[test]
fn cv033_proves_public_provenance_through_inmemory_restart() {
    assert_pass(&run_provenance_in_memory(), "CV-033");
}

#[test]
fn cv033_proves_public_provenance_through_live_postgres_restart() {
    assert_pass(&run_provenance_postgres(), "CV-033");
}

#[test]
fn provenance_requires_controlled_boundary_restart() {
    let client = LoomClient::builder("http://127.0.0.1:1".to_owned())
        .build()
        .expect("client should build");
    let ctx = BackendContext::new(client)
        .with_backend_kind(BackendKind::InMemory)
        .with_scope("reconnect-only");
    for id in ["CV-031", "CV-032", "CV-033"] {
        let result = provenance::execute(&descriptor(id), &ctx);
        assert!(result.outcome().is_unavailable(), "{id}: {result:?}");
        assert!(
            result
                .finding()
                .actual()
                .contains("ControlledBoundaryRestart")
        );
    }
}
