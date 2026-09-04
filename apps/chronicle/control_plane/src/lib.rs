//! Chronicle C1-T1 ingestion control-plane contract.
//!
//! Pure domain state machines for durable document ingestion workflows:
//! [`JobStatus`], [`StageStatus`] (+ [`StageName`] pipeline vocabulary),
//! [`ChunkStatus`], [`ReviewKind`]/[`ReviewStatus`].
//!
//! This crate is normative for every legal lifecycle transition. The Python
//! persistence boundary (`apps/chronicle/persistence/control_plane.py`)
//! mirrors these tables; when they disagree, this crate wins.
//!
//! Application-owned product logic only (Architecture Amendment 0006):
//! no Loom Runtime/World/Timeline/Work/Binding authority, no `loom-storage`
//! dependency, no SQL, no DB driver. Persistence lives in the Chronicle
//! PostgreSQL migration `0002_chronicle_c1_control_plane.sql` behind
//! `CHRONICLE_DATABASE_URL`.

#![forbid(unsafe_code)]

use core::fmt;

/// Error for a rejected lifecycle transition.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct IllegalTransition {
    /// Entity kind, e.g. `"job"`, `"stage"`, `"chunk"`.
    pub kind: &'static str,
    /// Transition that was attempted, e.g. `"queued -> completed"`.
    pub attempted: (&'static str, &'static str),
}

impl fmt::Display for IllegalTransition {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "illegal {} transition: {} -> {}",
            self.kind, self.attempted.0, self.attempted.1
        )
    }
}

/// Durable ingestion job status (frozen by C1-T1).
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
    /// Canonical wire/persistence spelling.
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

    /// Parse the canonical spelling; unknown spellings are rejected.
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "queued" => Some(Self::Queued),
            "running" => Some(Self::Running),
            "needs_review" => Some(Self::NeedsReview),
            "failed" => Some(Self::Failed),
            "cancelled" => Some(Self::Cancelled),
            "completed" => Some(Self::Completed),
            _ => None,
        }
    }

    /// Terminal states accept no further transition.
    #[must_use]
    pub const fn is_terminal(self) -> bool {
        matches!(self, Self::Failed | Self::Cancelled | Self::Completed)
    }

    /// Legal outgoing edges. Self-transitions (idempotent worker retries of
    /// the same status write) are accepted by [`Self::transition`] directly.
    #[must_use]
    pub fn can_transition_to(self, next: Self) -> bool {
        if self == next {
            return true;
        }
        matches!(
            (self, next),
            (Self::Queued, Self::Running | Self::Cancelled)
                | (
                    Self::Running,
                    Self::NeedsReview | Self::Failed | Self::Cancelled | Self::Completed,
                )
                | (
                    Self::NeedsReview,
                    Self::Running | Self::Failed | Self::Cancelled
                )
        )
    }

    /// Validate one transition step.
    pub fn transition(self, next: Self) -> Result<Self, IllegalTransition> {
        if self.can_transition_to(next) {
            Ok(next)
        } else {
            Err(IllegalTransition {
                kind: "job",
                attempted: (self.as_str(), next.as_str()),
            })
        }
    }
}

/// Initial C1-T1 pipeline stage vocabulary.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum StageName {
    Prepare,
    Structure,
    Segment,
    Extract,
    Assemble,
    Resolve,
    Publish,
    Present,
}

impl StageName {
    /// Canonical spelling, also used as the persistence key.
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

    /// Canonical pipeline order.
    pub const ALL_IN_ORDER: [Self; 8] = [
        Self::Prepare,
        Self::Structure,
        Self::Segment,
        Self::Extract,
        Self::Assemble,
        Self::Resolve,
        Self::Publish,
        Self::Present,
    ];
}

