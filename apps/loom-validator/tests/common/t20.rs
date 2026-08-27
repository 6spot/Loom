//! Test-only `PostgreSQL` fixtures used by the T20 live gate.

use std::{collections::HashSet, env, str::FromStr, sync::Arc};

use loom_api::{
    ActionTypeId, AdminExecutionSession, AdminService, EntityId, EventId, EventTypeId, FacetOwner,
    FacetTypeId, IngressId, SchemaRevision, WorldEffect,
};
use loom_boundary::{BoundaryConfig, RequireAdminAuthorization, router_with_admin};
use loom_capability::{
    ActionDefinition, ActionResolver, Capability, CapabilityManifest, CapabilityRegistrar,
    CapabilityRegistry, EventDefinition, FacetDefinition, RegistrationError, ResolutionContext,
    ResolverError,
};
use loom_client::LoomClient;
use loom_neutral::registry as neutral_registry;
use loom_protocol::{ActionInvocation, ProposedEvent, Resolution, ResolveOutcome};
use loom_runtime::{
    EntropyRequest, EntropySample, EntropySource, EntropySourceError, EntropySourceId,
    PlatformTime, Runtime, RuntimeRevisionCapability, RuntimeRevisionDescriptor, RuntimeRevisionId,
    RuntimeRevisionStore,
};
use loom_storage::PgStorage;
use loom_validator::{BackendContext, BackendKind, ScenarioResult, provenance};
use serde_json::{Value, json};
use tokio::sync::Mutex;

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

fn postgres_url() -> (String, bool) {
    match env::var("LOOM_TEST_POSTGRES_URL") {
        Ok(url) if !url.trim().is_empty() => (url, false),
        _ => (DEFAULT_POSTGRES_CONTROL_URL.to_owned(), true),
    }
}

fn start_repository_postgres() -> Result<(), String> {
    let script =
        std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../tools/postgres-test.sh");
    let status = std::process::Command::new("bash")
        .arg(&script)
        .arg("up")
        .status()
        .map_err(|error| format!("failed to start {}: {error}", script.display()))?;
    status
        .success()
        .then_some(())
        .ok_or_else(|| format!("{} exited with {status}", script.display()))
}

