//! Official Loom CLI over the formal HTTP client.
//!
//! The CLI is a pure consumer of `loom-client` and `loom-api` contracts. It
//! maps each public service method to a subcommand, serializes `loom-api` DTOs
//! directly for deterministic JSON output, and maps `ApiErrorCode` to distinct
//! nonzero exit codes.

#![forbid(unsafe_code)]
#![allow(clippy::doc_markdown)]
#![allow(clippy::missing_errors_doc)]
#![allow(clippy::must_use_candidate)]
#![allow(clippy::large_enum_variant)]

use std::{fs, path::PathBuf, str::FromStr, time::Duration};

use clap::{Parser, Subcommand, ValueEnum};
use loom_api::{
    ActionRequest, ActionService, ActionTypeId, AdminActivateRuntimeRevisionRequest,
    AdminAdvanceWorldTimeRequest, AdminExecutionSessionRequest, AdminMissingImplementationRequest,
    AdminRuntimeRevisionRequest, AdminScheduleAgencyWakeRequest, AdminService,
    AdminTerminalWorkState, AdminTerminalizeWorkRequest, ApiError, ApiErrorCode, CatalogService,
    CausalDirection, CausalQuery, ChangeFeedCursor, CreateWorldFromTemplateRequest, EntityId,
    EntityTrajectoryQuery, EventId, EventQuery, EventRef, EventSeq, ExecutionSessionId, FacetOwner,
    FacetQuery, FacetTypeId, HistoryService, IngressEnvelope, IngressId, IngressService,
    QueryService, RelationshipId, RelationshipTrajectoryQuery, StateRevision, SubscriptionService,
    TimelineId, TimelineService, TimelineTarget, TimelineVersion, WorkId, WorldId, WorldInstant,
    WorldService,
};
use loom_client::{ClientBuilder, LoomClient};
use serde::Serialize;

/// Output mode for the CLI.
#[derive(Clone, Copy, Debug, Eq, PartialEq, ValueEnum, Default)]
pub enum OutputMode {
    /// Deterministic compact JSON suitable for scripting.
    #[default]
    Json,
    /// Human-readable pretty JSON.
    Human,
    /// Alias for `human`.
    Pretty,
}

impl OutputMode {
    fn is_json(self) -> bool {
        matches!(self, Self::Json)
    }
}

/// Global connection and output options.
#[derive(Parser, Debug, Clone)]
#[command(name = "loom", version, about = "Official Loom CLI over loom-client")]
pub struct Cli {
    /// Loom server base URL.
    #[arg(long, env = "LOOM_SERVER_URL", default_value = "http://127.0.0.1:8080")]
    pub server: String,

    /// Bearer token for ordinary API authentication.
    #[arg(long, env = "LOOM_BEARER_TOKEN")]
    pub bearer_token: Option<String>,

    /// Admin token for isolated /v1/admin operations.
    #[arg(long, env = "LOOM_ADMIN_TOKEN")]
    pub admin_token: Option<String>,

    /// Output mode.
    #[arg(long, value_enum, default_value_t = OutputMode::Json)]
    pub output: OutputMode,

    /// Request timeout in seconds.
    #[arg(long, default_value_t = 30)]
    pub timeout_secs: u64,

    #[command(subcommand)]
    pub command: Commands,
}

/// Top-level command set.
#[derive(Subcommand, Debug, Clone)]
pub enum Commands {
    /// Catalog discovery.
    Catalog(CatalogArgs),
    /// World operations.
    World(WorldArgs),
    /// Timeline operations.
    Timeline(TimelineArgs),
    /// Action invocation.
    Action(ActionArgs),
    /// Facet query.
    Facet(FacetArgs),
    /// History queries.
    History(HistoryArgs),
    /// Trajectory queries.
    Trajectory(TrajectoryArgs),
    /// Change feed subscription.
    Feed(FeedArgs),
    /// Ingress operations.
    Ingress(IngressArgs),
    /// Admin operations.
    Admin(AdminArgs),
}

// Catalog
#[derive(Parser, Debug, Clone)]
pub struct CatalogArgs {
    /// World ID for per-world catalog; when omitted, global catalog is used.
    #[arg(long)]
    pub world_id: Option<String>,
}

// World
#[derive(Subcommand, Debug, Clone)]
pub enum WorldCommands {
    /// Create a world from a template descriptor.
    Create(WorldCreateArgs),
}

#[derive(Parser, Debug, Clone)]
pub struct WorldArgs {
    #[command(subcommand)]
    pub command: WorldCommands,
}

#[derive(Parser, Debug, Clone)]
pub struct WorldCreateArgs {
    /// Path to a JSON file containing a WorldTemplateDescriptor.
    #[arg(long)]
    pub template_file: Option<PathBuf>,
    /// Inline JSON for CreateWorldFromTemplateRequest or WorldTemplateDescriptor.
    #[arg(long)]
    pub template_json: Option<String>,
    /// Inline JSON file for the full CreateWorldFromTemplateRequest.
    #[arg(long)]
    pub request_file: Option<PathBuf>,
}

// Timeline
#[derive(Subcommand, Debug, Clone)]
pub enum TimelineCommands {
    /// Inspect a timeline.
    Inspect(TimelineInspectArgs),
    /// Fork a timeline.
    Fork(TimelineForkArgs),
}

#[derive(Parser, Debug, Clone)]
pub struct TimelineArgs {
    #[command(subcommand)]
    pub command: TimelineCommands,
}

#[derive(Parser, Debug, Clone)]
pub struct TimelineInspectArgs {
    #[arg(long)]
    pub world: String,
    #[arg(long)]
    pub timeline: String,
}

#[derive(Parser, Debug, Clone)]
pub struct TimelineForkArgs {
    #[arg(long)]
    pub world: String,
    #[arg(long)]
    pub timeline: String,
    /// Optional JSON for ForkTimelineRequest.
    #[arg(long)]
    pub request_file: Option<PathBuf>,
    /// Optional JSON inline for ForkTimelineRequest.
    #[arg(long)]
    pub request_json: Option<String>,
    /// Optional source version as JSON {"head_event_seq":1,"state_revision":1} or "seq:rev".
    #[arg(long)]
    pub source_version: Option<String>,
}

// Action
#[derive(Subcommand, Debug, Clone)]
pub enum ActionCommands {
    /// Invoke an action.
    Invoke(ActionInvokeArgs),
}

#[derive(Parser, Debug, Clone)]
pub struct ActionArgs {
    #[command(subcommand)]
    pub command: ActionCommands,
}

#[derive(Parser, Debug, Clone)]
pub struct ActionInvokeArgs {
    #[arg(long)]
    pub world: String,
    #[arg(long)]
    pub timeline: String,
    #[arg(long)]
    pub action: Option<String>,
    #[arg(long)]
    pub input: Option<String>,
    #[arg(long)]
    pub input_file: Option<PathBuf>,
    /// Path to a JSON file containing an ActionRequest.
    #[arg(long)]
    pub request_file: Option<PathBuf>,
    /// Inline JSON for ActionRequest.
    #[arg(long)]
    pub request_json: Option<String>,
}

