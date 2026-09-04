//! Deterministic in-memory fake of the Chronicle control plane.
//!
//! The fake mirrors the `PostgreSQL` contract (`control_plane_store.py` plus
//! migration `0002`) without a database, a wall clock, or a worker process:
//! [`FakeClock`] replaces time so lease expiry is deterministic, and every
//! state change goes through the same [`crate::status`] transition guards
//! the durable store enforces. Orchestration logic tested here behaves the
//! same against the real store.

use std::collections::{HashMap, VecDeque};
use std::fmt;

use crate::status::{
    ChunkStatus, IllegalTransition, JobStatus, ReviewStatus, RunStatus, Stage, StageStatus,
};

/// Errors from fake control-plane operations.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ControlError {
    /// The referenced entity does not exist.
    NotFound {
        /// Entity kind (`"document"`, `"revision"`, ...).
        entity: &'static str,
        /// The unknown identifier.
        id: String,
    },
    /// A valid-entity request that conflicts with stored state (duplicate
    /// coordinates, lease held by another worker, cross-document link, ...).
    Conflict(String),
    /// A rejected lifecycle move.
    Illegal(IllegalTransition),
}

impl fmt::Display for ControlError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotFound { entity, id } => write!(f, "{entity} not found: {id}"),
            Self::Conflict(message) => write!(f, "control-plane conflict: {message}"),
            Self::Illegal(illegal) => write!(f, "{illegal}"),
        }
    }
}

impl std::error::Error for ControlError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Illegal(illegal) => Some(illegal),
            Self::NotFound { .. } | Self::Conflict(_) => None,
        }
    }
}

impl From<IllegalTransition> for ControlError {
    fn from(illegal: IllegalTransition) -> Self {
        Self::Illegal(illegal)
    }
}

/// A manually advanced clock (milliseconds) for deterministic lease tests.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FakeClock {
    now_ms: u64,
}

impl FakeClock {
    /// Create a clock starting at `start_ms`.
    #[must_use]
    pub const fn new(start_ms: u64) -> Self {
        Self { now_ms: start_ms }
    }

    /// Current time in milliseconds.
    #[must_use]
    pub const fn now_ms(self) -> u64 {
        self.now_ms
    }

    /// Move the clock forward.
    pub fn advance(&mut self, delta_ms: u64) {
        self.now_ms = self.now_ms.saturating_add(delta_ms);
    }
}

impl Default for FakeClock {
    fn default() -> Self {
        Self::new(0)
    }
}

/// A historical document (mutable title, immutable revisions).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Document {
    /// Fake-local identifier (`"doc-1"`, ...).
    pub id: String,
    /// Human title.
    pub title: String,
}

/// An immutable source revision. Replacement creates a new revision; the old
/// row is never modified.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Revision {
    /// Fake-local identifier (`"rev-1"`, ...).
    pub id: String,
    /// Owning document.
    pub document_id: String,
    /// 1-based number within the document.
    pub number: u32,
    /// Content hash of the uploaded source bytes.
    pub source_sha256: String,
    /// Previous revision superseded by this one, if any.
    pub supersedes: Option<String>,
}

/// A durable ingestion job bound to exactly one immutable revision.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Job {
    /// Fake-local identifier (`"job-1"`, ...).
    pub id: String,
    /// Owning document.
    pub document_id: String,
    /// The immutable revision being ingested.
    pub revision_id: String,
    /// Lifecycle status.
    pub status: JobStatus,
    /// Worker holding the current lease, if any.
    pub worker: Option<String>,
    /// Lease expiry in fake milliseconds.
    pub lease_expires_ms: Option<u64>,
    /// Claim count (restarts included).
    pub attempts: u32,
    /// Opaque orchestration progress marker.
    pub checkpoint: String,
    /// Pipeline stages in execution order.
    pub stages: Vec<(Stage, StageStatus)>,
    /// Whether a terminal status was reached.
    pub finished: bool,
}

/// A source section covered by one job.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Section {
    /// Fake-local identifier.
    pub id: String,
    /// Owning job.
    pub job_id: String,
    /// Covered revision.
    pub revision_id: String,
    /// Index within the job.
    pub index: u32,
    /// Byte range within the revision source.
    pub byte_range: (u64, u64),
}

