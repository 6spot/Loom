//! Runtime-owned gateway from a pinned Agency view to cognition.
//!
//! This module is deliberately value-only at the Agency boundary. Runtime
//! pins the executor metadata and policy in the Execution Assembly, mediates
//! the context `ReadSet`, and records the typed result in Execution Provenance.
//! No provider client, World read port or mutation authority crosses the SPI.

use std::{error::Error, fmt, sync::Arc};

use loom_agency::{
    AgentWorldView, CognitiveError, CognitiveExecutor, CognitiveMetadata, CognitiveRequest,
    ContextBudgetUsage, Decision,
};

use crate::{
    CognitiveDisposition, CognitiveObservation, CognitiveOutcome, ExecutionAssembly,
    ExecutionEvidence, PinnedReadSession,
};

/// Runtime-owned technical errors around the Agency cognition boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CognitiveGatewayError {
    /// The evidence envelope belongs to another pinned entropy source.
    EvidenceSourceMismatch,
    /// The supplied view or read session is not the pinned Assembly coordinate.
    PinnedContextMismatch {
        /// Coordinate field that differed.
        field: String,
        /// Coordinate pinned by the Session/Assembly.
        expected: String,
        /// Coordinate supplied by the caller.
        actual: String,
    },
    /// The Agency Wake requirement does not match the pinned executor.
    CognitiveRequirementMismatch {
        /// Stable requirement carried by the Agency Wake target.
        requirement: String,
        /// Executor identity pinned in the Execution Assembly.
        pinned: String,
    },
    /// The selected context exceeds the pinned Agency context budget.
    ContextBudgetExceeded {
        /// Budget dimension that exceeded its pinned limit.
        dimension: String,
        /// Pinned maximum.
        limit: u64,
        /// Measured usage.
        actual: u64,
    },
    /// The injected executor changed identity after the Assembly was pinned.
    ExecutorMetadataChanged {
        /// Metadata pinned into the Execution Assembly.
        expected: Box<CognitiveMetadata>,
        /// Metadata returned by the injected executor at invocation time.
        actual: Box<CognitiveMetadata>,
    },
    /// The executor returned a typed technical failure.
    Executor(CognitiveError),
}

impl fmt::Display for CognitiveGatewayError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EvidenceSourceMismatch => {
                formatter.write_str("cognitive evidence belongs to another entropy source")
            }
            Self::PinnedContextMismatch {
                field,
                expected,
                actual,
            } => write!(
                formatter,
                "cognitive context {field} mismatch: expected {expected}, got {actual}"
            ),
            Self::CognitiveRequirementMismatch {
                requirement,
                pinned,
            } => write!(
                formatter,
                "cognitive requirement {requirement} does not match pinned executor {pinned}"
            ),
            Self::ContextBudgetExceeded {
                dimension,
                limit,
                actual,
            } => write!(
                formatter,
                "cognitive context {dimension} budget exceeded: {actual} > {limit}"
            ),
            Self::ExecutorMetadataChanged { expected, actual } => write!(
                formatter,
                "cognitive executor metadata changed after pin: expected {expected:?}, got {actual:?}"
            ),
            Self::Executor(error) => error.fmt(formatter),
        }
    }
}

impl Error for CognitiveGatewayError {}

impl From<CognitiveError> for CognitiveGatewayError {
    fn from(error: CognitiveError) -> Self {
        Self::Executor(error)
    }
}

/// Explicit unconfigured executor used by the Runtime default composition.
///
/// Agency Wake admission can report this as missing compatible cognition; it
/// never pretends that an absent provider produced `NoAction`.
#[derive(Clone, Copy, Debug, Default)]
pub struct UnavailableCognitiveExecutor;

impl CognitiveExecutor for UnavailableCognitiveExecutor {
    fn metadata(&self) -> CognitiveMetadata {
        CognitiveMetadata::new(loom_agency::ExecutorMetadata::new("unconfigured", "0"))
    }

    fn execute<'a>(&'a self, _request: &'a CognitiveRequest) -> loom_agency::CognitiveFuture<'a> {
        Box::pin(async {
            Err(CognitiveError::unavailable(
                "no cognitive executor was configured",
            ))
        })
    }
}

