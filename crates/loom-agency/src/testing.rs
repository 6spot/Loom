//! Deterministic cognition implementations for composition and integration tests.
//!
//! The fake deliberately implements the production [`CognitiveExecutor`] SPI.
//! It records only cloned Agency requests, has no World or Runtime handle, and
//! can make a scripted result pending for a deterministic number of polls.

use std::{
    collections::VecDeque,
    future::Future,
    pin::Pin,
    sync::Mutex,
    task::{Context, Poll},
};

use crate::{
    CognitiveError, CognitiveExecutor, CognitiveFuture, CognitiveMetadata, CognitiveRequest,
    CognitiveResult, Decision, ExecutorMetadata,
};
use loom_protocol::ActionInvocation;

/// One scripted result returned by [`DeterministicCognitiveExecutor`].
#[derive(Clone, Debug, PartialEq)]
pub enum DeterministicCognitiveOutcome {
    /// Return an untrusted Action proposal through the normal Agency SPI.
    Act(ActionInvocation),
    /// Return the typed determined no-op result.
    NoAction,
    /// Return a typed technical cognition failure.
    TechnicalFailure(CognitiveError),
}

impl DeterministicCognitiveOutcome {
    /// Creates an `Act` script step.
    #[must_use]
    pub fn act(invocation: ActionInvocation) -> Self {
        Self::Act(invocation)
    }

    /// Creates a `NoAction` script step.
    #[must_use]
    pub const fn no_action() -> Self {
        Self::NoAction
    }

    /// Creates a technical failure script step.
    #[must_use]
    pub fn technical_failure(error: CognitiveError) -> Self {
        Self::TechnicalFailure(error)
    }

    fn into_result(self) -> CognitiveResult {
        match self {
            Self::Act(invocation) => Ok(Decision::Act(invocation)),
            Self::NoAction => Ok(Decision::NoAction),
            Self::TechnicalFailure(error) => Err(error),
        }
    }
}

/// One deterministic fake invocation script entry.
#[derive(Clone, Debug, PartialEq)]
pub struct DeterministicCognitiveStep {
    /// Result returned after the configured poll delay.
    pub outcome: DeterministicCognitiveOutcome,
    /// Number of polls for which the future remains pending before returning.
    pub delay_polls: usize,
}

impl DeterministicCognitiveStep {
    /// Creates an immediate script step.
    #[must_use]
    pub fn new(outcome: DeterministicCognitiveOutcome) -> Self {
        Self {
            outcome,
            delay_polls: 0,
        }
    }

    /// Creates an `Act` step.
    #[must_use]
    pub fn act(invocation: ActionInvocation) -> Self {
        Self::new(DeterministicCognitiveOutcome::act(invocation))
    }

    /// Creates a `NoAction` step.
    #[must_use]
    pub fn no_action() -> Self {
        Self::new(DeterministicCognitiveOutcome::no_action())
    }

    /// Creates a technical failure step.
    #[must_use]
    pub fn technical_failure(error: CognitiveError) -> Self {
        Self::new(DeterministicCognitiveOutcome::technical_failure(error))
    }

    /// Adds a deterministic number of pending polls to this step.
    #[must_use]
    pub const fn with_delay_polls(mut self, delay_polls: usize) -> Self {
        self.delay_polls = delay_polls;
        self
    }

    /// Alias for [`Self::with_delay_polls`] used by CAS-focused tests.
    #[must_use]
    pub const fn delayed(self, delay_polls: usize) -> Self {
        self.with_delay_polls(delay_polls)
    }

    /// Alias for [`Self::with_delay_polls`] for latency-oriented tests.
    #[must_use]
    pub const fn with_delay(self, delay_polls: usize) -> Self {
        self.with_delay_polls(delay_polls)
    }
}

impl From<Decision> for DeterministicCognitiveStep {
    fn from(decision: Decision) -> Self {
        match decision {
            Decision::Act(invocation) => Self::act(invocation),
            Decision::NoAction => Self::no_action(),
        }
    }
}

impl From<CognitiveError> for DeterministicCognitiveStep {
    fn from(error: CognitiveError) -> Self {
        Self::technical_failure(error)
    }
}

/// A deterministic, thread-safe scripted cognitive executor.
///
/// The script cursor and request log are the fake's test harness state; each
/// invocation still receives an immutable, value-only [`CognitiveRequest`].
/// No Action is executed by this type.
pub struct DeterministicCognitiveExecutor {
    metadata: CognitiveMetadata,
    script: Mutex<VecDeque<DeterministicCognitiveStep>>,
    requests: Mutex<Vec<CognitiveRequest>>,
}

impl std::fmt::Debug for DeterministicCognitiveExecutor {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("DeterministicCognitiveExecutor")
            .field("metadata", &self.metadata)
            .field("scripted_steps", &self.script_len())
            .field("calls", &self.calls())
            .finish_non_exhaustive()
    }
}