fn provenance_registry() -> CapabilityRegistry {
    CapabilityRegistry::assemble([Box::new(ProvenanceCapability {
        manifest: CapabilityManifest::parse(PROVENANCE_CAPABILITY, "0.1.0")
            .expect("provenance manifest should parse"),
    }) as Box<dyn Capability>])
    .expect("provenance registry should assemble")
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
    .expect("T16 revision should be valid")
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
            json!({"type":"object","required":["value"],"properties":{"value":{"type":"integer"}}}),
        ))?;
        registrar.register_event(
            EventDefinition::new(
                EventTypeId::from(PROVENANCE_SEED_EVENT),
                SchemaRevision::new(1),
            )
            .with_payload_schema(json!({"type":"object"})),
        )?;
        registrar.register_event(
            EventDefinition::new(
                EventTypeId::from(PROVENANCE_ROOT_EVENT),
                SchemaRevision::new(1),
            )
            .with_payload_schema(json!({"type":"object"})),
        )?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(PROVENANCE_SEED), SchemaRevision::new(1))
                .with_input_schema(json!({"type":"object","required":["event_id","entity_id"],"properties":{"event_id":{"type":"string"},"entity_id":{"type":"string"}}})),
            ProvenanceSeedResolver,
        )?;
        registrar.register_action(
            ActionDefinition::new(ActionTypeId::from(PROVENANCE_ROOT), SchemaRevision::new(1))
                .with_input_schema(json!({"type":"object","required":["event_id","entity_id"],"properties":{"event_id":{"type":"string"},"entity_id":{"type":"string"}}})),
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
            json!({"entity_id":entity_id.to_string()}),
        )
        .with_effect(WorldEffect::CreateEntity { entity_id })
        .with_effect(WorldEffect::PutFacet {
            owner: FacetOwner::entity(entity_id),
            facet_type: FacetTypeId::from(PROVENANCE_FACET),
            schema_revision: SchemaRevision::new(1),
            value: json!({"value":11}),
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
            json!({"entity_id":entity_id.to_string(),"facet_value":11}),
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

struct Handle {
    store: PgStorage,
    server: tokio::task::JoinHandle<()>,
    provenance: bool,
}
#[derive(Clone)]
pub struct ProvenanceServer {
    inner: Arc<Mutex<Handle>>,
}

impl ProvenanceServer {
    pub fn start() -> Result<(Self, LoomClient), String> {
        Self::start_with(true)
    }

    pub fn start_neutral() -> Result<(Self, LoomClient), String> {
        Self::start_with(false)
    }

    fn start_with(provenance: bool) -> Result<(Self, LoomClient), String> {
        let (url, repository_default) = postgres_url();
        let store = super::leaked_runtime().block_on(async {
            let store = match PgStorage::connect(&url).await {
                Ok(store) => store,
                Err(error) if repository_default => {
                    start_repository_postgres()?;
                    PgStorage::connect(&url).await.map_err(|retry| {
                        format!("PostgreSQL remained unavailable: {error:?}; {retry:?}")
                    })?
                }
                Err(error) => return Err(format!("PostgreSQL unavailable: {error:?}")),
            };
            store.health().await.map_err(|error| format!("{error:?}"))?;
            store
                .migrate()
                .await
                .map_err(|error| format!("{error:?}"))?;
            Ok::<PgStorage, String>(store)
        })?;
        let (client, handle) = super::leaked_runtime().block_on(start(&store, provenance))?;
        Ok((
            Self {
                inner: Arc::new(Mutex::new(handle)),
            },
            client,
        ))
    }

    pub fn restart(&self) -> Result<LoomClient, String> {
        let inner = Arc::clone(&self.inner);
        std::thread::spawn(move || {
            super::leaked_runtime().block_on(async {
                let mut guard = inner.lock().await;
                guard.server.abort();
                let (client, handle) = start(&guard.store, guard.provenance).await?;
                *guard = handle;
                Ok::<LoomClient, String>(client)
            })
        })
        .join()
        .map_err(|_| "T16 PostgreSQL restart thread panicked".to_owned())?
    }
}

async fn start(store: &PgStorage, provenance: bool) -> Result<(LoomClient, Handle), String> {
    let registry = if provenance {
        provenance_registry()
    } else {
        neutral_registry()
    };
    registry.validate().map_err(|error| format!("{error:?}"))?;
    let revisions = if provenance {
        [
            (PROVENANCE_R1_ID, "validator-t16-cv033-r1-build"),
            (PROVENANCE_R2_ID, "validator-t16-cv033-r2-build"),
        ]
    } else {
        [
            ("validator-t16-r1", "validator-t16-r1-build"),
            ("validator-t16-r2", "validator-t16-r2-build"),
        ]
    };
    for (id, build) in revisions {
        match RuntimeRevisionStore::confirm_revision(store, revision(id, build, &registry)).await {
            Ok(_) => {}
            Err(error) if format!("{error:?}").contains("already exists") => {}
            Err(error) => return Err(format!("confirm revision failed: {error:?}")),
        }
    }
    let active = RuntimeRevisionStore::read_active_revision(store)
        .await
        .map_err(|error| format!("{error:?}"))?;
    let r1_id = if provenance {
        PROVENANCE_R1_ID
    } else {
        "validator-t16-r1"
    };
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
        .map_err(|error| format!("activate revision failed: {error:?}"))?;
    }
    let runtime = Runtime::new(store.clone(), registry)
        .map_err(|error| format!("runtime failed: {error:?}"))?;
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
        Handle {
            store: store.clone(),
            server,
            provenance,
        },
    ))
}

/// Executes CV-031 or CV-032 through the same structured Validator path with
/// the neutral T16 revision fixture used by the existing suite.
pub fn run_neutral(id: &str) -> ScenarioResult {
    let (server, client) =
        ProvenanceServer::start_neutral().expect("T16 PostgreSQL server should start");
    let baseline = sessions(&client)
        .expect("baseline sessions should be readable")
        .into_iter()
        .map(|item| item.id)
        .collect::<HashSet<_>>();
    let before = client.clone();
    let restart_server = server.clone();
    let scenario_id = id.to_owned();
    let restart = Arc::new(move || {
        let expected = sessions(&before)?
            .into_iter()
            .filter(|item| !baseline.contains(&item.id) && !item.event_refs.is_empty())
            .collect::<Vec<_>>();
        let restarted = restart_server.restart()?;
        assert_restart(&scenario_id, &restarted, &expected)?;
        Ok(restarted)
    });
    let context = BackendContext::new(client)
        .with_backend_kind(BackendKind::PostgreSQL)
        .with_scope(format!("T20-{id}"))
        .with_restart_strategy(restart)
        .with_controlled_boundary_restart();
    let descriptor = provenance::descriptors()
        .into_iter()
        .find(|item| item.id_str() == id)
        .expect("T16 descriptor");
    provenance::execute(&descriptor, &context)
}