// Facet
#[derive(Subcommand, Debug, Clone)]
pub enum FacetCommands {
    /// Get a facet value.
    Get(FacetGetArgs),
}

#[derive(Parser, Debug, Clone)]
pub struct FacetArgs {
    #[command(subcommand)]
    pub command: FacetCommands,
}

#[derive(Parser, Debug, Clone)]
pub struct FacetGetArgs {
    #[arg(long)]
    pub world: String,
    #[arg(long)]
    pub timeline: String,
    #[arg(long)]
    pub owner: String,
    /// Owner kind: entity or relationship.
    #[arg(long, default_value = "entity")]
    pub owner_kind: String,
    #[arg(long)]
    pub facet_type: String,
    /// Optional JSON for FacetQuery.
    #[arg(long)]
    pub request_file: Option<PathBuf>,
    #[arg(long)]
    pub request_json: Option<String>,
}

// History
#[derive(Subcommand, Debug, Clone)]
pub enum HistoryCommands {
    /// List events.
    Events(HistoryEventsArgs),
    /// Get a single event.
    Event(HistoryEventArgs),
    /// Direct causes.
    Causes(HistoryCausesArgs),
    /// Direct effects.
    Effects(HistoryEffectsArgs),
    /// Causal walk.
    Walk(HistoryWalkArgs),
}

#[derive(Parser, Debug, Clone)]
pub struct HistoryArgs {
    #[command(subcommand)]
    pub command: HistoryCommands,
}

#[derive(Parser, Debug, Clone)]
pub struct HistoryEventsArgs {
    #[arg(long)]
    pub world: String,
    #[arg(long)]
    pub timeline: String,
    #[arg(long)]
    pub after: Option<u64>,
    #[arg(long)]
    pub limit: Option<u32>,
    #[arg(long)]
    pub request_file: Option<PathBuf>,
    #[arg(long)]
    pub request_json: Option<String>,
}

#[derive(Parser, Debug, Clone)]
pub struct HistoryEventArgs {
    #[arg(long)]
    pub world: Option<String>,
    #[arg(long)]
    pub timeline: Option<String>,
    #[arg(long)]
    pub event_id: Option<String>,
    /// Timeline-qualified EventRef as JSON or "timeline:uuid/event:uuid".
    #[arg(long)]
    pub event_ref: Option<String>,
    #[arg(long)]
    pub request_file: Option<PathBuf>,
    #[arg(long)]
    pub request_json: Option<String>,
}

#[derive(Parser, Debug, Clone)]
pub struct HistoryCausesArgs {
    #[arg(long)]
    pub timeline: String,
    #[arg(long)]
    pub event_id: String,
}

#[derive(Parser, Debug, Clone)]
pub struct HistoryEffectsArgs {
    #[arg(long)]
    pub timeline: String,
    #[arg(long)]
    pub event_id: String,
}

#[derive(Parser, Debug, Clone)]
pub struct HistoryWalkArgs {
    #[arg(long)]
    pub timeline: String,
    #[arg(long)]
    pub event_id: String,
    #[arg(long, default_value = "causes")]
    pub direction: String,
    #[arg(long, default_value_t = 10)]
    pub max_depth: u32,
    #[arg(long, default_value_t = 100)]
    pub limit: u32,
    #[arg(long)]
    pub request_file: Option<PathBuf>,
    #[arg(long)]
    pub request_json: Option<String>,
}

// Trajectory
#[derive(Subcommand, Debug, Clone)]
pub enum TrajectoryCommands {
    /// Entity trajectory.
    Entity(TrajectoryEntityArgs),
    /// Relationship trajectory.
    Relationship(TrajectoryRelationshipArgs),
}

#[derive(Parser, Debug, Clone)]
pub struct TrajectoryArgs {
    #[command(subcommand)]
    pub command: TrajectoryCommands,
}

#[derive(Parser, Debug, Clone)]
pub struct TrajectoryEntityArgs {
    #[arg(long)]
    pub world: String,
    #[arg(long)]
    pub timeline: String,
    #[arg(long)]
    pub entity_id: String,
    #[arg(long)]
    pub after: Option<u64>,
    #[arg(long)]
    pub limit: Option<u32>,
    #[arg(long)]
    pub request_file: Option<PathBuf>,
    #[arg(long)]
    pub request_json: Option<String>,
}

#[derive(Parser, Debug, Clone)]
pub struct TrajectoryRelationshipArgs {
    #[arg(long)]
    pub world: String,
    #[arg(long)]
    pub timeline: String,
    #[arg(long)]
    pub relationship_id: String,
    #[arg(long)]
    pub after: Option<u64>,
    #[arg(long)]
    pub limit: Option<u32>,
    #[arg(long)]
    pub request_file: Option<PathBuf>,
    #[arg(long)]
    pub request_json: Option<String>,
}

// Feed
#[derive(Subcommand, Debug, Clone)]
pub enum FeedCommands {
    /// Subscribe / tail the change feed.
    Subscribe(FeedSubscribeArgs),
    /// Alias for subscribe.
    Tail(FeedSubscribeArgs),
}

#[derive(Parser, Debug, Clone)]
pub struct FeedArgs {
    #[command(subcommand)]
    pub command: FeedCommands,
}

#[derive(Parser, Debug, Clone)]
pub struct FeedSubscribeArgs {
    #[arg(long)]
    pub world: String,
    #[arg(long)]
    pub timeline: String,
    #[arg(long)]
    pub after: Option<u64>,
    #[arg(long, default_value_t = 100)]
    pub limit: u32,
    /// Optional file containing SubscriptionRequest JSON.
    #[arg(long)]
    pub request_file: Option<PathBuf>,
    #[arg(long)]
    pub request_json: Option<String>,
}

// Ingress
#[derive(Subcommand, Debug, Clone)]
pub enum IngressCommands {
    /// Submit an ingress envelope.
    Submit(IngressSubmitArgs),
    /// Query ingress status.
    Status(IngressStatusArgs),
}

#[derive(Parser, Debug, Clone)]
pub struct IngressArgs {
    #[command(subcommand)]
    pub command: IngressCommands,
}

#[derive(Parser, Debug, Clone)]
pub struct IngressSubmitArgs {
    /// Path to JSON file containing IngressEnvelope.
    #[arg(long)]
    pub file: Option<PathBuf>,
    #[arg(long)]
    pub json: Option<String>,
    // Convenience fields for constructing envelope manually
    #[arg(long)]
    pub ingress_id: Option<String>,
    #[arg(long)]
    pub idempotency_key: Option<String>,
    #[arg(long)]
    pub world: Option<String>,
    #[arg(long)]
    pub timeline: Option<String>,
    #[arg(long)]
    pub action: Option<String>,
    #[arg(long)]
    pub input: Option<String>,
    #[arg(long)]
    pub input_file: Option<PathBuf>,
    #[arg(long)]
    pub source: Option<String>,
}