/// Pipeline stage status.
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

    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "pending" => Some(Self::Pending),
            "running" => Some(Self::Running),
            "needs_review" => Some(Self::NeedsReview),
            "failed" => Some(Self::Failed),
            "skipped" => Some(Self::Skipped),
            "completed" => Some(Self::Completed),
            _ => None,
        }
    }

    #[must_use]
    pub fn can_transition_to(self, next: Self) -> bool {
        if self == next {
            return true;
        }
        matches!(
            (self, next),
            (Self::Pending, Self::Running | Self::Skipped)
                | (
                    Self::Running,
                    Self::NeedsReview | Self::Failed | Self::Completed | Self::Skipped,
                )
                | (
                    Self::NeedsReview,
                    Self::Running | Self::Failed | Self::Skipped
                )
                | (Self::Failed, Self::Running)
        )
    }

    pub fn transition(self, next: Self) -> Result<Self, IllegalTransition> {
        if self.can_transition_to(next) {
            Ok(next)
        } else {
            Err(IllegalTransition {
                kind: "stage",
                attempted: (self.as_str(), next.as_str()),
            })
        }
    }
}

/// Chunk processing status. Chunks are processing units, never historical
/// identity/truth boundaries.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ChunkStatus {
    Pending,
    Running,
    NeedsReview,
    Failed,
    Completed,
}

impl ChunkStatus {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Running => "running",
            Self::NeedsReview => "needs_review",
            Self::Failed => "failed",
            Self::Completed => "completed",
        }
    }

    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "pending" => Some(Self::Pending),
            "running" => Some(Self::Running),
            "needs_review" => Some(Self::NeedsReview),
            "failed" => Some(Self::Failed),
            "completed" => Some(Self::Completed),
            _ => None,
        }
    }

    #[must_use]
    pub fn can_transition_to(self, next: Self) -> bool {
        if self == next {
            return true;
        }
        matches!(
            (self, next),
            (Self::Pending, Self::Running)
                | (
                    Self::Running,
                    Self::NeedsReview | Self::Failed | Self::Completed,
                )
                | (Self::NeedsReview, Self::Running | Self::Failed)
                | (Self::Failed, Self::Running)
        )
    }

    pub fn transition(self, next: Self) -> Result<Self, IllegalTransition> {
        if self.can_transition_to(next) {
            Ok(next)
        } else {
            Err(IllegalTransition {
                kind: "chunk",
                attempted: (self.as_str(), next.as_str()),
            })
        }
    }
}

/// Human review gate kind.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ReviewKind {
    ChunkFailure,
    StageGate,
    QualityFlag,
}

impl ReviewKind {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::ChunkFailure => "chunk_failure",
            Self::StageGate => "stage_gate",
            Self::QualityFlag => "quality_flag",
        }
    }
}

/// Human review item status.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ReviewStatus {
    Open,
    Resolved,
    Dismissed,
}

impl ReviewStatus {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Open => "open",
            Self::Resolved => "resolved",
            Self::Dismissed => "dismissed",
        }
    }

    /// Only open items accept a resolution; resolved history is append-only.
    #[must_use]
    pub const fn can_resolve(self) -> bool {
        matches!(self, Self::Open)
    }
}

/// Replacement/supersession rule: replacing a source creates a new immutable
/// revision; it never destructively overwrites the old uploaded source.
/// Returns the next revision number for a document whose current tip is
/// `current_tip` (`None` when the document has no revision yet).
#[must_use]
pub const fn next_revision_no(current_tip: Option<u32>) -> u32 {
    match current_tip {
        None => 1,
        Some(n) => n + 1,
    }
}

#[cfg(test)]
mod status_tests {
    use super::*;

    #[test]
    fn job_status_round_trips_through_canonical_spelling() {
        for status in [
            JobStatus::Queued,
            JobStatus::Running,
            JobStatus::NeedsReview,
            JobStatus::Failed,
            JobStatus::Cancelled,
            JobStatus::Completed,
        ] {
            assert_eq!(JobStatus::parse(status.as_str()), Some(status));
        }
        assert_eq!(JobStatus::parse("bogus"), None);
    }

    #[test]
    fn job_terminal_states_reject_every_outgoing_transition() {
        for terminal in [
            JobStatus::Failed,
            JobStatus::Cancelled,
            JobStatus::Completed,
        ] {
            assert!(terminal.is_terminal());
            for candidate in [
                JobStatus::Queued,
                JobStatus::Running,
                JobStatus::NeedsReview,
                JobStatus::Failed,
                JobStatus::Cancelled,
                JobStatus::Completed,
            ] {
                if candidate != terminal {
                    assert!(
                        !terminal.can_transition_to(candidate),
                        "{terminal:?} -> {candidate:?} must be illegal"
                    );
                }
            }
        }
        assert!(!JobStatus::Queued.is_terminal());
        assert!(!JobStatus::Running.is_terminal());
        assert!(!JobStatus::NeedsReview.is_terminal());
    }