fn sessions(client: &LoomClient) -> Result<Vec<AdminExecutionSession>, String> {
    super::leaked_runtime()
        .block_on(async { client.list_execution_sessions().await })
        .map_err(|error| format!("session list failed: {error:?}"))
}

fn session(
    client: &LoomClient,
    id: loom_api::ExecutionSessionId,
) -> Result<AdminExecutionSession, String> {
    super::leaked_runtime()
        .block_on(async {
            client
                .get_execution_session(loom_api::AdminExecutionSessionRequest { session_id: id })
                .await
        })
        .map_err(|error| format!("session read failed: {error:?}"))
}

fn session_for_event(
    client: &LoomClient,
    event: loom_api::EventRef,
) -> Result<loom_api::ExecutionSessionId, String> {
    super::leaked_runtime()
        .block_on(async { client.session_for_event(event).await })
        .map_err(|error| format!("event lookup failed: {error:?}"))?
        .session_id
        .ok_or_else(|| "event has no producing session".to_owned())
}

fn assert_restart(
    id: &str,
    client: &LoomClient,
    expected: &[AdminExecutionSession],
) -> Result<(), String> {
    if id == "CV-033" {
        for item in expected {
            for event in item.event_refs.iter().copied() {
                if session_for_event(client, event)? != item.id {
                    return Err(format!(
                        "event {event:?} no longer resolves to session {:?}",
                        item.id
                    ));
                }
            }
        }
    }
    Ok(())
}

/// Executes CV-033 through the public Validator executor on a provenance-aware
/// `PostgreSQL` boundary, including the real controlled restart callback.
pub fn run_cv033() -> ScenarioResult {
    let (server, client) = ProvenanceServer::start().expect("T16 PostgreSQL server should start");
    let baseline = sessions(&client)
        .expect("baseline sessions should be readable")
        .into_iter()
        .map(|item| item.id)
        .collect::<HashSet<_>>();
    let before = client.clone();
    let restart_server = server.clone();
    let restart = Arc::new(move || {
        let expected = sessions(&before)?
            .into_iter()
            .filter(|item| !baseline.contains(&item.id) && !item.event_refs.is_empty())
            .collect::<Vec<_>>();
        let restarted = restart_server.restart()?;
        assert_restart("CV-033", &restarted, &expected)?;
        Ok(restarted)
    });
    let context = BackendContext::new(client)
        .with_backend_kind(BackendKind::PostgreSQL)
        .with_scope("T20-CV-033")
        .with_restart_strategy(restart)
        .with_controlled_boundary_restart();
    let descriptor = provenance::descriptors()
        .into_iter()
        .find(|item| item.id_str() == "CV-033")
        .expect("CV-033 descriptor");
    provenance::execute(&descriptor, &context)
}

/// `PostgreSQL` boundary with the repository's explicit ingress processing pump.
/// The production CV-016 executor remains unchanged; this only composes the
/// test worker needed to turn Accepted into a durable Completed result.
#[derive(Clone)]
pub struct PumpServer {
    command: std::sync::mpsc::Sender<PumpCommand>,
}

enum PumpCommand {
    Pump,
    Restart(std::sync::mpsc::Sender<Result<LoomClient, String>>),
}

struct PumpState {
    runtime: Arc<Runtime<PgStorage>>,
    server: tokio::task::JoinHandle<()>,
    address: std::net::SocketAddr,
}

impl PumpServer {
    pub fn start() -> Result<(Self, LoomClient), String> {
        let (command, command_rx) = std::sync::mpsc::channel();
        let (ready_tx, ready_rx) = std::sync::mpsc::channel();
        std::thread::spawn(move || {
            let runtime = tokio::runtime::Builder::new_multi_thread()
                .enable_all()
                .build()
                .map_err(|error| format!("build CV-016 pump runtime: {error}"));
            let Ok(runtime) = runtime else {
                let _ = ready_tx.send(Err(runtime.err().unwrap()));
                return;
            };
            let setup = runtime.block_on(async { connect_pg().await });
            let Ok(store) = setup else {
                let _ = ready_tx.send(Err(setup.err().unwrap()));
                return;
            };
            let state = runtime.block_on(start_pump_state(store.clone()));
            let Ok(mut state) = state else {
                let _ = ready_tx.send(Err(state.err().unwrap()));
                return;
            };
            let client = client_for_state(&state);
            if ready_tx.send(client).is_err() {
                return;
            }
            loop {
                match command_rx.try_recv() {
                    Ok(PumpCommand::Pump) => {
                        let _ = runtime.block_on(state.runtime.process_ingress(
                            IngressId::from("ingress-cv016-1"),
                            PlatformTime::new(0),
                            PlatformTime::new(10),
                            PlatformTime::new(0),
                        ));
                    }
                    Ok(PumpCommand::Restart(reply)) => {
                        state.server.abort();
                        let next = runtime.block_on(start_pump_state(store.clone()));
                        let result = match next {
                            Ok(next) => {
                                state = next;
                                client_for_state(&state)
                            }
                            Err(error) => Err(error),
                        };
                        let _ = reply.send(result);
                    }
                    Err(std::sync::mpsc::TryRecvError::Empty) => {}
                    Err(std::sync::mpsc::TryRecvError::Disconnected) => return,
                }
                runtime.block_on(async {
                    tokio::time::sleep(std::time::Duration::from_millis(5)).await;
                });
            }
        });
        let client = ready_rx
            .recv()
            .map_err(|_| "CV-016 pump thread stopped".to_owned())??;
        Ok((Self { command }, client))
    }