#[derive(Parser, Debug, Clone)]
pub struct IngressStatusArgs {
    #[arg(long)]
    pub ingress_id: String,
}

// Admin
#[derive(Subcommand, Debug, Clone)]
pub enum AdminCommands {
    /// Runtime revision operations.
    Revision(AdminRevisionArgs),
    /// Execution session operations.
    Session(AdminSessionArgs),
    /// Timeline admin operations.
    Timeline(AdminTimelineArgs),
    /// Work admin operations.
    Work(AdminWorkArgs),
    /// Agency operations.
    Agency(AdminAgencyArgs),
    /// World time operations.
    WorldTime(AdminWorldTimeArgs),
}

#[derive(Parser, Debug, Clone)]
pub struct AdminArgs {
    #[command(subcommand)]
    pub command: AdminCommands,
}

#[derive(Subcommand, Debug, Clone)]
pub enum AdminRevisionSubcommands {
    Active,
    List,
    Get(AdminRevisionGetArgs),
    Activate(AdminRevisionActivateArgs),
}

#[derive(Parser, Debug, Clone)]
pub struct AdminRevisionArgs {
    #[command(subcommand)]
    pub command: AdminRevisionSubcommands,
}

#[derive(Parser, Debug, Clone)]
pub struct AdminRevisionGetArgs {
    #[arg(long)]
    pub revision_id: String,
}

#[derive(Parser, Debug, Clone)]
pub struct AdminRevisionActivateArgs {
    #[arg(long)]
    pub revision_id: String,
    #[arg(long)]
    pub expected_generation: Option<u64>,
    #[arg(long)]
    pub request_file: Option<PathBuf>,
    #[arg(long)]
    pub request_json: Option<String>,
}

#[derive(Subcommand, Debug, Clone)]
pub enum AdminSessionSubcommands {
    List,
    Get(AdminSessionGetArgs),
    ForEvent(AdminSessionForEventArgs),
}

#[derive(Parser, Debug, Clone)]
pub struct AdminSessionArgs {
    #[command(subcommand)]
    pub command: AdminSessionSubcommands,
}

#[derive(Parser, Debug, Clone)]
pub struct AdminSessionGetArgs {
    #[arg(long)]
    pub session_id: String,
}

#[derive(Parser, Debug, Clone)]
pub struct AdminSessionForEventArgs {
    #[arg(long)]
    pub timeline: String,
    #[arg(long)]
    pub event_id: String,
}

#[derive(Subcommand, Debug, Clone)]
pub enum AdminTimelineSubcommands {
    Status(AdminTimelineStatusArgs),
    MissingImplementation(AdminMissingImplArgs),
}

#[derive(Parser, Debug, Clone)]
pub struct AdminTimelineArgs {
    #[command(subcommand)]
    pub command: AdminTimelineSubcommands,
}

#[derive(Parser, Debug, Clone)]
pub struct AdminTimelineStatusArgs {
    #[arg(long)]
    pub world: String,
    #[arg(long)]
    pub timeline: String,
}

#[derive(Parser, Debug, Clone)]
pub struct AdminMissingImplArgs {
    #[arg(long)]
    pub world: String,
    #[arg(long)]
    pub timeline: String,
    #[arg(long)]
    pub work_id: String,
}

#[derive(Subcommand, Debug, Clone)]
pub enum AdminWorkSubcommands {
    Terminalize(AdminTerminalizeArgs),
}

#[derive(Parser, Debug, Clone)]
pub struct AdminWorkArgs {
    #[command(subcommand)]
    pub command: AdminWorkSubcommands,
}

#[derive(Parser, Debug, Clone)]
pub struct AdminTerminalizeArgs {
    #[arg(long)]
    pub world: String,
    #[arg(long)]
    pub timeline: String,
    #[arg(long)]
    pub work_id: String,
    #[arg(long)]
    pub expected_head_seq: u64,
    #[arg(long)]
    pub expected_state_rev: u64,
    #[arg(long, default_value = "dead")]
    pub terminal_state: String,
    #[arg(long)]
    pub request_file: Option<PathBuf>,
    #[arg(long)]
    pub request_json: Option<String>,
}

#[derive(Subcommand, Debug, Clone)]
pub enum AdminAgencySubcommands {
    ScheduleWake(AdminScheduleWakeArgs),
}

#[derive(Parser, Debug, Clone)]
pub struct AdminAgencyArgs {
    #[command(subcommand)]
    pub command: AdminAgencySubcommands,
}

#[derive(Parser, Debug, Clone)]
pub struct AdminScheduleWakeArgs {
    #[arg(long)]
    pub file: Option<PathBuf>,
    #[arg(long)]
    pub json: Option<String>,
    #[arg(long)]
    pub world: Option<String>,
    #[arg(long)]
    pub timeline: Option<String>,
    #[arg(long)]
    pub work_id: Option<String>,
    #[arg(long)]
    pub agent: Option<String>,
    #[arg(long)]
    pub cognition: Option<String>,
    #[arg(long)]
    pub payload: Option<String>,
    #[arg(long)]
    pub payload_file: Option<PathBuf>,
}

#[derive(Subcommand, Debug, Clone)]
pub enum AdminWorldTimeSubcommands {
    Advance(AdminAdvanceWorldTimeArgs),
}

#[derive(Parser, Debug, Clone)]
pub struct AdminWorldTimeArgs {
    #[command(subcommand)]
    pub command: AdminWorldTimeSubcommands,
}

#[derive(Parser, Debug, Clone)]
pub struct AdminAdvanceWorldTimeArgs {
    #[arg(long)]
    pub world: String,
    #[arg(long)]
    pub timeline: String,
    #[arg(long)]
    pub expected_head_seq: u64,
    #[arg(long)]
    pub expected_state_rev: u64,
    #[arg(long)]
    pub current: i64,
    #[arg(long)]
    pub next: i64,
    #[arg(long)]
    pub request_file: Option<PathBuf>,
    #[arg(long)]
    pub request_json: Option<String>,
}

/// Exit code mapping for ApiErrorCode.
#[must_use]
pub fn exit_code_for_api_error(code: ApiErrorCode) -> i32 {
    match code {
        ApiErrorCode::InvalidRequest => 10,
        ApiErrorCode::NotFound => 11,
        ApiErrorCode::Conflict => 12,
        ApiErrorCode::Unavailable => 13,
        ApiErrorCode::Unauthorized => 14,
        ApiErrorCode::Forbidden => 15,
        ApiErrorCode::Internal => 16,
    }
}