/// Invokes one pinned executor and records its result into Session evidence.
pub(crate) async fn execute_cognitive(
    executor: &dyn CognitiveExecutor,
    assembly: &ExecutionAssembly,
    session: &PinnedReadSession,
    view: AgentWorldView,
    evidence: &mut ExecutionEvidence,
) -> Result<Decision, CognitiveGatewayError> {
    validate_coordinate(assembly, session, &view)?;
    validate_budget(
        &assembly.cognitive().policy().context_budget,
        view.context.usage,
    )?;
    if evidence.entropy_evidence.source_id() != assembly.entropy_source_id() {
        return Err(CognitiveGatewayError::EvidenceSourceMismatch);
    }

    let pinned_metadata = assembly.cognitive().metadata().clone();
    let actual_metadata = executor.metadata();
    if actual_metadata != pinned_metadata {
        return Err(CognitiveGatewayError::ExecutorMetadataChanged {
            expected: Box::new(pinned_metadata),
            actual: Box::new(actual_metadata),
        });
    }

    let context_read_set = session.read_set();
    evidence.read_set.extend(context_read_set.clone());
    let request = CognitiveRequest::new(view.clone(), assembly.cognitive().policy().clone());
    let result = executor.execute(&request).await;
    let outcome = match &result {
        Ok(Decision::Act(_)) => CognitiveOutcome::Act,
        Ok(Decision::NoAction) => CognitiveOutcome::NoAction,
        Err(error) => CognitiveOutcome::Error(error.clone()),
    };
    evidence.cognitive_evidence.record(CognitiveObservation {
        ordinal: 0,
        metadata: pinned_metadata,
        policy: assembly.cognitive().policy().clone(),
        agent: view.agent,
        timeline_id: view.timeline_id,
        version: view.version,
        world_time: view.world_time,
        context_usage: view.context.usage,
        context_read_set,
        outcome,
        disposition: CognitiveDisposition::Fresh,
    });
    result.map_err(CognitiveGatewayError::Executor)
}

/// Records an explicitly reusable decision after Runtime rebuilt the
/// subjective context at a fresh Timeline coordinate.
///
/// No executor is called here. The caller must have selected
/// `DecisionReusePolicy::ReuseDeterministic`; this function still repeats the
/// gateway coordinate, budget and executor metadata checks so a reused result
/// cannot bypass the pinned Agency boundary.
pub(crate) fn record_reused_cognitive(
    executor: &dyn CognitiveExecutor,
    assembly: &ExecutionAssembly,
    session: &PinnedReadSession,
    view: AgentWorldView,
    decision: &Decision,
    evidence: &mut ExecutionEvidence,
) -> Result<(), CognitiveGatewayError> {
    validate_coordinate(assembly, session, &view)?;
    validate_budget(
        &assembly.cognitive().policy().context_budget,
        view.context.usage,
    )?;
    if evidence.entropy_evidence.source_id() != assembly.entropy_source_id() {
        return Err(CognitiveGatewayError::EvidenceSourceMismatch);
    }
    let pinned_metadata = assembly.cognitive().metadata().clone();
    let actual_metadata = executor.metadata();
    if actual_metadata != pinned_metadata {
        return Err(CognitiveGatewayError::ExecutorMetadataChanged {
            expected: Box::new(pinned_metadata),
            actual: Box::new(actual_metadata),
        });
    }
    let context_read_set = session.read_set();
    evidence.read_set.extend(context_read_set.clone());
    let outcome = match decision {
        Decision::Act(_) => CognitiveOutcome::Act,
        Decision::NoAction => CognitiveOutcome::NoAction,
    };
    evidence.cognitive_evidence.record(CognitiveObservation {
        ordinal: 0,
        metadata: assembly.cognitive().metadata().clone(),
        policy: assembly.cognitive().policy().clone(),
        agent: view.agent,
        timeline_id: view.timeline_id,
        version: view.version,
        world_time: view.world_time,
        context_usage: view.context.usage,
        context_read_set,
        outcome,
        disposition: CognitiveDisposition::Reused,
    });
    Ok(())
}