    pub fn restart(&self) -> Result<LoomClient, String> {
        let (reply, response) = std::sync::mpsc::channel();
        self.command
            .send(PumpCommand::Restart(reply))
            .map_err(|error| error.to_string())?;
        response
            .recv()
            .map_err(|_| "CV-016 pump restart did not respond".to_owned())?
    }

    pub fn pump_once(&self) -> Result<(), String> {
        self.command
            .send(PumpCommand::Pump)
            .map_err(|error| error.to_string())
    }
}

async fn connect_pg() -> Result<PgStorage, String> {
    let (url, repository_default) = postgres_url();
    let store = match PgStorage::connect(&url).await {
        Ok(store) => store,
        Err(error) if repository_default => {
            start_repository_postgres()?;
            PgStorage::connect(&url)
                .await
                .map_err(|retry| format!("PostgreSQL remained unavailable: {error:?}; {retry:?}"))?
        }
        Err(error) => return Err(format!("PostgreSQL unavailable: {error:?}")),
    };
    store.health().await.map_err(|error| format!("{error:?}"))?;
    store
        .migrate()
        .await
        .map_err(|error| format!("{error:?}"))?;
    Ok(store)
}

async fn start_pump_state(store: PgStorage) -> Result<PumpState, String> {
    let registry = neutral_registry();
    registry.validate().map_err(|error| format!("{error:?}"))?;
    let descriptor = pump_revision(
        "validator-t20-cv016",
        "validator-t20-cv016-build",
        &registry,
    );
    match RuntimeRevisionStore::confirm_revision(&store, descriptor.clone()).await {
        Ok(_) => {}
        Err(error) if format!("{error:?}").contains("already exists") => {}
        Err(error) => return Err(format!("confirm revision failed: {error:?}")),
    }
    let active = RuntimeRevisionStore::read_active_revision(&store)
        .await
        .map_err(|error| format!("{error:?}"))?;
    if active
        .as_ref()
        .is_none_or(|value| value.revision().id() != descriptor.id())
    {
        RuntimeRevisionStore::activate_revision(
            &store,
            descriptor.id().clone(),
            active
                .as_ref()
                .map(loom_runtime::RuntimeRevisionSelection::generation),
            PlatformTime::default(),
        )
        .await
        .map_err(|error| format!("activate revision failed: {error:?}"))?;
    }
    let runtime = Arc::new(
        Runtime::new(store.clone(), registry)
            .map_err(|error| format!("runtime failed: {error:?}"))?,
    );
    let router = router_with_admin(
        Arc::clone(&runtime),
        Arc::new(RequireAdminAuthorization),
        BoundaryConfig::default(),
    );
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .map_err(|error| error.to_string())?;
    let address = listener.local_addr().map_err(|error| error.to_string())?;
    let server = tokio::spawn(async move {
        if let Err(error) = axum::serve(listener, router).await {
            eprintln!("CV-016 PG server failed: {error}");
        }
    });
    tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    Ok(PumpState {
        runtime,
        server,
        address,
    })
}

fn client_for_state(state: &PumpState) -> Result<LoomClient, String> {
    LoomClient::builder(format!("http://{}", state.address))
        .admin_token("validator-test-admin")
        .map_err(|error| error.to_string())?
        .build()
        .map_err(|error| error.to_string())
}

fn pump_revision(
    id: &str,
    build: &str,
    registry: &CapabilityRegistry,
) -> RuntimeRevisionDescriptor {
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
    .expect("T20 revision should be valid")
}