/// A processing-unit chunk identified by stable coordinates.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Chunk {
    /// Fake-local identifier.
    pub id: String,
    /// Owning job.
    pub job_id: String,
    /// Owning section.
    pub section_id: String,
    /// Covered revision.
    pub revision_id: String,
    /// Index within the section.
    pub index: u32,
    /// Lifecycle status.
    pub status: ChunkStatus,
    /// Byte range within the revision source.
    pub byte_range: (u64, u64),
    /// Content hash of the byte range.
    pub source_sha256: String,
    /// Completed attempt count.
    pub retries: u32,
}

/// One chunk attempt. Retries append new runs; finished runs never change.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChunkRun {
    /// Fake-local identifier.
    pub id: String,
    /// Attempted chunk.
    pub chunk_id: String,
    /// Owning job.
    pub job_id: String,
    /// 1-based attempt number.
    pub attempt: u32,
    /// Attempt status.
    pub status: RunStatus,
}

/// A human/operator decision gate over job output.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ReviewItem {
    /// Fake-local identifier.
    pub id: String,
    /// Owning job.
    pub job_id: String,
    /// Lifecycle status.
    pub status: ReviewStatus,
}

/// An assembled artifact that feeds the C0 staged path.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Output {
    /// Fake-local identifier.
    pub id: String,
    /// Producing job.
    pub job_id: String,
    /// Covered revision.
    pub revision_id: String,
    /// Content hash of the assembled payload.
    pub artifact_sha256: String,
}

/// Everything a job produced, traced back to its immutable revision.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Provenance {
    /// The one immutable revision this job ingested.
    pub revision_id: String,
    /// Final job status.
    pub job_status: JobStatus,
    /// Stage statuses in pipeline order.
    pub stages: Vec<(Stage, StageStatus)>,
    /// Chunk identifiers handled by the job.
    pub chunks: Vec<String>,
    /// `(run id, status)` in attempt order.
    pub runs: Vec<(String, RunStatus)>,
    /// `(review id, status)` in creation order.
    pub reviews: Vec<(String, ReviewStatus)>,
    /// Output identifiers published by the job.
    pub outputs: Vec<String>,
}

/// Deterministic in-memory control plane.
#[derive(Debug, Default)]
pub struct FakeControlPlane {
    seq: u64,
    documents: HashMap<String, Document>,
    revisions: HashMap<String, Revision>,
    jobs: HashMap<String, Job>,
    queue: VecDeque<String>,
    sections: HashMap<String, Section>,
    chunks: HashMap<String, Chunk>,
    runs: HashMap<String, ChunkRun>,
    reviews: HashMap<String, ReviewItem>,
    review_order: Vec<String>,
    outputs: HashMap<String, Output>,
}