    #[test]
    fn job_happy_path_and_review_resume_are_legal() {
        assert!(JobStatus::Queued.can_transition_to(JobStatus::Running));
        assert!(JobStatus::Running.can_transition_to(JobStatus::NeedsReview));
        assert!(JobStatus::NeedsReview.can_transition_to(JobStatus::Running));
        assert!(JobStatus::Running.can_transition_to(JobStatus::Completed));
        assert!(JobStatus::Queued.can_transition_to(JobStatus::Cancelled));
        assert!(JobStatus::Running.can_transition_to(JobStatus::Failed));
    }

    #[test]
    fn job_illegal_jumps_are_rejected() {
        // Queued work cannot skip straight to a terminal/review state.
        for illegal in [
            JobStatus::NeedsReview,
            JobStatus::Failed,
            JobStatus::Completed,
        ] {
            assert!(JobStatus::Queued.transition(illegal).is_err());
        }
        // Review cannot complete directly; it must resume first.
        assert!(JobStatus::NeedsReview
            .transition(JobStatus::Completed)
            .is_err());
        // Completed work is terminal: no restart, no review.
        assert!(JobStatus::Completed.transition(JobStatus::Running).is_err());
        assert!(JobStatus::Completed.transition(JobStatus::Queued).is_err());
    }