fn validate_coordinate(
    assembly: &ExecutionAssembly,
    session: &PinnedReadSession,
    view: &AgentWorldView,
) -> Result<(), CognitiveGatewayError> {
    for (field, expected, actual) in [
        (
            "session_id",
            assembly.session_id().to_string(),
            session.session_id().to_string(),
        ),
        (
            "world_id",
            assembly.world_id().to_string(),
            session.world_id().to_string(),
        ),
        (
            "timeline_id",
            assembly.timeline_id().to_string(),
            session.timeline_id().to_string(),
        ),
        (
            "version",
            format!("{:?}", assembly.expected_version()),
            format!("{:?}", session.version()),
        ),
        (
            "world_time",
            format!("{:?}", assembly.world_time()),
            format!("{:?}", session.world_time()),
        ),
        (
            "view.timeline_id",
            assembly.timeline_id().to_string(),
            view.timeline_id.to_string(),
        ),
        (
            "view.version",
            format!("{:?}", assembly.expected_version()),
            format!("{:?}", view.version),
        ),
        (
            "view.world_time",
            format!("{:?}", assembly.world_time()),
            format!("{:?}", view.world_time),
        ),
    ] {
        if expected != actual {
            return Err(CognitiveGatewayError::PinnedContextMismatch {
                field: field.to_owned(),
                expected,
                actual,
            });
        }
    }
    Ok(())
}

fn validate_budget(
    budget: &loom_agency::ContextBudget,
    usage: ContextBudgetUsage,
) -> Result<(), CognitiveGatewayError> {
    for (dimension, limit, actual) in [
        (
            "entries",
            u64::from(budget.max_entries),
            u64::from(usage.entries),
        ),
        ("bytes", budget.max_bytes, usage.bytes),
        (
            "entities",
            u64::from(budget.max_entities),
            u64::from(usage.entities),
        ),
        (
            "relationships",
            u64::from(budget.max_relationships),
            u64::from(usage.relationships),
        ),
        (
            "events",
            u64::from(budget.max_events),
            u64::from(usage.events),
        ),
        (
            "semantic_results",
            u64::from(budget.max_semantic_results),
            u64::from(usage.semantic_results),
        ),
        ("depth", u64::from(budget.max_depth), u64::from(usage.depth)),
        (
            "semantic_queries",
            u64::from(budget.max_semantic_queries),
            u64::from(usage.semantic_queries),
        ),
    ] {
        if actual > limit {
            return Err(CognitiveGatewayError::ContextBudgetExceeded {
                dimension: dimension.to_owned(),
                limit,
                actual,
            });
        }
    }
    Ok(())
}

/// Type-erased cognition dependency retained by Runtime composition.
pub(crate) type CognitiveExecutorHandle = Arc<dyn CognitiveExecutor + Send + Sync>;

#[cfg(test)]
mod tests {
    use std::{future::Future, str::FromStr};

    use loom_agency::{
        AgentContextSnapshot, AgentRef, CognitiveError, CognitiveMetadata, ContextBudget,
        ContextBudgetUsage, DeterministicCognitiveExecutor, DeterministicCognitiveStep,
        ExecutionPolicy, ExecutorMetadata,
    };
    use loom_core::{
        EntityId, EventSeq, StateRevision, TimelineId, TimelineVersion, WorldId, WorldInstant,
    };
    use loom_protocol::ActionInvocation;
    use semver::Version;

    use super::*;
    use crate::{
        CognitiveAssembly, EntropySourceId, ExecutionAssembly, RuntimeRevisionDescriptor,
        RuntimeRevisionId, RuntimeRevisionSelection, WorldRuntimeBinding,
    };

    fn id<T>(value: u128) -> T
    where
        T: FromStr,
        T::Err: std::fmt::Debug,
    {
        format!("00000000-0000-0000-0000-{value:012x}")
            .parse()
            .expect("test identity should parse")
    }

    fn block_on<F: Future>(future: F) -> F::Output {
        let mut future = Box::pin(future);
        let waker = std::task::Waker::noop();
        let mut context = std::task::Context::from_waker(waker);
        loop {
            match future.as_mut().poll(&mut context) {
                std::task::Poll::Ready(value) => return value,
                std::task::Poll::Pending => std::thread::yield_now(),
            }
        }
    }

    fn assembly(metadata: CognitiveMetadata) -> ExecutionAssembly {
        let world_id = id::<WorldId>(1);
        let timeline_id = id::<TimelineId>(2);
        let session_id = id::<loom_core::ExecutionSessionId>(3);
        let binding = WorldRuntimeBinding::new([], serde_json::json!({}), 1, None);
        let revision = RuntimeRevisionDescriptor::new(
            RuntimeRevisionId::from("cognitive-test-revision"),
            crate::PlatformTime::default(),
            "cognitive-test-build",
            Version::new(0, 1, 0),
            [],
        )
        .expect("empty test revision should be valid");
        let implementations = revision
            .compatible_with(&binding)
            .expect("empty test binding should be compatible");
        ExecutionAssembly::new(
            session_id,
            world_id,
            timeline_id,
            TimelineVersion::new(EventSeq::new(2), StateRevision::new(1)),
            WorldInstant::new(7),
            binding,
            RuntimeRevisionSelection::new(revision, 1, crate::PlatformTime::default()),
            implementations,
            crate::ResolutionBudget::unlimited(),
            EntropySourceId::from("cognitive-test-entropy"),
        )
        .with_cognitive(CognitiveAssembly::new(
            metadata,
            ExecutionPolicy::new("cognitive-test-policy", "1", ContextBudget::default()),
        ))
    }