impl FakeControlPlane {
    /// Create an empty control plane.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    fn next_id(&mut self, prefix: &'static str) -> String {
        self.seq += 1;
        format!("{prefix}-{}", self.seq)
    }

    fn document(&self, id: &str) -> Result<&Document, ControlError> {
        self.documents
            .get(id)
            .ok_or_else(|| ControlError::NotFound {
                entity: "document",
                id: id.to_owned(),
            })
    }

    fn revision(&self, id: &str) -> Result<&Revision, ControlError> {
        self.revisions
            .get(id)
            .ok_or_else(|| ControlError::NotFound {
                entity: "revision",
                id: id.to_owned(),
            })
    }

    fn job(&self, id: &str) -> Result<&Job, ControlError> {
        self.jobs.get(id).ok_or_else(|| ControlError::NotFound {
            entity: "job",
            id: id.to_owned(),
        })
    }

    fn job_mut(&mut self, id: &str) -> Result<&mut Job, ControlError> {
        self.jobs.get_mut(id).ok_or_else(|| ControlError::NotFound {
            entity: "job",
            id: id.to_owned(),
        })
    }

    /// Create a document.
    ///
    /// # Errors
    ///
    /// Returns [`ControlError::Conflict`] when the title is empty.
    pub fn create_document(&mut self, title: &str) -> Result<String, ControlError> {
        if title.is_empty() {
            return Err(ControlError::Conflict(
                "document title must not be empty".to_owned(),
            ));
        }
        let id = self.next_id("doc");
        self.documents.insert(
            id.clone(),
            Document {
                id: id.clone(),
                title: title.to_owned(),
            },
        );
        Ok(id)
    }

    /// Create an immutable revision. Replacing a source requires
    /// `supersedes` pointing at a revision of the same document; the new
    /// revision number follows the superseded one, and the old row is never
    /// touched.
    ///
    /// # Errors
    ///
    /// Returns [`ControlError`] when the document or superseded revision is
    /// unknown, the supersession crosses documents, the same source bytes
    /// were already ingested for the document, or a first revision carries a
    /// supersession link.
    pub fn create_revision(
        &mut self,
        document_id: &str,
        source_sha256: &str,
        supersedes: Option<&str>,
    ) -> Result<String, ControlError> {
        self.document(document_id)?;
        if self
            .revisions
            .values()
            .any(|rev| rev.document_id == document_id && rev.source_sha256 == source_sha256)
        {
            return Err(ControlError::Conflict(
                "source bytes already ingested for this document".to_owned(),
            ));
        }
        let number = match supersedes {
            None => {
                if self
                    .revisions
                    .values()
                    .any(|rev| rev.document_id == document_id)
                {
                    return Err(ControlError::Conflict(
                        "replacing a source requires supersedes; revisions are never overwritten"
                            .to_owned(),
                    ));
                }
                1
            }
            Some(prev_id) => {
                let prev = self.revision(prev_id)?.clone();
                if prev.document_id != document_id {
                    return Err(ControlError::Conflict(
                        "revision supersession must stay within one document".to_owned(),
                    ));
                }
                prev.number + 1
            }
        };
        let id = self.next_id("rev");
        self.revisions.insert(
            id.clone(),
            Revision {
                id: id.clone(),
                document_id: document_id.to_owned(),
                number,
                source_sha256: source_sha256.to_owned(),
                supersedes: supersedes.map(str::to_owned),
            },
        );
        Ok(id)
    }

    /// Queue a job bound to one immutable revision and initialize all
    /// pipeline stages as pending.
    ///
    /// # Errors
    ///
    /// Returns [`ControlError`] when the revision is unknown or belongs to a
    /// different document.
    pub fn queue_job(
        &mut self,
        document_id: &str,
        revision_id: &str,
    ) -> Result<String, ControlError> {
        let revision = self.revision(revision_id)?.clone();
        if revision.document_id != document_id {
            return Err(ControlError::Conflict(
                "job revision must belong to the job document".to_owned(),
            ));
        }
        let id = self.next_id("job");
        self.jobs.insert(
            id.clone(),
            Job {
                id: id.clone(),
                document_id: document_id.to_owned(),
                revision_id: revision_id.to_owned(),
                status: JobStatus::Queued,
                worker: None,
                lease_expires_ms: None,
                attempts: 0,
                checkpoint: String::new(),
                stages: Stage::pipeline()
                    .into_iter()
                    .map(|stage| (stage, StageStatus::Pending))
                    .collect(),
                finished: false,
            },
        );
        self.queue.push_back(id.clone());
        Ok(id)
    }

    /// Claim the next queued job, or a running job whose lease expired
    /// (crashed-worker restart with its checkpoint intact).
    pub fn claim_job(&mut self, clock: &FakeClock, worker: &str, lease_ms: u64) -> Option<String> {
        let now = clock.now_ms();
        let running_expired = self.jobs.values().find_map(|job| {
            (job.status == JobStatus::Running
                && job.lease_expires_ms.is_some_and(|expiry| expiry < now))
            .then(|| job.id.clone())
        });
        let claimed = running_expired.or_else(|| self.queue.pop_front())?;
        let job = self.jobs.get_mut(&claimed)?;
        job.status = JobStatus::Running;
        job.worker = Some(worker.to_owned());
        job.lease_expires_ms = Some(now.saturating_add(lease_ms));
        job.attempts += 1;
        Some(claimed)
    }

    /// Renew a worker lease on a running job it owns.
    ///
    /// # Errors
    ///
    /// Returns [`ControlError`] when the job is unknown, owned by another
    /// worker, or not running.
    pub fn heartbeat(
        &mut self,
        clock: &FakeClock,
        job_id: &str,
        worker: &str,
        lease_ms: u64,
    ) -> Result<(), ControlError> {
        let job = self.job_mut(job_id)?;
        if job.worker.as_deref() != Some(worker) {
            return Err(ControlError::Conflict(
                "job is leased to a different worker".to_owned(),
            ));
        }
        if job.status != JobStatus::Running {
            return Err(ControlError::Conflict(
                "heartbeat requires a running job".to_owned(),
            ));
        }
        job.lease_expires_ms = Some(clock.now_ms().saturating_add(lease_ms));
        Ok(())
    }

    /// Persist orchestration progress without changing job status.
    ///
    /// # Errors
    ///
    /// Returns [`ControlError`] when the job is unknown, finished, or leased
    /// to a different worker.
    pub fn save_checkpoint(
        &mut self,
        job_id: &str,
        worker: Option<&str>,
        checkpoint: &str,
    ) -> Result<(), ControlError> {
        let job = self.job_mut(job_id)?;
        if job.finished {
            return Err(ControlError::Conflict(
                "cannot checkpoint a finished job".to_owned(),
            ));
        }
        if let Some(worker) = worker {
            if job.worker.as_deref() != Some(worker) {
                return Err(ControlError::Conflict(
                    "job is leased to a different worker".to_owned(),
                ));
            }
        }
        job.checkpoint.clear();
        job.checkpoint.push_str(checkpoint);
        Ok(())
    }

    /// Move a job to a new status, enforcing the frozen transition graph.
    ///
    /// # Errors
    ///
    /// Returns [`ControlError`] when the job is unknown or the move is illegal.
    pub fn transition_job(
        &mut self,
        job_id: &str,
        target: JobStatus,
    ) -> Result<JobStatus, ControlError> {
        let job = self.job_mut(job_id)?;
        let next = job.status.transition(target)?;
        job.status = next;
        job.finished = next.is_terminal();
        Ok(next)
    }

    /// Move one pipeline stage of a job to a new status.
    ///
    /// # Errors
    ///
    /// Returns [`ControlError`] when the job or stage is unknown or the move
    /// is illegal.
    pub fn transition_stage(
        &mut self,
        job_id: &str,
        stage: Stage,
        target: StageStatus,
    ) -> Result<StageStatus, ControlError> {
        let job = self.job_mut(job_id)?;
        let slot = job
            .stages
            .iter_mut()
            .find(|(candidate, _)| *candidate == stage)
            .ok_or_else(|| ControlError::NotFound {
                entity: "stage",
                id: stage.as_str().to_owned(),
            })?;
        slot.1 = slot.1.transition(target)?;
        Ok(slot.1)
    }

    /// Record a source section for a job.
    ///
    /// # Errors
    ///
    /// Returns [`ControlError`] when the job is unknown or the byte range is
    /// inverted.
    pub fn create_section(
        &mut self,
        job_id: &str,
        index: u32,
        byte_range: (u64, u64),
    ) -> Result<String, ControlError> {
        let job = self.job(job_id)?.clone();
        if byte_range.0 > byte_range.1 {
            return Err(ControlError::Conflict(
                "section start must not exceed section end".to_owned(),
            ));
        }
        if self
            .sections
            .values()
            .any(|section| section.job_id == job.id && section.index == index)
        {
            return Err(ControlError::Conflict(
                "section coordinate already exists".to_owned(),
            ));
        }
        let id = self.next_id("sec");
        self.sections.insert(
            id.clone(),
            Section {
                id: id.clone(),
                job_id: job.id,
                revision_id: job.revision_id,
                index,
                byte_range,
            },
        );
        Ok(id)
    }

    /// Record a chunk identified by stable (job, section, index) coordinates
    /// plus source offsets and content hash.
    ///
    /// # Errors
    ///
    /// Returns [`ControlError`] when the section is unknown, belongs to a
    /// different job, the range is inverted, or the coordinates are taken.
    pub fn create_chunk(
        &mut self,
        job_id: &str,
        section_id: &str,
        index: u32,
        byte_range: (u64, u64),
        source_sha256: &str,
    ) -> Result<String, ControlError> {
        let section = self
            .sections
            .get(section_id)
            .ok_or_else(|| ControlError::NotFound {
                entity: "section",
                id: section_id.to_owned(),
            })?
            .clone();
        if section.job_id != job_id {
            return Err(ControlError::Conflict(
                "chunk section must belong to the chunk job".to_owned(),
            ));
        }
        if byte_range.0 > byte_range.1 {
            return Err(ControlError::Conflict(
                "chunk start must not exceed chunk end".to_owned(),
            ));
        }
        if self.chunks.values().any(|chunk| {
            chunk.job_id == job_id && chunk.section_id == section_id && chunk.index == index
        }) {
            return Err(ControlError::Conflict(
                "chunk coordinate already exists".to_owned(),
            ));
        }
        let job = self.job(job_id)?.clone();
        let id = self.next_id("chunk");
        self.chunks.insert(
            id.clone(),
            Chunk {
                id: id.clone(),
                job_id: job_id.to_owned(),
                section_id: section_id.to_owned(),
                revision_id: job.revision_id,
                index,
                status: ChunkStatus::Pending,
                byte_range,
                source_sha256: source_sha256.to_owned(),
                retries: 0,
            },
        );
        Ok(id)
    }

    /// Move a chunk to a new status. Retries (`failed -> processing`)
    /// increment the retry counter; the retry itself is a new run.
    ///
    /// # Errors
    ///
    /// Returns [`ControlError`] when the chunk is unknown or the move is illegal.
    pub fn transition_chunk(
        &mut self,
        chunk_id: &str,
        target: ChunkStatus,
    ) -> Result<ChunkStatus, ControlError> {
        let chunk = self
            .chunks
            .get_mut(chunk_id)
            .ok_or_else(|| ControlError::NotFound {
                entity: "chunk",
                id: chunk_id.to_owned(),
            })?;
        let from = chunk.status;
        let next = from.transition(target)?;
        if from == ChunkStatus::Failed && next == ChunkStatus::Processing {
            chunk.retries += 1;
        }
        chunk.status = next;
        Ok(next)
    }

    /// Start a chunk attempt. Attempt numbers must be sequential; finished
    /// runs are never modified.
    ///
    /// # Errors
    ///
    /// Returns [`ControlError`] when the chunk is unknown, the attempt number
    /// is not the next one, or the run was already recorded.
    pub fn start_run(&mut self, chunk_id: &str, attempt: u32) -> Result<String, ControlError> {
        let chunk = self
            .chunks
            .get(chunk_id)
            .ok_or_else(|| ControlError::NotFound {
                entity: "chunk",
                id: chunk_id.to_owned(),
            })?
            .clone();
        if attempt < 1 {
            return Err(ControlError::Conflict(
                "attempt numbers start at 1".to_owned(),
            ));
        }
        if self
            .runs
            .values()
            .any(|run| run.chunk_id == chunk_id && run.attempt == attempt)
        {
            return Err(ControlError::Conflict(
                "chunk run already recorded".to_owned(),
            ));
        }
        let expected = self
            .runs
            .values()
            .filter(|run| run.chunk_id == chunk_id)
            .count()
            + 1;
        if usize::try_from(attempt).unwrap_or(usize::MAX) != expected {
            return Err(ControlError::Conflict(
                "chunk attempts must be sequential".to_owned(),
            ));
        }
        let id = self.next_id("run");
        self.runs.insert(
            id.clone(),
            ChunkRun {
                id: id.clone(),
                chunk_id: chunk_id.to_owned(),
                job_id: chunk.job_id.clone(),
                attempt,
                status: RunStatus::Started,
            },
        );
        Ok(id)
    }

    /// Complete a started run exactly once.
    ///
    /// # Errors
    ///
    /// Returns [`ControlError`] when the run is unknown or already finished.
    pub fn finish_run(
        &mut self,
        run_id: &str,
        target: RunStatus,
    ) -> Result<RunStatus, ControlError> {
        let run = self
            .runs
            .get_mut(run_id)
            .ok_or_else(|| ControlError::NotFound {
                entity: "chunk run",
                id: run_id.to_owned(),
            })?;
        if target == RunStatus::Started {
            return Err(ControlError::Conflict(
                "a started run may only complete as succeeded/failed".to_owned(),
            ));
        }
        let next = run.status.transition(target)?;
        run.status = next;
        Ok(next)
    }

    /// Open a review gate over job output.
    ///
    /// # Errors
    ///
    /// Returns [`ControlError`] when the job is unknown.
    pub fn open_review(&mut self, job_id: &str) -> Result<String, ControlError> {
        self.job(job_id)?;
        let id = self.next_id("review");
        self.reviews.insert(
            id.clone(),
            ReviewItem {
                id: id.clone(),
                job_id: job_id.to_owned(),
                status: ReviewStatus::Open,
            },
        );
        self.review_order.push(id.clone());
        Ok(id)
    }

    /// Resolve an open review exactly once.
    ///
    /// # Errors
    ///
    /// Returns [`ControlError`] when the review is unknown or already resolved.
    pub fn resolve_review(
        &mut self,
        review_id: &str,
        target: ReviewStatus,
    ) -> Result<ReviewStatus, ControlError> {
        let review = self
            .reviews
            .get_mut(review_id)
            .ok_or_else(|| ControlError::NotFound {
                entity: "review",
                id: review_id.to_owned(),
            })?;
        let next = review.status.transition(target)?;
        review.status = next;
        Ok(next)
    }

    /// Number of still-open reviews for a job.
    #[must_use]
    pub fn open_review_count(&self, job_id: &str) -> usize {
        self.review_order
            .iter()
            .filter_map(|id| self.reviews.get(id))
            .filter(|review| review.job_id == job_id && review.status == ReviewStatus::Open)
            .count()
    }

    /// Publish an assembled output (immutable; corrections are new rows).
    ///
    /// # Errors
    ///
    /// Returns [`ControlError`] when the job is unknown or the same artifact
    /// was already published for it.
    pub fn publish_output(
        &mut self,
        job_id: &str,
        artifact_sha256: &str,
    ) -> Result<String, ControlError> {
        let job = self.job(job_id)?.clone();
        if self
            .outputs
            .values()
            .any(|output| output.job_id == job_id && output.artifact_sha256 == artifact_sha256)
        {
            return Err(ControlError::Conflict(
                "ingestion output already published".to_owned(),
            ));
        }
        let id = self.next_id("out");
        self.outputs.insert(
            id.clone(),
            Output {
                id: id.clone(),
                job_id: job_id.to_owned(),
                revision_id: job.revision_id,
                artifact_sha256: artifact_sha256.to_owned(),
            },
        );
        Ok(id)
    }

    /// Trace everything a job produced back to its immutable revision.
    ///
    /// # Errors
    ///
    /// Returns [`ControlError`] when the job is unknown.
    pub fn provenance(&self, job_id: &str) -> Result<Provenance, ControlError> {
        let job = self.job(job_id)?.clone();
        let mut runs: Vec<(u32, String, RunStatus)> = self
            .runs
            .values()
            .filter(|run| run.job_id == job_id)
            .map(|run| (run.attempt, run.id.clone(), run.status))
            .collect();
        runs.sort_by_key(|run| run.0);
        Ok(Provenance {
            revision_id: job.revision_id.clone(),
            job_status: job.status,
            stages: job.stages.clone(),
            chunks: {
                let mut chunks: Vec<(u32, String)> = self
                    .chunks
                    .values()
                    .filter(|chunk| chunk.job_id == job_id)
                    .map(|chunk| (chunk.index, chunk.id.clone()))
                    .collect();
                chunks.sort();
                chunks.into_iter().map(|(_, id)| id).collect()
            },
            runs: runs
                .into_iter()
                .map(|(_, id, status)| (id, status))
                .collect(),
            reviews: self
                .review_order
                .iter()
                .filter_map(|id| self.reviews.get(id))
                .filter(|review| review.job_id == job_id)
                .map(|review| (review.id.clone(), review.status))
                .collect(),
            outputs: self
                .outputs
                .values()
                .filter(|output| output.job_id == job_id)
                .map(|output| output.id.clone())
                .collect(),
        })
    }

    /// Read-only access to a job (for tests and orchestration drivers).
    ///
    /// # Errors
    ///
    /// Returns [`ControlError::NotFound`] when the job is unknown.
    pub fn get_job(&self, job_id: &str) -> Result<&Job, ControlError> {
        self.job(job_id)
    }

    /// Read-only access to a chunk.
    ///
    /// # Errors
    ///
    /// Returns [`ControlError::NotFound`] when the chunk is unknown.
    pub fn get_chunk(&self, chunk_id: &str) -> Result<&Chunk, ControlError> {
        self.chunks
            .get(chunk_id)
            .ok_or_else(|| ControlError::NotFound {
                entity: "chunk",
                id: chunk_id.to_owned(),
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn setup() -> (FakeControlPlane, FakeClock, String, String, String) {
        let mut plane = FakeControlPlane::new();
        let clock = FakeClock::new(1_000);
        let doc = plane.create_document("Book").expect("create document");
        let rev = plane
            .create_revision(&doc, "sha-v1", None)
            .expect("create revision");
        let job = plane.queue_job(&doc, &rev).expect("queue job");
        (plane, clock, doc, rev, job)
    }

    #[test]
    #[allow(clippy::too_many_lines)]
    fn full_lifecycle_claim_progress_retry_review_resume_completed() {
        let (mut plane, clock, _doc, rev, job) = setup();

        // Queue initializes the full frozen pipeline as pending.
        assert_eq!(plane.get_job(&job).expect("job").stages.len(), 8);
        assert!(plane
            .get_job(&job)
            .expect("job")
            .stages
            .iter()
            .all(|(_, status)| *status == StageStatus::Pending));

        // Claim -> stage progress.
        let claimed = plane
            .claim_job(&clock, "fake-worker", 300_000)
            .expect("claim");
        assert_eq!(claimed, job);
        for stage in [Stage::Prepare, Stage::Structure, Stage::Segment] {
            plane
                .transition_stage(&job, stage, StageStatus::Running)
                .expect("stage running");
            plane
                .transition_stage(&job, stage, StageStatus::Completed)
                .expect("stage completed");
        }
        plane
            .save_checkpoint(&job, Some("fake-worker"), "segment-done")
            .expect("checkpoint");

        // Chunk retry: first attempt fails, the retry is a new run.
        let section = plane.create_section(&job, 0, (0, 128)).expect("section");
        let chunk = plane
            .create_chunk(&job, &section, 0, (0, 128), "sha-chunk")
            .expect("chunk");
        plane
            .transition_chunk(&chunk, ChunkStatus::Processing)
            .expect("processing");
        let run1 = plane.start_run(&chunk, 1).expect("run 1");
        plane
            .finish_run(&run1, RunStatus::Failed)
            .expect("run 1 fails");
        plane
            .transition_chunk(&chunk, ChunkStatus::Failed)
            .expect("chunk failed");
        plane
            .transition_chunk(&chunk, ChunkStatus::Processing)
            .expect("chunk retry");
        assert_eq!(plane.get_chunk(&chunk).expect("chunk").retries, 1);
        let run2 = plane.start_run(&chunk, 2).expect("run 2");
        plane
            .finish_run(&run2, RunStatus::Succeeded)
            .expect("run 2 succeeds");
        plane
            .transition_chunk(&chunk, ChunkStatus::Completed)
            .expect("chunk completed");

        for stage in [Stage::Extract, Stage::Assemble, Stage::Resolve] {
            plane
                .transition_stage(&job, stage, StageStatus::Running)
                .expect("stage running");
            plane
                .transition_stage(&job, stage, StageStatus::Completed)
                .expect("stage completed");
        }

        // Review gate: pause, resolve, resume.
        plane
            .transition_job(&job, JobStatus::NeedsReview)
            .expect("needs review");
        let review = plane.open_review(&job).expect("open review");
        assert_eq!(plane.open_review_count(&job), 1);
        plane
            .resolve_review(&review, ReviewStatus::Approved)
            .expect("approved");
        assert_eq!(plane.open_review_count(&job), 0);
        plane
            .transition_job(&job, JobStatus::Running)
            .expect("resume");

        for stage in [Stage::Publish, Stage::Present] {
            plane
                .transition_stage(&job, stage, StageStatus::Running)
                .expect("stage running");
            plane
                .transition_stage(&job, stage, StageStatus::Completed)
                .expect("stage completed");
        }
        plane
            .publish_output(&job, "sha-output")
            .expect("publish output");
        plane
            .transition_job(&job, JobStatus::Completed)
            .expect("completed");

        // Provenance traces everything to the one immutable revision.
        let provenance = plane.provenance(&job).expect("provenance");
        assert_eq!(provenance.revision_id, rev);
        assert_eq!(provenance.job_status, JobStatus::Completed);
        assert!(provenance
            .stages
            .iter()
            .all(|(_, status)| *status == StageStatus::Completed));
        assert_eq!(provenance.chunks.len(), 1);
        assert_eq!(
            provenance
                .runs
                .iter()
                .map(|(_, status)| *status)
                .collect::<Vec<_>>(),
            vec![RunStatus::Failed, RunStatus::Succeeded]
        );
        assert_eq!(provenance.reviews.len(), 1);
        assert_eq!(provenance.outputs.len(), 1);

        // A finished job accepts no more checkpoints or moves.
        assert!(plane.save_checkpoint(&job, None, "late").is_err());
        assert!(plane.transition_job(&job, JobStatus::Running).is_err());
    }

    #[test]
    fn expired_lease_is_reclaimed_with_checkpoint_intact() {
        let (mut plane, mut clock, _doc, _rev, job) = setup();
        plane.claim_job(&clock, "worker-1", 60_000).expect("claim");
        plane
            .save_checkpoint(&job, Some("worker-1"), "prepare-done")
            .expect("checkpoint");
        plane
            .heartbeat(&clock, &job, "worker-1", 60_000)
            .expect("heartbeat");

        // A live lease cannot be stolen.
        assert_eq!(plane.claim_job(&clock, "worker-2", 60_000), None);
        // A heartbeat from a different worker is rejected.
        assert!(plane.heartbeat(&clock, &job, "worker-2", 60_000).is_err());

        // After the worker dies (lease expires), another worker reclaims
        // the same job with its checkpoint intact.
        clock.advance(61_000);
        let reclaimed = plane
            .claim_job(&clock, "worker-2", 60_000)
            .expect("reclaim");
        assert_eq!(reclaimed, job);
        let state = plane.get_job(&job).expect("job");
        assert_eq!(state.worker.as_deref(), Some("worker-2"));
        assert_eq!(state.attempts, 2);
        assert_eq!(state.checkpoint, "prepare-done");
    }

    #[test]
    fn supersession_is_non_destructive() {
        let mut plane = FakeControlPlane::new();
        let doc = plane.create_document("Book").expect("document");
        let rev1 = plane.create_revision(&doc, "sha-v1", None).expect("rev 1");
        // Replacing without a supersession link is rejected.
        assert!(plane.create_revision(&doc, "sha-v2", None).is_err());
        let rev2 = plane
            .create_revision(&doc, "sha-v2", Some(&rev1))
            .expect("rev 2");
        assert_ne!(rev1, rev2);
        // Both rows survive; the old source bytes are untouched.
        assert_eq!(plane.revision(&rev1).expect("rev1").number, 1);
        assert_eq!(plane.revision(&rev2).expect("rev2").number, 2);
        assert_eq!(
            plane.revision(&rev2).expect("rev2").supersedes.as_deref(),
            Some(rev1.as_str())
        );
        // Same bytes twice are a conflict, and supersession cannot cross
        // documents.
        assert!(plane.create_revision(&doc, "sha-v1", Some(&rev2)).is_err());
        let other = plane.create_document("Other").expect("other");
        assert!(plane.create_revision(&other, "sha-x", Some(&rev1)).is_err());
        // A job stays bound to the revision it was queued with.
        let job = plane.queue_job(&doc, &rev1).expect("job");
        assert_eq!(plane.get_job(&job).expect("job").revision_id, rev1);
        assert!(plane.queue_job(&other, &rev1).is_err());
    }

    #[test]
    fn duplicate_coordinates_are_rejected() {
        let (mut plane, _clock, _doc, _rev, job) = setup();
        plane.create_section(&job, 0, (0, 64)).expect("section");
        assert!(plane.create_section(&job, 0, (0, 64)).is_err());
        assert!(plane.create_section(&job, 1, (64, 32)).is_err());
    }
}
