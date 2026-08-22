//! Runtime-owned entropy source and composition boundary.

use std::sync::{
    Mutex,
    atomic::{AtomicUsize, Ordering},
};

use loom_capability::{EntropyRequest, EntropySample};
use serde::{Deserialize, Serialize};

/// Stable provenance identity for the entropy environment pinned by one
/// Execution Assembly.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(transparent)]
pub struct EntropySourceId(String);

impl EntropySourceId {
    /// Creates a source identity used in Execution Assembly provenance.
    #[must_use]
    pub fn new(value: impl Into<String>) -> Self {
        Self(value.into())
    }

    /// Returns the stable source identity.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl Default for EntropySourceId {
    fn default() -> Self {
        Self::from("unknown")
    }
}

impl From<&str> for EntropySourceId {
    fn from(value: &str) -> Self {
        Self::new(value)
    }
}

impl From<String> for EntropySourceId {
    fn from(value: String) -> Self {
        Self::new(value)
    }
}

impl std::fmt::Display for EntropySourceId {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0)
    }
}

/// Boundary-safe failure returned by a Runtime entropy source.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EntropySourceError {
    /// Explanation safe to propagate through the Runtime host boundary.
    pub message: String,
}

impl EntropySourceError {
    /// Creates a source failure without exposing provider implementation data.
    #[must_use]
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl std::fmt::Display for EntropySourceError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for EntropySourceError {}

/// Runtime composition port for controlled entropy.
///
/// The trait is held by Runtime, never passed to Capability code. A source may
/// be backed by an application CSPRNG or another approved implementation, but
/// the only value crossing `ResolutionContext` is the requested sample.
pub trait EntropySource: Send + Sync {
    /// Returns the identity pinned into each new Execution Assembly.
    fn source_id(&self) -> EntropySourceId {
        EntropySourceId::from("anonymous")
    }

    /// Produces exactly the requested number of bytes.
    ///
    /// Runtime validates the returned length again before exposing the sample
    /// to a Capability resolver.
    ///
    /// # Errors
    ///
    /// Returns a boundary-safe source error when the configured source cannot
    /// produce the requested sample.
    fn sample(&self, request: &EntropyRequest) -> Result<EntropySample, EntropySourceError>;
}

/// Explicit no-source default used until the composition root injects one.
#[derive(Clone, Copy, Debug, Default)]
pub struct UnavailableEntropySource;

impl EntropySource for UnavailableEntropySource {
    fn source_id(&self) -> EntropySourceId {
        EntropySourceId::from("unconfigured")
    }

    fn sample(&self, _request: &EntropyRequest) -> Result<EntropySample, EntropySourceError> {
        Err(EntropySourceError::new("no entropy source was configured"))
    }
}

/// Deterministic source for focused Runtime and Capability tests.
///
/// Scripted samples are consumed in request order and must match each
/// requested byte count exactly. `from_seed` provides a small deterministic
/// byte generator for tests that need more samples; it is not intended as a
/// production cryptographic source.
pub struct DeterministicEntropySource {
    source_id: EntropySourceId,
    scripted: Vec<EntropySample>,
    next_script: Mutex<usize>,
    seed: Option<u64>,
    calls: AtomicUsize,
}

impl std::fmt::Debug for DeterministicEntropySource {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("DeterministicEntropySource")
            .field("source_id", &self.source_id)
            .field("scripted_samples", &self.scripted.len())
            .field("seeded", &self.seed.is_some())
            .field("calls", &self.calls())
            .finish_non_exhaustive()
    }
}

impl DeterministicEntropySource {
    /// Creates a deterministic source from an ordered sample script.
    #[must_use]
    pub fn new(samples: impl IntoIterator<Item = Vec<u8>>) -> Self {
        Self::with_source_id("deterministic", samples)
    }

    /// Creates a scripted source with an explicit provenance identity.
    #[must_use]
    pub fn with_source_id(
        source_id: impl Into<EntropySourceId>,
        samples: impl IntoIterator<Item = Vec<u8>>,
    ) -> Self {
        Self {
            source_id: source_id.into(),
            scripted: samples.into_iter().map(EntropySample::new).collect(),
            next_script: Mutex::new(0),
            seed: None,
            calls: AtomicUsize::new(0),
        }
    }

    /// Creates a deterministic generated source for test-only repeated calls.
    #[must_use]
    pub fn from_seed(seed: u64) -> Self {
        Self {
            source_id: EntropySourceId::from("deterministic-seed"),
            scripted: Vec::new(),
            next_script: Mutex::new(0),
            seed: Some(seed),
            calls: AtomicUsize::new(0),
        }
    }

    /// Returns the number of source calls made so far.
    #[must_use]
    pub fn calls(&self) -> usize {
        self.calls.load(Ordering::Acquire)
    }

    fn seeded_sample(seed: u64, call: usize, byte_count: usize) -> EntropySample {
        let mut state = seed
            ^ (call as u64)
                .wrapping_add(1)
                .wrapping_mul(0x9E37_79B9_7F4A_7C15);
        let mut bytes = Vec::with_capacity(byte_count);
        for _ in 0..byte_count {
            state ^= state << 7;
            state ^= state >> 9;
            state ^= state << 8;
            bytes.push(state.to_le_bytes()[0]);
        }
        EntropySample::new(bytes)
    }
}

impl EntropySource for DeterministicEntropySource {
    fn source_id(&self) -> EntropySourceId {
        self.source_id.clone()
    }

    fn sample(&self, request: &EntropyRequest) -> Result<EntropySample, EntropySourceError> {
        let call = self.calls.fetch_add(1, Ordering::AcqRel);
        if let Some(seed) = self.seed {
            return Ok(Self::seeded_sample(seed, call, request.byte_count()));
        }

        let mut next_script = self
            .next_script
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let Some(sample) = self.scripted.get(*next_script).cloned() else {
            return Err(EntropySourceError::new(
                "deterministic entropy script is exhausted",
            ));
        };
        *next_script += 1;
        if sample.len() != request.byte_count() {
            return Err(EntropySourceError::new(format!(
                "scripted entropy sample has {} bytes, request needs {}",
                sample.len(),
                request.byte_count()
            )));
        }
        Ok(sample)
    }
}

#[cfg(test)]
mod tests {
    use loom_capability::EntropyRequest;

    use super::{DeterministicEntropySource, EntropySource};

    #[test]
    fn scripted_source_is_reproducible_and_counts_calls() {
        let first = DeterministicEntropySource::new(vec![vec![1, 2], vec![3]]);
        let second = DeterministicEntropySource::new(vec![vec![1, 2], vec![3]]);
        let two = EntropyRequest::new(2);
        let one = EntropyRequest::new(1);

        assert_eq!(
            first
                .sample(&two)
                .expect("first scripted sample")
                .as_bytes(),
            second
                .sample(&two)
                .expect("second scripted sample")
                .as_bytes()
        );
        assert_eq!(
            first.sample(&one).expect("first second sample").as_bytes(),
            second
                .sample(&one)
                .expect("second second sample")
                .as_bytes()
        );
        assert_eq!(first.calls(), 2);
        assert_eq!(second.calls(), 2);
    }

    #[test]
    fn seeded_source_repeats_the_same_call_sequence() {
        let first = DeterministicEntropySource::from_seed(7);
        let second = DeterministicEntropySource::from_seed(7);
        let request = EntropyRequest::new(8);

        assert_eq!(
            first.sample(&request).expect("first seeded sample"),
            second.sample(&request).expect("second seeded sample")
        );
        assert_eq!(first.calls(), 1);
        assert_eq!(second.calls(), 1);
    }
}