    #[test]
    fn stage_names_cover_the_frozen_pipeline_vocabulary_in_order() {
        let names: Vec<&str> = StageName::ALL_IN_ORDER
            .iter()
            .map(|s| StageName::as_str(*s))
            .collect();
        assert_eq!(
            names,
            vec![
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
    }

    #[test]
    fn stage_failed_can_retry_but_completed_is_terminal() {
        assert!(StageStatus::Failed.can_transition_to(StageStatus::Running));
        assert!(!StageStatus::Completed.can_transition_to(StageStatus::Running));
        assert!(!StageStatus::Skipped.can_transition_to(StageStatus::Running));
        assert!(StageStatus::Pending.can_transition_to(StageStatus::Skipped));
        assert!(StageStatus::Running.can_transition_to(StageStatus::Completed));
        assert!(StageStatus::Pending
            .transition(StageStatus::Completed)
            .is_err());
    }

    #[test]
    fn chunk_failed_can_retry_and_review_can_resume() {
        assert!(ChunkStatus::Failed.can_transition_to(ChunkStatus::Running));
        assert!(ChunkStatus::NeedsReview.can_transition_to(ChunkStatus::Running));
        assert!(ChunkStatus::Running.can_transition_to(ChunkStatus::Completed));
        assert!(!ChunkStatus::Completed.can_transition_to(ChunkStatus::Running));
        assert!(ChunkStatus::Pending
            .transition(ChunkStatus::Completed)
            .is_err());
    }

    #[test]
    fn review_items_resolve_exactly_once() {
        assert!(ReviewStatus::Open.can_resolve());
        assert!(!ReviewStatus::Resolved.can_resolve());
        assert!(!ReviewStatus::Dismissed.can_resolve());
        assert_eq!(ReviewKind::ChunkFailure.as_str(), "chunk_failure");
        assert_eq!(ReviewKind::StageGate.as_str(), "stage_gate");
        assert_eq!(ReviewKind::QualityFlag.as_str(), "quality_flag");
    }

    #[test]
    fn supersession_never_reuses_a_revision_number() {
        assert_eq!(next_revision_no(None), 1);
        assert_eq!(next_revision_no(Some(1)), 2);
        assert_eq!(next_revision_no(Some(41)), 42);
    }
}

/// Deterministic fake lifecycle: create revision -> queue job -> claim ->
/// stage progress -> chunk retry -> needs_review -> resume -> completed.
///
/// This is the in-memory contract proof. The PostgreSQL-backed equivalent
/// (restart/reconnect across real worker loss) lives in
/// `apps/chronicle/persistence/test_control_plane_postgres.py`.
#[cfg(test)]
mod lifecycle_tests {
    use super::*;
    use std::collections::BTreeMap;

    struct FakeJob {
        revision_no: u32,
        job: JobStatus,
        stages: BTreeMap<&'static str, StageStatus>,
        chunk: ChunkStatus,
        chunk_attempts: u32,
        open_reviews: u32,
        checkpoints: u32,
    }

    impl FakeJob {
        fn new() -> Self {
            let mut stages = BTreeMap::new();
            for stage in StageName::ALL_IN_ORDER {
                stages.insert(stage.as_str(), StageStatus::Pending);
            }
            Self {
                revision_no: next_revision_no(None),
                job: JobStatus::Queued,
                stages,
                chunk: ChunkStatus::Pending,
                chunk_attempts: 0,
                open_reviews: 0,
                checkpoints: 0,
            }
        }

        fn checkpoint(&mut self) {
            self.checkpoints += 1;
        }

        fn set_stage(&mut self, stage: StageName, next: StageStatus) {
            let current = self.stages[stage.as_str()];
            self.stages
                .insert(stage.as_str(), current.transition(next).unwrap());
            self.checkpoint();
        }
    }

    #[test]
    fn fake_restart_retry_review_lifecycle_reaches_completed() {
        // create revision -> queue job
        let mut fake = FakeJob::new();
        assert_eq!(fake.revision_no, 1);

        // claim: queued -> running
        fake.job = fake.job.transition(JobStatus::Running).unwrap();
        fake.checkpoint();

        // stage progress through prepare/structure/segment
        for stage in [StageName::Prepare, StageName::Structure, StageName::Segment] {
            fake.set_stage(stage, StageStatus::Running);
            // simulate worker restart: stage state is checkpointed, resume is
            // a self-transition-friendly re-entry into running
            fake.set_stage(stage, StageStatus::Running);
            fake.set_stage(stage, StageStatus::Completed);
        }

        // extract chunk: first attempt fails, retry succeeds
        fake.set_stage(StageName::Extract, StageStatus::Running);
        fake.chunk = fake.chunk.transition(ChunkStatus::Running).unwrap();
        fake.chunk_attempts += 1;
        fake.chunk = fake.chunk.transition(ChunkStatus::Failed).unwrap();
        fake.checkpoint(); // failure checkpoint survives the crash
        fake.chunk = fake.chunk.transition(ChunkStatus::Running).unwrap();
        fake.chunk_attempts += 1;
        fake.chunk = fake.chunk.transition(ChunkStatus::Completed).unwrap();
        assert_eq!(fake.chunk_attempts, 2);
        fake.set_stage(StageName::Extract, StageStatus::Completed);

        // assemble hits a quality gate: chunk + job go to needs_review
        fake.set_stage(StageName::Assemble, StageStatus::Running);
        fake.chunk = ChunkStatus::Pending
            .transition(ChunkStatus::Running)
            .unwrap();
        fake.chunk = fake.chunk.transition(ChunkStatus::NeedsReview).unwrap();
        fake.set_stage(StageName::Assemble, StageStatus::NeedsReview);
        fake.open_reviews += 1;
        fake.job = fake.job.transition(JobStatus::NeedsReview).unwrap();
        fake.checkpoint();

        // human resolves the review, worker resumes
        fake.open_reviews -= 1;
        assert_eq!(fake.open_reviews, 0);
        fake.job = fake.job.transition(JobStatus::Running).unwrap();
        fake.chunk = fake.chunk.transition(ChunkStatus::Running).unwrap();
        fake.chunk = fake.chunk.transition(ChunkStatus::Completed).unwrap();
        fake.set_stage(StageName::Assemble, StageStatus::Running);
        fake.set_stage(StageName::Assemble, StageStatus::Completed);

        // remaining stages complete; a terminal illegal jump still fails
        for stage in [StageName::Resolve, StageName::Publish, StageName::Present] {
            fake.set_stage(stage, StageStatus::Running);
            fake.set_stage(stage, StageStatus::Completed);
        }
        assert!(fake.job.transition(JobStatus::Queued).is_err());

        fake.job = fake.job.transition(JobStatus::Completed).unwrap();
        assert_eq!(fake.job, JobStatus::Completed);
        assert!(fake.stages.values().all(|s| *s == StageStatus::Completed));
        assert!(fake.checkpoints > 0, "lifecycle must leave checkpoints");
    }
}
