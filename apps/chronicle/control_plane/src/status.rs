//! Frozen status vocabularies and legal lifecycle transitions.
//!
//! Every vocabulary here mirrors a `PostgreSQL` `CHECK` constraint in migration
//! `0002_chronicle_c1_control_plane.sql`. Adding or removing a status is a
//! contract change: update the SQL, the Python store tables, and this module
//! together.

use std::fmt;

/// An illegal lifecycle transition attempt.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct IllegalTransition {
    /// Which entity kind was transitioned (`"job"`, `"stage"`, ...).
    pub kind: &'static str,
    /// The current status.
    pub from: &'static str,
    /// The rejected target status.
    pub to: &'static str,
}

impl fmt::Display for IllegalTransition {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "illegal {} transition: '{}' -> '{}'",
            self.kind, self.from, self.to
        )
    }
}

impl std::error::Error for IllegalTransition {}

/// Durable ingestion job status.
///
/// ```text
/// queued -> running -> {needs_review | failed | cancelled | completed}
/// needs_review -> running | failed | cancelled | completed
/// failed -> running (resume/retry) | cancelled
/// cancelled / completed are terminal.
/// ```
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum JobStatus {
    Queued,
    Running,
    NeedsReview,
    Failed,
    Cancelled,
    Completed,
}

impl JobStatus {
    /// All statuses in declaration order.
    #[must_use]
    pub const fn all() -> [Self; 6] {
        [
            Self::Queued,
            Self::Running,
            Self::NeedsReview,
            Self::Failed,
            Self::Cancelled,
            Self::Completed,
        ]
    }

    /// The stable wire/persistence string, frozen by C1-T1.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Queued => "queued",
            Self::Running => "running",
            Self::NeedsReview => "needs_review",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
            Self::Completed => "completed",
        }
    }

    /// Parse a persisted status string.
    ///
    /// # Errors
    ///
    /// Returns the unknown input when it is not part of the frozen vocabulary.
    pub fn parse(value: &str) -> Result<Self, &str> {
        match value {
            "queued" => Ok(Self::Queued),
            "running" => Ok(Self::Running),
            "needs_review" => Ok(Self::NeedsReview),
            "failed" => Ok(Self::Failed),
            "cancelled" => Ok(Self::Cancelled),
            "completed" => Ok(Self::Completed),
            unknown => Err(unknown),
        }
    }

    /// Whether `self -> target` is a legal job transition.
    #[must_use]
    pub fn can_transition_to(self, target: Self) -> bool {
        self.transition(target).is_ok()
    }

    /// Perform the transition, rejecting illegal moves.
    ///
    /// # Errors
    ///
    /// Returns [`IllegalTransition`] when `self -> target` is not legal.
    pub fn transition(self, target: Self) -> Result<Self, IllegalTransition> {
        let legal = match self {
            Self::Queued => matches!(target, Self::Running | Self::Cancelled),
            Self::Running => matches!(
                target,
                Self::NeedsReview | Self::Failed | Self::Cancelled | Self::Completed
            ),
            Self::NeedsReview => matches!(
                target,
                Self::Running | Self::Failed | Self::Cancelled | Self::Completed
            ),
            Self::Failed => matches!(target, Self::Running | Self::Cancelled),
            Self::Cancelled | Self::Completed => false,
        };
        if legal {
            Ok(target)
        } else {
            Err(IllegalTransition {
                kind: "job",
                from: self.as_str(),
                to: target.as_str(),
            })
        }
    }

    /// Whether the status ends the job lifecycle.
    #[must_use]
    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Failed | Self::Cancelled | Self::Completed)
    }
}

/// Initial pipeline stage vocabulary, frozen by C1-T1, in execution order.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Stage {
    Prepare,
    Structure,
    Segment,
    Extract,
    Assemble,
    Resolve,
    Publish,
    Present,
}

impl Stage {
    /// The pipeline in execution order.
    #[must_use]
    pub const fn pipeline() -> [Self; 8] {
        [
            Self::Prepare,
            Self::Structure,
            Self::Segment,
            Self::Extract,
            Self::Assemble,
            Self::Resolve,
            Self::Publish,
            Self::Present,
        ]
    }

    /// The stable persistence string, frozen by C1-T1.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Prepare => "prepare",
            Self::Structure => "structure",
            Self::Segment => "segment",
            Self::Extract => "extract",
            Self::Assemble => "assemble",
            Self::Resolve => "resolve",
            Self::Publish => "publish",
            Self::Present => "present",
        }
    }

    /// Parse a persisted stage string.
    ///
    /// # Errors
    ///
    /// Returns the unknown input when it is not part of the frozen vocabulary.
    pub fn parse(value: &str) -> Result<Self, &str> {
        match value {
            "prepare" => Ok(Self::Prepare),
            "structure" => Ok(Self::Structure),
            "segment" => Ok(Self::Segment),
            "extract" => Ok(Self::Extract),
            "assemble" => Ok(Self::Assemble),
            "resolve" => Ok(Self::Resolve),
            "publish" => Ok(Self::Publish),
            "present" => Ok(Self::Present),
            unknown => Err(unknown),
        }
    }
}