    fn view(assembly: &ExecutionAssembly) -> AgentWorldView {
        AgentWorldView::new(
            AgentRef::new(id::<EntityId>(10)),
            assembly.timeline_id(),
            assembly.expected_version(),
            assembly.world_time(),
            AgentContextSnapshot::new(Vec::new(), ContextBudgetUsage::new(0, 0)),
        )
    }

    #[test]
    fn gateway_records_distinct_no_action_and_technical_failure() {
        let metadata = CognitiveMetadata::new(ExecutorMetadata::new("cognitive.fake", "1"));
        let assembly = assembly(metadata.clone());
        let session = PinnedReadSession::new(
            assembly.session_id(),
            assembly.world_id(),
            assembly.timeline_id(),
            assembly.expected_version(),
            assembly.world_time(),
        );
        let fake = DeterministicCognitiveExecutor::with_metadata(
            metadata,
            [
                DeterministicCognitiveStep::no_action(),
                DeterministicCognitiveStep::technical_failure(CognitiveError::failed(
                    "scripted provider failure",
                )),
            ],
        );
        let mut evidence = ExecutionEvidence::new(assembly.entropy_source_id().clone());

        assert!(matches!(
            block_on(execute_cognitive(
                &fake,
                &assembly,
                &session,
                view(&assembly),
                &mut evidence,
            )),
            Ok(Decision::NoAction)
        ));
        assert!(matches!(
            block_on(execute_cognitive(
                &fake,
                &assembly,
                &session,
                view(&assembly),
                &mut evidence,
            )),
            Err(CognitiveGatewayError::Executor(
                CognitiveError::Failed { .. }
            ))
        ));
        assert_eq!(evidence.cognitive_evidence.len(), 2);
        assert!(matches!(
            evidence.cognitive_evidence.observations()[0].outcome,
            CognitiveOutcome::NoAction
        ));
        assert!(matches!(
            evidence.cognitive_evidence.observations()[1].outcome,
            CognitiveOutcome::Error(CognitiveError::Failed { .. })
        ));
        let finished = crate::ExecutionSession::new(
            assembly.session_id(),
            crate::ExecutionOrigin::Runtime,
            assembly.clone(),
            crate::PlatformTime::new(1),
        )
        .finish_with_evidence(
            crate::ExecutionSessionStatus::Failed,
            crate::PlatformTime::new(2),
            evidence,
        )
        .expect("Session should retain cognition evidence");
        assert_eq!(finished.cognitive_evidence().len(), 2);
    }

    #[test]
    fn gateway_preserves_restricted_view_and_deterministic_delay() {
        let metadata = CognitiveMetadata::new(ExecutorMetadata::new("cognitive.fake", "1"));
        let assembly = assembly(metadata.clone());
        let session = PinnedReadSession::new(
            assembly.session_id(),
            assembly.world_id(),
            assembly.timeline_id(),
            assembly.expected_version(),
            assembly.world_time(),
        );
        let fake = DeterministicCognitiveExecutor::with_metadata(
            metadata,
            [DeterministicCognitiveStep::act(ActionInvocation::new(
                "cognitive.action".into(),
                serde_json::json!({"value": 1}),
            ))
            .with_delay_polls(2)],
        );
        let mut evidence = ExecutionEvidence::new(assembly.entropy_source_id().clone());
        let decision = block_on(execute_cognitive(
            &fake,
            &assembly,
            &session,
            view(&assembly),
            &mut evidence,
        ))
        .expect("scripted Action should be returned");
        assert!(matches!(decision, Decision::Act(_)));
        let request = &fake.requests()[0];
        assert_eq!(request.view.context.entries.len(), 0);
        assert_eq!(request.policy.policy_id, "cognitive-test-policy");
        assert_eq!(
            evidence.cognitive_evidence.observations()[0]
                .context_read_set
                .len(),
            0
        );
    }
}