impl DeterministicCognitiveExecutor {
    /// Creates a fake with the default `deterministic.fake` metadata.
    #[must_use]
    pub fn new<I, T>(script: I) -> Self
    where
        I: IntoIterator<Item = T>,
        T: Into<DeterministicCognitiveStep>,
    {
        Self::with_metadata(
            CognitiveMetadata::new(ExecutorMetadata::new("deterministic.fake", "1")),
            script.into_iter().map(Into::into),
        )
    }

    /// Creates a fake with explicit audit-safe executor/provider/model metadata.
    #[must_use]
    pub fn with_metadata(
        metadata: CognitiveMetadata,
        script: impl IntoIterator<Item = DeterministicCognitiveStep>,
    ) -> Self {
        Self {
            metadata,
            script: Mutex::new(script.into_iter().collect()),
            requests: Mutex::new(Vec::new()),
        }
    }

    /// Appends a scripted invocation to the shared deterministic queue.
    pub fn push(&self, step: DeterministicCognitiveStep) {
        self.script
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .push_back(step);
    }

    /// Returns the number of requests accepted by this fake.
    #[must_use]
    pub fn calls(&self) -> usize {
        self.requests
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .len()
    }

    /// Returns cloned requests in invocation order for boundary assertions.
    #[must_use]
    pub fn requests(&self) -> Vec<CognitiveRequest> {
        self.requests
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .clone()
    }

    /// Returns the number of unconsumed scripted steps.
    #[must_use]
    pub fn script_len(&self) -> usize {
        self.script
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .len()
    }
}

struct DeterministicFuture {
    remaining_polls: usize,
    outcome: Option<DeterministicCognitiveOutcome>,
}

impl Future for DeterministicFuture {
    type Output = CognitiveResult;

    fn poll(mut self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Self::Output> {
        if self.remaining_polls != 0 {
            self.remaining_polls -= 1;
            context.waker().wake_by_ref();
            return Poll::Pending;
        }
        Poll::Ready(
            self.outcome
                .take()
                .expect("deterministic cognition future polled after completion")
                .into_result(),
        )
    }
}

impl CognitiveExecutor for DeterministicCognitiveExecutor {
    fn metadata(&self) -> CognitiveMetadata {
        self.metadata.clone()
    }

    fn execute<'a>(&'a self, request: &'a CognitiveRequest) -> CognitiveFuture<'a> {
        self.requests
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .push(request.clone());
        let step = self
            .script
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .pop_front()
            .unwrap_or_else(|| {
                DeterministicCognitiveStep::technical_failure(CognitiveError::failed(
                    "deterministic cognition script is exhausted",
                ))
            });
        Box::pin(DeterministicFuture {
            remaining_polls: step.delay_polls,
            outcome: Some(step.outcome),
        })
    }
}

#[cfg(test)]
mod tests {
    use std::{future::Future, task::Context};

    use loom_protocol::ActionInvocation;
    use serde_json::json;

    use super::*;

    fn block_on<F: Future>(future: F) -> F::Output {
        let mut future = Box::pin(future);
        let waker = std::task::Waker::noop();
        let mut context = Context::from_waker(waker);
        loop {
            match future.as_mut().poll(&mut context) {
                Poll::Ready(value) => return value,
                Poll::Pending => std::thread::yield_now(),
            }
        }
    }

    fn request() -> CognitiveRequest {
        CognitiveRequest::new(
            crate::AgentWorldView::new(
                crate::AgentRef::new(
                    "00000000-0000-0000-0000-000000000001"
                        .parse()
                        .expect("test Agent identity"),
                ),
                "00000000-0000-0000-0000-000000000002"
                    .parse()
                    .expect("test Timeline identity"),
                loom_core::TimelineVersion::default(),
                loom_core::WorldInstant::default(),
                crate::AgentContextSnapshot::default(),
            ),
            crate::ExecutionPolicy::default(),
        )
    }

    #[test]
    fn fake_scripts_typed_results_and_poll_delay() {
        let fake = DeterministicCognitiveExecutor::new([
            DeterministicCognitiveStep::no_action(),
            DeterministicCognitiveStep::act(ActionInvocation::new("test.act".into(), json!({})))
                .with_delay_polls(2),
            DeterministicCognitiveStep::technical_failure(CognitiveError::failed("technical")),
        ]);
        let request = request();

        assert_eq!(block_on(fake.execute(&request)), Ok(Decision::NoAction));
        assert!(matches!(
            block_on(fake.execute(&request)),
            Ok(Decision::Act(_))
        ));
        assert!(matches!(
            block_on(fake.execute(&request)),
            Err(CognitiveError::Failed { .. })
        ));
        assert_eq!(fake.calls(), 3);
        assert_eq!(fake.requests().len(), 3);
    }
}