/// Build a LoomClient from global CLI options.
pub fn build_client(cli: &Cli) -> Result<LoomClient, String> {
    let mut builder = ClientBuilder::new(cli.server.clone());
    if let Some(token) = &cli.bearer_token {
        builder = builder
            .bearer_token(token)
            .map_err(|e| format!("invalid bearer token: {e}"))?;
    }
    if let Some(token) = &cli.admin_token {
        builder = builder
            .admin_token(token)
            .map_err(|e| format!("invalid admin token: {e}"))?;
    }
    if cli.timeout_secs == 0 {
        builder = builder.no_timeout();
    } else {
        builder = builder.timeout(Duration::from_secs(cli.timeout_secs));
    }
    builder
        .build()
        .map_err(|e| format!("client build failed: {e}"))
}

/// Print a serializable value according to output mode.
pub fn print_output<T: Serialize>(value: &T, mode: OutputMode) -> Result<(), String> {
    let out = if mode.is_json() {
        serde_json::to_string(value).map_err(|e| format!("serialization failed: {e}"))?
    } else {
        serde_json::to_string_pretty(value).map_err(|e| format!("serialization failed: {e}"))?
    };
    println!("{out}");
    Ok(())
}

/// Print an ApiError to stderr as structured JSON and return its exit code.
pub fn print_api_error(error: &ApiError, mode: OutputMode) -> i32 {
    let code = exit_code_for_api_error(error.code);
    let payload = serde_json::json!({
        "code": error.code.to_string(),
        "message": error.message,
    });
    let text = if mode.is_json() {
        serde_json::to_string(&payload).unwrap_or_else(|_| format!("{payload:?}"))
    } else {
        serde_json::to_string_pretty(&payload).unwrap_or_else(|_| format!("{payload:?}"))
    };
    eprintln!("{text}");
    code
}

fn parse_world_id(s: &str) -> Result<WorldId, String> {
    WorldId::from_str(s).map_err(|e| format!("invalid WorldId '{s}': {e}"))
}

fn parse_timeline_id(s: &str) -> Result<TimelineId, String> {
    TimelineId::from_str(s).map_err(|e| format!("invalid TimelineId '{s}': {e}"))
}

fn parse_entity_id(s: &str) -> Result<EntityId, String> {
    EntityId::from_str(s).map_err(|e| format!("invalid EntityId '{s}': {e}"))
}

fn parse_relationship_id(s: &str) -> Result<RelationshipId, String> {
    RelationshipId::from_str(s).map_err(|e| format!("invalid RelationshipId '{s}': {e}"))
}

fn parse_event_id(s: &str) -> Result<EventId, String> {
    EventId::from_str(s).map_err(|e| format!("invalid EventId '{s}': {e}"))
}

fn parse_world_timeline(world: &str, timeline: &str) -> Result<TimelineTarget, String> {
    Ok(TimelineTarget::new(
        parse_world_id(world)?,
        parse_timeline_id(timeline)?,
    ))
}

fn read_json_file<T>(path: &PathBuf) -> Result<T, String>
where
    T: serde::de::DeserializeOwned,
{
    let data = fs::read_to_string(path).map_err(|e| format!("read {}: {e}", path.display()))?;
    serde_json::from_str(&data).map_err(|e| format!("parse {}: {e}", path.display()))
}

#[allow(dead_code)]
fn parse_json_arg<T>(inline: Option<&String>, file: Option<&PathBuf>) -> Result<Option<T>, String>
where
    T: serde::de::DeserializeOwned,
{
    match (inline, file) {
        (Some(s), None) => {
            let v: T = serde_json::from_str(s).map_err(|e| format!("invalid inline JSON: {e}"))?;
            Ok(Some(v))
        }
        (None, Some(p)) => Ok(Some(read_json_file(p)?)),
        (None, None) => Ok(None),
        (Some(_), Some(_)) => Err("specify only one of inline JSON or file".to_string()),
    }
}

// Individual command handlers

async fn handle_catalog(
    client: &LoomClient,
    args: &CatalogArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    if let Some(world_id) = &args.world_id {
        let wid = parse_world_id(world_id).map_err(ApiError::invalid_request)?;
        let snapshot = client.catalog_for_world(wid).await?;
        print_output(&snapshot, mode).map_err(ApiError::internal)?;
    } else {
        let snapshot = client.catalog()?;
        print_output(&snapshot, mode).map_err(ApiError::internal)?;
    }
    Ok(())
}