/// Per-stage execution status.
///
/// ```text
/// pending -> running | skipped
/// running -> needs_review | failed | skipped | completed
/// needs_review -> running | failed | skipped | completed
/// failed -> running | skipped
/// skipped -> running (re-run)
/// completed is terminal.
/// ```
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum StageStatus {
    Pending,
    Running,
    NeedsReview,
    Failed,
    Skipped,
    Completed,
}

impl StageStatus {
    /// The stable persistence string, frozen by C1-T1.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Running => "running",
            Self::NeedsReview => "needs_review",
            Self::Failed => "failed",
            Self::Skipped => "skipped",
            Self::Completed => "completed",
        }
    }

    /// Parse a persisted stage status string.
    ///
    /// # Errors
    ///
    /// Returns the unknown input when it is not part of the frozen vocabulary.
    pub fn parse(value: &str) -> Result<Self, &str> {
        match value {
            "pending" => Ok(Self::Pending),
            "running" => Ok(Self::Running),
            "needs_review" => Ok(Self::NeedsReview),
            "failed" => Ok(Self::Failed),
            "skipped" => Ok(Self::Skipped),
            "completed" => Ok(Self::Completed),
            unknown => Err(unknown),
        }
    }

    /// Perform the transition, rejecting illegal moves.
    ///
    /// # Errors
    ///
    /// Returns [`IllegalTransition`] when `self -> target` is not legal.
    pub fn transition(self, target: Self) -> Result<Self, IllegalTransition> {
        let legal = match self {
            Self::Pending => matches!(target, Self::Running | Self::Skipped),
            Self::Running => matches!(
                target,
                Self::NeedsReview | Self::Failed | Self::Skipped | Self::Completed
            ),
            Self::NeedsReview => matches!(
                target,
                Self::Running | Self::Failed | Self::Skipped | Self::Completed
            ),
            Self::Failed => matches!(target, Self::Running | Self::Skipped),
            Self::Skipped => matches!(target, Self::Running),
            Self::Completed => false,
        };
        if legal {
            Ok(target)
        } else {
            Err(IllegalTransition {
                kind: "stage",
                from: self.as_str(),
                to: target.as_str(),
            })
        }
    }
}

/// Chunk processing status.
///
/// Chunks are model-processing units, never historical identity authority.
/// ```text
/// pending -> processing -> {needs_review | failed | completed}
/// needs_review -> processing | failed | completed
/// failed -> processing (retry; the retry itself is a new chunk run)
/// completed is terminal.
/// ```
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ChunkStatus {
    Pending,
    Processing,
    NeedsReview,
    Failed,
    Completed,
}

impl ChunkStatus {
    /// The stable persistence string, frozen by C1-T1.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Processing => "processing",
            Self::NeedsReview => "needs_review",
            Self::Failed => "failed",
            Self::Completed => "completed",
        }
    }

    /// Perform the transition, rejecting illegal moves.
    ///
    /// # Errors
    ///
    /// Returns [`IllegalTransition`] when `self -> target` is not legal.
    pub fn transition(self, target: Self) -> Result<Self, IllegalTransition> {
        let legal = match self {
            Self::Pending | Self::Failed => matches!(target, Self::Processing),
            Self::Processing => {
                matches!(target, Self::NeedsReview | Self::Failed | Self::Completed)
            }
            Self::NeedsReview => {
                matches!(target, Self::Processing | Self::Failed | Self::Completed)
            }
            Self::Completed => false,
        };
        if legal {
            Ok(target)
        } else {
            Err(IllegalTransition {
                kind: "chunk",
                from: self.as_str(),
                to: target.as_str(),
            })
        }
    }
}

/// Chunk run (single attempt) status: `started -> succeeded | failed`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum RunStatus {
    Started,
    Succeeded,
    Failed,
}

impl RunStatus {
    /// The stable persistence string, frozen by C1-T1.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Started => "started",
            Self::Succeeded => "succeeded",
            Self::Failed => "failed",
        }
    }

    /// Perform the transition, rejecting illegal moves.
    ///
    /// # Errors
    ///
    /// Returns [`IllegalTransition`] when `self -> target` is not legal.
    pub fn transition(self, target: Self) -> Result<Self, IllegalTransition> {
        let legal = match self {
            Self::Started => matches!(target, Self::Succeeded | Self::Failed),
            Self::Succeeded | Self::Failed => false,
        };
        if legal {
            Ok(target)
        } else {
            Err(IllegalTransition {
                kind: "chunk run",
                from: self.as_str(),
                to: target.as_str(),
            })
        }
    }
}

/// Review item status: `open -> approved | rejected | superseded`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ReviewStatus {
    Open,
    Approved,
    Rejected,
    Superseded,
}