async fn handle_world_create(
    client: &LoomClient,
    args: &WorldCreateArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let request: CreateWorldFromTemplateRequest = if let Some(path) = &args.request_file {
        read_json_file::<CreateWorldFromTemplateRequest>(path).map_err(ApiError::invalid_request)?
    } else if let Some(inline) = &args.template_json {
        // Try as CreateWorldFromTemplateRequest first, then as WorldTemplateDescriptor
        if let Ok(req) = serde_json::from_str::<CreateWorldFromTemplateRequest>(inline) {
            req
        } else {
            let descriptor: loom_api::WorldTemplateDescriptor = serde_json::from_str(inline)
                .map_err(|e| ApiError::invalid_request(format!("invalid template JSON: {e}")))?;
            CreateWorldFromTemplateRequest::new(descriptor)
        }
    } else if let Some(path) = &args.template_file {
        let descriptor: loom_api::WorldTemplateDescriptor =
            read_json_file(path).map_err(ApiError::invalid_request)?;
        CreateWorldFromTemplateRequest::new(descriptor)
    } else {
        return Err(ApiError::invalid_request(
            "world create requires --template-file, --template-json, --request-file",
        ));
    };

    let result = client.create_world_from_template(request).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_timeline_inspect(
    client: &LoomClient,
    args: &TimelineInspectArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let target =
        parse_world_timeline(&args.world, &args.timeline).map_err(ApiError::invalid_request)?;
    let snapshot = client.inspect_timeline(target).await?;
    print_output(&snapshot, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_timeline_fork(
    client: &LoomClient,
    args: &TimelineForkArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let request = if let Some(path) = &args.request_file {
        read_json_file::<loom_api::ForkTimelineRequest>(path).map_err(ApiError::invalid_request)?
    } else if let Some(inline) = &args.request_json {
        serde_json::from_str::<loom_api::ForkTimelineRequest>(inline)
            .map_err(|e| ApiError::invalid_request(format!("invalid fork request JSON: {e}")))?
    } else {
        let source =
            parse_world_timeline(&args.world, &args.timeline).map_err(ApiError::invalid_request)?;
        if let Some(sv) = &args.source_version {
            // Try parse as JSON TimelineVersion
            let version: TimelineVersion = if sv.contains('{') {
                serde_json::from_str(sv).map_err(|e| {
                    ApiError::invalid_request(format!("invalid source_version JSON: {e}"))
                })?
            } else if sv.contains(':') {
                let parts: Vec<_> = sv.split(':').collect();
                if parts.len() != 2 {
                    return Err(ApiError::invalid_request(
                        "source_version expected as head_seq:state_rev",
                    ));
                }
                let head_seq: u64 = parts[0]
                    .parse()
                    .map_err(|_| ApiError::invalid_request("invalid head_event_seq"))?;
                let state_rev: u64 = parts[1]
                    .parse()
                    .map_err(|_| ApiError::invalid_request("invalid state_revision"))?;
                TimelineVersion::new(EventSeq::new(head_seq), StateRevision::new(state_rev))
            } else {
                return Err(ApiError::invalid_request(
                    "source_version must be JSON or head_seq:state_rev",
                ));
            };
            loom_api::ForkTimelineRequest::at_version(source, version)
        } else {
            loom_api::ForkTimelineRequest::new(source)
        }
    };
    let result = client.fork(request).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_action_invoke(
    client: &LoomClient,
    args: &ActionInvokeArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let request = if let Some(path) = &args.request_file {
        read_json_file::<ActionRequest>(path).map_err(ApiError::invalid_request)?
    } else if let Some(inline) = &args.request_json {
        serde_json::from_str::<ActionRequest>(inline)
            .map_err(|e| ApiError::invalid_request(format!("invalid ActionRequest JSON: {e}")))?
    } else {
        let world = args.world.clone();
        let timeline = args.timeline.clone();
        if world.is_empty() || timeline.is_empty() {
            return Err(ApiError::invalid_request(
                "action invoke requires --world and --timeline",
            ));
        }
        let target = parse_world_timeline(&world, &timeline).map_err(ApiError::invalid_request)?;
        let action = args
            .action
            .clone()
            .ok_or_else(|| ApiError::invalid_request("missing --action"))?;
        let input_value = if let Some(path) = &args.input_file {
            let data = fs::read_to_string(path)
                .map_err(|e| ApiError::invalid_request(format!("read input file: {e}")))?;
            serde_json::from_str::<serde_json::Value>(&data)
                .map_err(|e| ApiError::invalid_request(format!("invalid input file JSON: {e}")))?
        } else if let Some(inp) = &args.input {
            serde_json::from_str::<serde_json::Value>(inp)
                .map_err(|e| ApiError::invalid_request(format!("invalid --input JSON: {e}")))?
        } else {
            serde_json::Value::Object(serde_json::Map::new())
        };
        let invocation = loom_api::ActionInvocation::new(ActionTypeId::from(action), input_value);
        ActionRequest::new(target, invocation)
    };
    let result = client.invoke(request).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_facet_get(
    client: &LoomClient,
    args: &FacetGetArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let query = if let Some(path) = &args.request_file {
        read_json_file::<FacetQuery>(path).map_err(ApiError::invalid_request)?
    } else if let Some(inline) = &args.request_json {
        serde_json::from_str::<FacetQuery>(inline)
            .map_err(|e| ApiError::invalid_request(format!("invalid FacetQuery JSON: {e}")))?
    } else {
        let target =
            parse_world_timeline(&args.world, &args.timeline).map_err(ApiError::invalid_request)?;
        let facet_type = FacetTypeId::from(args.facet_type.clone());
        let owner = match args.owner_kind.as_str() {
            "entity" => {
                let eid = parse_entity_id(&args.owner).map_err(ApiError::invalid_request)?;
                FacetOwner::entity(eid)
            }
            "relationship" => {
                let rid = parse_relationship_id(&args.owner).map_err(ApiError::invalid_request)?;
                FacetOwner::relationship(rid)
            }
            other => {
                return Err(ApiError::invalid_request(format!(
                    "unknown owner_kind '{other}', expected entity or relationship"
                )));
            }
        };
        FacetQuery::new(target, owner, facet_type)
    };
    let result = client.get_facet(query).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_history_events(
    client: &LoomClient,
    args: &HistoryEventsArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let query = if let Some(path) = &args.request_file {
        read_json_file::<EventQuery>(path).map_err(ApiError::invalid_request)?
    } else if let Some(inline) = &args.request_json {
        serde_json::from_str::<EventQuery>(inline)
            .map_err(|e| ApiError::invalid_request(format!("invalid EventQuery JSON: {e}")))?
    } else {
        let target =
            parse_world_timeline(&args.world, &args.timeline).map_err(ApiError::invalid_request)?;
        EventQuery {
            target,
            after: args.after.map(EventSeq::new),
            limit: args.limit,
        }
    };
    let page = client.list_events_page(query).await?;
    print_output(&page, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_history_event(
    client: &LoomClient,
    args: &HistoryEventArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let event_ref = if let Some(path) = &args.request_file {
        let r: EventRef = read_json_file(path).map_err(ApiError::invalid_request)?;
        r
    } else if let Some(inline) = &args.request_json {
        serde_json::from_str::<EventRef>(inline)
            .map_err(|e| ApiError::invalid_request(format!("invalid EventRef JSON: {e}")))?
    } else if let Some(er) = &args.event_ref {
        // Try JSON first, then "timeline:uuid/event:uuid" or just event id with world/timeline
        if er.contains('{') {
            serde_json::from_str::<EventRef>(er)
                .map_err(|e| ApiError::invalid_request(format!("invalid event_ref JSON: {e}")))?
        } else if er.contains('/') {
            let parts: Vec<_> = er.split('/').collect();
            if parts.len() != 2 {
                return Err(ApiError::invalid_request(
                    "event_ref expected as timeline_id/event_id",
                ));
            }
            let tid = parse_timeline_id(parts[0]).map_err(ApiError::invalid_request)?;
            let eid = parse_event_id(parts[1]).map_err(ApiError::invalid_request)?;
            EventRef::new(tid, eid)
        } else {
            return Err(ApiError::invalid_request(
                "event_ref requires timeline and event_id",
            ));
        }
    } else {
        let timeline = args
            .timeline
            .clone()
            .ok_or_else(|| ApiError::invalid_request("missing --timeline"))?;
        let event_id = args
            .event_id
            .clone()
            .ok_or_else(|| ApiError::invalid_request("missing --event-id"))?;
        let tid = parse_timeline_id(&timeline).map_err(ApiError::invalid_request)?;
        let eid = parse_event_id(&event_id).map_err(ApiError::invalid_request)?;
        EventRef::new(tid, eid)
    };
    // For HistoryEvent, we need to handle legacy --world param unused but validate if present
    if let Some(world) = &args.world {
        let _ = parse_world_id(world).map_err(ApiError::invalid_request)?;
    }
    let result = client.get_event(event_ref).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_history_causes(
    client: &LoomClient,
    args: &HistoryCausesArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let tid = parse_timeline_id(&args.timeline).map_err(ApiError::invalid_request)?;
    let eid = parse_event_id(&args.event_id).map_err(ApiError::invalid_request)?;
    let r = EventRef::new(tid, eid);
    let result = client.direct_causes(r).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_history_effects(
    client: &LoomClient,
    args: &HistoryEffectsArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let tid = parse_timeline_id(&args.timeline).map_err(ApiError::invalid_request)?;
    let eid = parse_event_id(&args.event_id).map_err(ApiError::invalid_request)?;
    let r = EventRef::new(tid, eid);
    let result = client.direct_effects(r).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_history_walk(
    client: &LoomClient,
    args: &HistoryWalkArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let query = if let Some(path) = &args.request_file {
        read_json_file::<CausalQuery>(path).map_err(ApiError::invalid_request)?
    } else if let Some(inline) = &args.request_json {
        serde_json::from_str::<CausalQuery>(inline)
            .map_err(|e| ApiError::invalid_request(format!("invalid CausalQuery JSON: {e}")))?
    } else {
        let tid = parse_timeline_id(&args.timeline).map_err(ApiError::invalid_request)?;
        let eid = parse_event_id(&args.event_id).map_err(ApiError::invalid_request)?;
        let direction = match args.direction.as_str() {
            "causes" => CausalDirection::Causes,
            "effects" => CausalDirection::Effects,
            other => {
                return Err(ApiError::invalid_request(format!(
                    "unknown direction '{other}'"
                )));
            }
        };
        CausalQuery::new(
            EventRef::new(tid, eid),
            direction,
            args.max_depth,
            args.limit,
        )
    };
    let result = client.causal_walk(query).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_trajectory_entity(
    client: &LoomClient,
    args: &TrajectoryEntityArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let query = if let Some(path) = &args.request_file {
        read_json_file::<EntityTrajectoryQuery>(path).map_err(ApiError::invalid_request)?
    } else if let Some(inline) = &args.request_json {
        serde_json::from_str::<EntityTrajectoryQuery>(inline).map_err(|e| {
            ApiError::invalid_request(format!("invalid EntityTrajectoryQuery JSON: {e}"))
        })?
    } else {
        let target =
            parse_world_timeline(&args.world, &args.timeline).map_err(ApiError::invalid_request)?;
        let eid = parse_entity_id(&args.entity_id).map_err(ApiError::invalid_request)?;
        EntityTrajectoryQuery {
            target,
            entity_id: eid,
            after: args.after.map(EventSeq::new),
            limit: args.limit,
        }
    };
    let result = client.entity_trajectory(query).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_trajectory_relationship(
    client: &LoomClient,
    args: &TrajectoryRelationshipArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let query = if let Some(path) = &args.request_file {
        read_json_file::<RelationshipTrajectoryQuery>(path).map_err(ApiError::invalid_request)?
    } else if let Some(inline) = &args.request_json {
        serde_json::from_str::<RelationshipTrajectoryQuery>(inline).map_err(|e| {
            ApiError::invalid_request(format!("invalid RelationshipTrajectoryQuery JSON: {e}"))
        })?
    } else {
        let target =
            parse_world_timeline(&args.world, &args.timeline).map_err(ApiError::invalid_request)?;
        let rid =
            parse_relationship_id(&args.relationship_id).map_err(ApiError::invalid_request)?;
        RelationshipTrajectoryQuery {
            target,
            relationship_id: rid,
            after: args.after.map(EventSeq::new),
            limit: args.limit,
        }
    };
    let result = client.relationship_trajectory(query).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_feed_subscribe(
    client: &LoomClient,
    args: &FeedSubscribeArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let request = if let Some(path) = &args.request_file {
        read_json_file::<loom_api::SubscriptionRequest>(path).map_err(ApiError::invalid_request)?
    } else if let Some(inline) = &args.request_json {
        serde_json::from_str::<loom_api::SubscriptionRequest>(inline).map_err(|e| {
            ApiError::invalid_request(format!("invalid SubscriptionRequest JSON: {e}"))
        })?
    } else {
        let target =
            parse_world_timeline(&args.world, &args.timeline).map_err(ApiError::invalid_request)?;
        if let Some(after) = args.after {
            let cursor = ChangeFeedCursor::after(target, EventSeq::new(after));
            loom_api::SubscriptionRequest::resume(target, cursor, args.limit)
        } else {
            loom_api::SubscriptionRequest::new(target, args.limit)
        }
    };
    let result = client.subscribe(request).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_ingress_submit(
    client: &LoomClient,
    args: &IngressSubmitArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let envelope = if let Some(path) = &args.file {
        read_json_file::<IngressEnvelope>(path).map_err(ApiError::invalid_request)?
    } else if let Some(inline) = &args.json {
        serde_json::from_str::<IngressEnvelope>(inline)
            .map_err(|e| ApiError::invalid_request(format!("invalid IngressEnvelope JSON: {e}")))?
    } else {
        // Build from convenience fields
        let ingress_id = args
            .ingress_id
            .clone()
            .ok_or_else(|| ApiError::invalid_request("missing --ingress-id"))?;
        let idempotency_key = args
            .idempotency_key
            .clone()
            .unwrap_or_else(|| ingress_id.clone());
        let world = args
            .world
            .clone()
            .ok_or_else(|| ApiError::invalid_request("missing --world"))?;
        let timeline = args
            .timeline
            .clone()
            .ok_or_else(|| ApiError::invalid_request("missing --timeline"))?;
        let target = parse_world_timeline(&world, &timeline).map_err(ApiError::invalid_request)?;
        let action = args
            .action
            .clone()
            .ok_or_else(|| ApiError::invalid_request("missing --action"))?;
        let input_value = if let Some(path) = &args.input_file {
            let data = fs::read_to_string(path)
                .map_err(|e| ApiError::invalid_request(format!("read input file: {e}")))?;
            serde_json::from_str::<serde_json::Value>(&data)
                .map_err(|e| ApiError::invalid_request(format!("invalid input file JSON: {e}")))?
        } else if let Some(inp) = &args.input {
            serde_json::from_str::<serde_json::Value>(inp)
                .map_err(|e| ApiError::invalid_request(format!("invalid --input JSON: {e}")))?
        } else {
            serde_json::Value::Object(serde_json::Map::new())
        };
        let invocation = loom_api::ActionInvocation::new(ActionTypeId::from(action), input_value);
        let provenance = if let Some(source) = &args.source {
            loom_api::IngressProvenance::new(source.clone())
        } else {
            loom_api::IngressProvenance::new("cli")
        };
        IngressEnvelope::new(
            IngressId::from(ingress_id),
            loom_api::IdempotencyKey::from(idempotency_key),
            provenance,
            target,
            loom_api::IngressAuthorizationContext::new(serde_json::json!({})),
            loom_api::IngressTimeMetadata::none(),
            invocation,
        )
    };
    let result = client.submit_ingress(envelope).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_ingress_status(
    client: &LoomClient,
    args: &IngressStatusArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let id = IngressId::from(args.ingress_id.clone());
    let result = client.ingress_status(id).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

// Admin handlers

async fn handle_admin_revision_active(
    client: &LoomClient,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let result = client.active_runtime_revision().await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_admin_revision_list(client: &LoomClient, mode: OutputMode) -> Result<(), ApiError> {
    let result = client.list_runtime_revisions().await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_admin_revision_get(
    client: &LoomClient,
    args: &AdminRevisionGetArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let req = AdminRuntimeRevisionRequest {
        revision_id: args.revision_id.clone(),
    };
    let result = client.get_runtime_revision(req).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_admin_revision_activate(
    client: &LoomClient,
    args: &AdminRevisionActivateArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let request = if let Some(path) = &args.request_file {
        read_json_file::<AdminActivateRuntimeRevisionRequest>(path)
            .map_err(ApiError::invalid_request)?
    } else if let Some(inline) = &args.request_json {
        serde_json::from_str::<AdminActivateRuntimeRevisionRequest>(inline)
            .map_err(|e| ApiError::invalid_request(format!("invalid activate request JSON: {e}")))?
    } else {
        AdminActivateRuntimeRevisionRequest {
            revision_id: args.revision_id.clone(),
            expected_generation: args.expected_generation,
        }
    };
    let result = client.activate_runtime_revision(request).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_admin_session_list(client: &LoomClient, mode: OutputMode) -> Result<(), ApiError> {
    let result = client.list_execution_sessions().await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_admin_session_get(
    client: &LoomClient,
    args: &AdminSessionGetArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let session_id = ExecutionSessionId::from_str(&args.session_id)
        .map_err(|e| ApiError::invalid_request(format!("invalid session_id: {e}")))?;
    let req = AdminExecutionSessionRequest { session_id };
    let result = client.get_execution_session(req).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_admin_session_for_event(
    client: &LoomClient,
    args: &AdminSessionForEventArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let tid = parse_timeline_id(&args.timeline).map_err(ApiError::invalid_request)?;
    let eid = parse_event_id(&args.event_id).map_err(ApiError::invalid_request)?;
    let r = EventRef::new(tid, eid);
    let result = client.session_for_event(r).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_admin_timeline_status(
    client: &LoomClient,
    args: &AdminTimelineStatusArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let target =
        parse_world_timeline(&args.world, &args.timeline).map_err(ApiError::invalid_request)?;
    let result = client.timeline_logical_status(target).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_admin_missing_impl(
    client: &LoomClient,
    args: &AdminMissingImplArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let target =
        parse_world_timeline(&args.world, &args.timeline).map_err(ApiError::invalid_request)?;
    let work_id = WorkId::from_str(&args.work_id)
        .map_err(|e| ApiError::invalid_request(format!("invalid work_id: {e}")))?;
    let req = AdminMissingImplementationRequest { target, work_id };
    let result = client.missing_implementation(req).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_admin_terminalize(
    client: &LoomClient,
    args: &AdminTerminalizeArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let request = if let Some(path) = &args.request_file {
        read_json_file::<AdminTerminalizeWorkRequest>(path).map_err(ApiError::invalid_request)?
    } else if let Some(inline) = &args.request_json {
        serde_json::from_str::<AdminTerminalizeWorkRequest>(inline)
            .map_err(|e| ApiError::invalid_request(format!("invalid terminalize JSON: {e}")))?
    } else {
        let target =
            parse_world_timeline(&args.world, &args.timeline).map_err(ApiError::invalid_request)?;
        let work_id = WorkId::from_str(&args.work_id)
            .map_err(|e| ApiError::invalid_request(format!("invalid work_id: {e}")))?;
        let expected_version = TimelineVersion::new(
            EventSeq::new(args.expected_head_seq),
            StateRevision::new(args.expected_state_rev),
        );
        let terminal_state = match args.terminal_state.as_str() {
            "dead" => AdminTerminalWorkState::Dead,
            "cancelled" => AdminTerminalWorkState::Cancelled,
            other => {
                return Err(ApiError::invalid_request(format!(
                    "unknown terminal_state '{other}'"
                )));
            }
        };
        AdminTerminalizeWorkRequest {
            target,
            work_id,
            expected_version,
            terminal_state,
        }
    };
    let result = client.terminalize_work(request).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_admin_schedule_wake(
    client: &LoomClient,
    args: &AdminScheduleWakeArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let request = if let Some(path) = &args.file {
        read_json_file::<AdminScheduleAgencyWakeRequest>(path).map_err(ApiError::invalid_request)?
    } else if let Some(inline) = &args.json {
        serde_json::from_str::<AdminScheduleAgencyWakeRequest>(inline)
            .map_err(|e| ApiError::invalid_request(format!("invalid agency wake JSON: {e}")))?
    } else {
        let world = args
            .world
            .clone()
            .ok_or_else(|| ApiError::invalid_request("missing --world"))?;
        let timeline = args
            .timeline
            .clone()
            .ok_or_else(|| ApiError::invalid_request("missing --timeline"))?;
        let target = parse_world_timeline(&world, &timeline).map_err(ApiError::invalid_request)?;
        let work_id = args
            .work_id
            .clone()
            .ok_or_else(|| ApiError::invalid_request("missing --work-id"))?;
        let work_id = WorkId::from_str(&work_id)
            .map_err(|e| ApiError::invalid_request(format!("invalid work_id: {e}")))?;
        let agent = args
            .agent
            .clone()
            .ok_or_else(|| ApiError::invalid_request("missing --agent"))?;
        let agent = parse_entity_id(&agent).map_err(ApiError::invalid_request)?;
        let cognition = args
            .cognition
            .clone()
            .unwrap_or_else(|| "test.cognition".to_string());
        let payload = if let Some(path) = &args.payload_file {
            let data = fs::read_to_string(path)
                .map_err(|e| ApiError::invalid_request(format!("read payload file: {e}")))?;
            serde_json::from_str::<serde_json::Value>(&data)
                .map_err(|e| ApiError::invalid_request(format!("invalid payload file JSON: {e}")))?
        } else if let Some(p) = &args.payload {
            serde_json::from_str::<serde_json::Value>(p)
                .map_err(|e| ApiError::invalid_request(format!("invalid --payload JSON: {e}")))?
        } else {
            serde_json::json!({})
        };
        // Need expected_version and schedule – for minimal, use default version and immediate schedule
        // If not supplied, we try to get timeline status to infer current version, but for now require explicit file for complex case.
        // Fallback to using a dummy expected version (0,0) – server will reject with conflict if wrong, which maps correctly.
        let expected_version = TimelineVersion::new(EventSeq::new(0), StateRevision::new(0));
        let schedule = loom_api::WorkSchedule::Immediate;
        AdminScheduleAgencyWakeRequest {
            target,
            expected_version,
            work_id,
            agent,
            cognition,
            payload,
            schedule,
        }
    };
    let result = client.schedule_agency_wake(request).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

async fn handle_admin_advance_world_time(
    client: &LoomClient,
    args: &AdminAdvanceWorldTimeArgs,
    mode: OutputMode,
) -> Result<(), ApiError> {
    let request = if let Some(path) = &args.request_file {
        read_json_file::<AdminAdvanceWorldTimeRequest>(path).map_err(ApiError::invalid_request)?
    } else if let Some(inline) = &args.request_json {
        serde_json::from_str::<AdminAdvanceWorldTimeRequest>(inline)
            .map_err(|e| ApiError::invalid_request(format!("invalid advance request JSON: {e}")))?
    } else {
        let target =
            parse_world_timeline(&args.world, &args.timeline).map_err(ApiError::invalid_request)?;
        let expected_version = TimelineVersion::new(
            EventSeq::new(args.expected_head_seq),
            StateRevision::new(args.expected_state_rev),
        );
        AdminAdvanceWorldTimeRequest {
            target,
            expected_version,
            current: WorldInstant::new(args.current),
            next: WorldInstant::new(args.next),
        }
    };
    let result = client.advance_world_time(request).await?;
    print_output(&result, mode).map_err(ApiError::internal)?;
    Ok(())
}

/// Execute the CLI and return an exit code.
#[allow(clippy::too_many_lines)]
pub async fn execute(cli: Cli) -> i32 {
    let mode = cli.output;
    let client = match build_client(&cli) {
        Ok(c) => c,
        Err(msg) => {
            eprintln!(
                "{}",
                serde_json::json!({"code":"invalid_request","message":msg})
            );
            return 10;
        }
    };

    let result: Result<(), ApiError> = match cli.command {
        Commands::Catalog(args) => handle_catalog(&client, &args, mode).await,
        Commands::World(args) => match args.command {
            WorldCommands::Create(c) => handle_world_create(&client, &c, mode).await,
        },
        Commands::Timeline(args) => match args.command {
            TimelineCommands::Inspect(c) => handle_timeline_inspect(&client, &c, mode).await,
            TimelineCommands::Fork(c) => handle_timeline_fork(&client, &c, mode).await,
        },
        Commands::Action(args) => match args.command {
            ActionCommands::Invoke(c) => handle_action_invoke(&client, &c, mode).await,
        },
        Commands::Facet(args) => match args.command {
            FacetCommands::Get(c) => handle_facet_get(&client, &c, mode).await,
        },
        Commands::History(args) => match args.command {
            HistoryCommands::Events(c) => handle_history_events(&client, &c, mode).await,
            HistoryCommands::Event(c) => handle_history_event(&client, &c, mode).await,
            HistoryCommands::Causes(c) => handle_history_causes(&client, &c, mode).await,
            HistoryCommands::Effects(c) => handle_history_effects(&client, &c, mode).await,
            HistoryCommands::Walk(c) => handle_history_walk(&client, &c, mode).await,
        },
        Commands::Trajectory(args) => match args.command {
            TrajectoryCommands::Entity(c) => handle_trajectory_entity(&client, &c, mode).await,
            TrajectoryCommands::Relationship(c) => {
                handle_trajectory_relationship(&client, &c, mode).await
            }
        },
        Commands::Feed(args) => match args.command {
            FeedCommands::Subscribe(c) | FeedCommands::Tail(c) => {
                handle_feed_subscribe(&client, &c, mode).await
            }
        },
        Commands::Ingress(args) => match args.command {
            IngressCommands::Submit(c) => handle_ingress_submit(&client, &c, mode).await,
            IngressCommands::Status(c) => handle_ingress_status(&client, &c, mode).await,
        },
        Commands::Admin(args) => match args.command {
            AdminCommands::Revision(c) => match c.command {
                AdminRevisionSubcommands::Active => {
                    handle_admin_revision_active(&client, mode).await
                }
                AdminRevisionSubcommands::List => handle_admin_revision_list(&client, mode).await,
                AdminRevisionSubcommands::Get(c) => {
                    handle_admin_revision_get(&client, &c, mode).await
                }
                AdminRevisionSubcommands::Activate(c) => {
                    handle_admin_revision_activate(&client, &c, mode).await
                }
            },
            AdminCommands::Session(c) => match c.command {
                AdminSessionSubcommands::List => handle_admin_session_list(&client, mode).await,
                AdminSessionSubcommands::Get(c) => {
                    handle_admin_session_get(&client, &c, mode).await
                }
                AdminSessionSubcommands::ForEvent(c) => {
                    handle_admin_session_for_event(&client, &c, mode).await
                }
            },
            AdminCommands::Timeline(c) => match c.command {
                AdminTimelineSubcommands::Status(c) => {
                    handle_admin_timeline_status(&client, &c, mode).await
                }
                AdminTimelineSubcommands::MissingImplementation(c) => {
                    handle_admin_missing_impl(&client, &c, mode).await
                }
            },
            AdminCommands::Work(c) => match c.command {
                AdminWorkSubcommands::Terminalize(c) => {
                    handle_admin_terminalize(&client, &c, mode).await
                }
            },
            AdminCommands::Agency(c) => match c.command {
                AdminAgencySubcommands::ScheduleWake(c) => {
                    handle_admin_schedule_wake(&client, &c, mode).await
                }
            },
            AdminCommands::WorldTime(c) => match c.command {
                AdminWorldTimeSubcommands::Advance(c) => {
                    handle_admin_advance_world_time(&client, &c, mode).await
                }
            },
        },
    };

    match result {
        Ok(()) => 0,
        Err(e) => print_api_error(&e, mode),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn exit_code_mapping_distinct() {
        assert_eq!(exit_code_for_api_error(ApiErrorCode::InvalidRequest), 10);
        assert_eq!(exit_code_for_api_error(ApiErrorCode::NotFound), 11);
        assert_eq!(exit_code_for_api_error(ApiErrorCode::Conflict), 12);
        assert_eq!(exit_code_for_api_error(ApiErrorCode::Unavailable), 13);
        assert_eq!(exit_code_for_api_error(ApiErrorCode::Unauthorized), 14);
        assert_eq!(exit_code_for_api_error(ApiErrorCode::Forbidden), 15);
        assert_eq!(exit_code_for_api_error(ApiErrorCode::Internal), 16);
    }

    #[test]
    fn catalog_args_parsing() {
        let cli = Cli::try_parse_from(["loom", "catalog"]).expect("catalog should parse");
        match cli.command {
            Commands::Catalog(args) => assert!(args.world_id.is_none()),
            _ => panic!("expected catalog"),
        }
    }

    #[test]
    fn catalog_world_id_parsing() {
        let cli = Cli::try_parse_from([
            "loom",
            "catalog",
            "--world-id",
            "00000000-0000-0000-0000-000000000001",
        ])
        .expect("catalog with world should parse");
        match cli.command {
            Commands::Catalog(args) => assert_eq!(
                args.world_id,
                Some("00000000-0000-0000-0000-000000000001".to_string())
            ),
            _ => panic!("expected catalog"),
        }
    }

    #[test]
    fn build_client_rejects_invalid_url() {
        let cli = Cli {
            server: "not-a-url".to_string(),
            bearer_token: None,
            admin_token: None,
            output: OutputMode::Json,
            timeout_secs: 30,
            command: Commands::Catalog(CatalogArgs { world_id: None }),
        };
        let res = build_client(&cli);
        assert!(res.is_err());
    }
}