impl ReviewStatus {
    /// The stable persistence string, frozen by C1-T1.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Open => "open",
            Self::Approved => "approved",
            Self::Rejected => "rejected",
            Self::Superseded => "superseded",
        }
    }

    /// Perform the transition, rejecting illegal moves.
    ///
    /// # Errors
    ///
    /// Returns [`IllegalTransition`] when `self -> target` is not legal.
    pub fn transition(self, target: Self) -> Result<Self, IllegalTransition> {
        let legal = match self {
            Self::Open => matches!(target, Self::Approved | Self::Rejected | Self::Superseded),
            Self::Approved | Self::Rejected | Self::Superseded => false,
        };
        if legal {
            Ok(target)
        } else {
            Err(IllegalTransition {
                kind: "review",
                from: self.as_str(),
                to: target.as_str(),
            })
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn job_vocabulary_round_trips() {
        for status in JobStatus::all() {
            assert_eq!(JobStatus::parse(status.as_str()), Ok(status));
        }
        assert!(JobStatus::parse("archived").is_err());
    }

    #[test]
    fn stage_vocabulary_round_trips() {
        let pipeline = Stage::pipeline();
        assert_eq!(pipeline.len(), 8);
        for stage in pipeline {
            assert_eq!(Stage::parse(stage.as_str()), Ok(stage));
        }
        assert_eq!(
            pipeline.map(Stage::as_str),
            [
                "prepare",
                "structure",
                "segment",
                "extract",
                "assemble",
                "resolve",
                "publish",
                "present"
            ]
        );
        assert!(Stage::parse("transcribe").is_err());
    }

    #[test]
    fn job_happy_path_transitions() {
        let mut status = JobStatus::Queued;
        for next in [
            JobStatus::Running,
            JobStatus::NeedsReview,
            JobStatus::Running,
            JobStatus::Completed,
        ] {
            status = status.transition(next).expect("legal transition");
        }
        assert_eq!(status, JobStatus::Completed);
    }

    #[test]
    fn job_illegal_transitions_rejected() {
        // Skipping running.
        assert!(JobStatus::Queued.transition(JobStatus::Completed).is_err());
        // Moving backwards.
        assert!(JobStatus::Running.transition(JobStatus::Queued).is_err());
        // Terminal states are terminal.
        for terminal in [
            JobStatus::Failed,
            JobStatus::Cancelled,
            JobStatus::Completed,
        ] {
            for target in JobStatus::all() {
                if terminal == JobStatus::Failed
                    && matches!(target, JobStatus::Running | JobStatus::Cancelled)
                {
                    continue;
                }
                assert!(
                    terminal.transition(target).is_err(),
                    "{terminal:?} -> {target:?} should be illegal"
                );
            }
        }
        // Failed jobs resume through running, never straight to completed.
        assert!(JobStatus::Failed.transition(JobStatus::Completed).is_err());
        assert_eq!(
            JobStatus::Failed.transition(JobStatus::Running),
            Ok(JobStatus::Running)
        );
    }

    #[test]
    fn can_transition_to_agrees_with_transition() {
        for from in JobStatus::all() {
            for to in JobStatus::all() {
                assert_eq!(
                    from.can_transition_to(to),
                    from.transition(to).is_ok(),
                    "{from:?} -> {to:?}"
                );
            }
        }
    }

    #[test]
    fn stage_skip_and_rerun() {
        let status = StageStatus::Pending
            .transition(StageStatus::Skipped)
            .expect("pending -> skipped");
        let status = status
            .transition(StageStatus::Running)
            .expect("skipped -> running");
        assert_eq!(
            status.transition(StageStatus::Completed),
            Ok(StageStatus::Completed)
        );
        assert!(StageStatus::Pending
            .transition(StageStatus::Completed)
            .is_err());
        assert!(StageStatus::Completed
            .transition(StageStatus::Running)
            .is_err());
    }

    #[test]
    fn chunk_retry_loop() {
        let status = ChunkStatus::Pending
            .transition(ChunkStatus::Processing)
            .expect("pending -> processing");
        let status = status
            .transition(ChunkStatus::Failed)
            .expect("processing -> failed");
        let status = status
            .transition(ChunkStatus::Processing)
            .expect("failed -> processing (retry)");
        assert_eq!(
            status.transition(ChunkStatus::Completed),
            Ok(ChunkStatus::Completed)
        );
        assert!(ChunkStatus::Pending
            .transition(ChunkStatus::Completed)
            .is_err());
    }

    #[test]
    fn run_and_review_are_single_shot() {
        assert_eq!(
            RunStatus::Started.transition(RunStatus::Succeeded),
            Ok(RunStatus::Succeeded)
        );
        assert!(RunStatus::Succeeded.transition(RunStatus::Failed).is_err());
        assert_eq!(
            ReviewStatus::Open.transition(ReviewStatus::Approved),
            Ok(ReviewStatus::Approved)
        );
        assert!(ReviewStatus::Approved
            .transition(ReviewStatus::Rejected)
            .is_err());
    }
}
