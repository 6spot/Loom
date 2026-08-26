//! Stable scenario identifiers and descriptor metadata.
//!
//! Identifiers such as `CV-001` are stable and independent of Rust
//! function or file names. The descriptor carries the full metadata
//! required by the validator contract.

use std::fmt;

/// Stable identifier for a validator scenario, e.g. `CV-001`.
///
/// The identifier is intentionally opaque and independent of Rust
/// item names. It is used for registry lookup, deterministic
/// enumeration, and finding payloads.
#[derive(Clone, Debug, Eq, PartialEq, PartialOrd, Ord, Hash)]
pub struct ScenarioId(String);

impl ScenarioId {
    /// Creates a new scenario identifier.
    ///
    /// # Panics
    ///
    /// Panics if `id` is empty or does not look like a stable
    /// validator ID. The contract expects IDs such as `CV-001`.
    #[must_use]
    pub fn new(id: impl Into<String>) -> Self {
        let id = id.into();
        assert!(!id.is_empty(), "scenario id must be non-empty");
        // Enforce the stable `CV-` prefix used throughout the validator.
        // The check is intentionally permissive about digit width so that
        // future IDs like `CV-1000` remain valid without a contract break.
        assert!(
            is_valid_cv_id(&id),
            "scenario id must match CV-{{digits}} pattern, got {id:?}"
        );
        Self(id)
    }

    /// Attempts to create a scenario identifier, returning an error on invalid input.
    ///
    /// # Errors
    ///
    /// Returns an error when `id` is empty or does not match the `CV-` pattern.
    pub fn try_new(id: impl Into<String>) -> Result<Self, String> {
        let id = id.into();
        if id.is_empty() {
            return Err("scenario id must be non-empty".to_string());
        }
        if !is_valid_cv_id(&id) {
            return Err(format!(
                "scenario id must match CV-{{digits}} pattern, got {id:?}"
            ));
        }
        Ok(Self(id))
    }

    /// Borrows the identifier as a string slice.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl AsRef<str> for ScenarioId {
    fn as_ref(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for ScenarioId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

fn is_valid_cv_id(id: &str) -> bool {
    // Expected form: CV- + at least 3 digits. This keeps the contract
    // stable while remaining extensible for larger numbers.
    if !id.starts_with("CV-") {
        return false;
    }
    let suffix = &id[3..];
    if suffix.len() < 3 {
        return false;
    }
    suffix.chars().all(|c| c.is_ascii_digit())
}

/// The supported backend that a scenario can exercise.
///
/// This is a closed set for the current contract but is designed to be
/// extensible without runner branching. New backends are added as variants
/// and the runner/executor remains generic over the set.
#[derive(Clone, Copy, Debug, Eq, PartialEq, PartialOrd, Ord, Hash)]
pub enum BackendKind {
    /// The public Loom client / HTTP boundary (default for consumers).
    LoomClient,
    /// In-memory test backend used for unit testing.
    InMemory,
    /// Repository-composed `PostgreSQL` backend used for live evidence.
    PostgreSQL,
}

impl BackendKind {
    /// Returns the stable string representation of the backend.
    #[must_use]
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::LoomClient => "loom-client",
            Self::InMemory => "in-memory",
            Self::PostgreSQL => "postgresql",
        }
    }

    /// Reports whether this backend requires live `PostgreSQL` evidence.
    #[must_use]
    pub const fn is_postgres(self) -> bool {
        matches!(self, Self::PostgreSQL)
    }

    /// Returns the storage evidence represented by this explicitly selected
    /// backend.
    #[must_use]
    pub const fn evidence(self) -> BackendEvidence {
        match self {
            Self::LoomClient => BackendEvidence::External,
            Self::InMemory => BackendEvidence::InMemory,
            Self::PostgreSQL => BackendEvidence::PostgreSQL,
        }
    }
}

impl fmt::Display for BackendKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// The storage identity that Validator is allowed to claim in evidence.
///
/// `External` is the default for a generic HTTP endpoint. The endpoint may be
/// backed by any implementation, but Validator has no trusted way to infer
/// which one it is. `InMemory` and `PostgreSQL` are trusted only when a
/// controlled harness explicitly constructs the corresponding backend kind;
/// ambient environment variables never create either identity.
#[derive(Clone, Copy, Debug, Eq, PartialEq, PartialOrd, Ord, Hash)]
pub enum BackendEvidence {
    /// A generic/external Loom endpoint with no trusted storage identity.
    External,
    /// A controlled `InMemory` harness.
    InMemory,
    /// A controlled `PostgreSQL` harness.
    PostgreSQL,
}

impl BackendEvidence {
    /// Returns the stable report label for this evidence class.
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::External => "external",
            Self::InMemory => "in-memory",
            Self::PostgreSQL => "postgresql",
        }
    }

    /// Returns whether this evidence class was produced by a controlled
    /// harness and may be used for storage-specific policy checks.
    #[must_use]
    pub const fn is_trusted(self) -> bool {
        !matches!(self, Self::External)
    }

    /// Returns whether this is trusted `PostgreSQL` evidence.
    #[must_use]
    pub const fn is_postgres(self) -> bool {
        matches!(self, Self::PostgreSQL)
    }

    /// Returns the compatibility backend kind corresponding to this evidence.
    #[must_use]
    pub const fn backend_kind(self) -> BackendKind {
        match self {
            Self::External => BackendKind::LoomClient,
            Self::InMemory => BackendKind::InMemory,
            Self::PostgreSQL => BackendKind::PostgreSQL,
        }
    }
}

impl fmt::Display for BackendEvidence {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Capability area that a scenario validates.
///
/// Kept as an opaque string for extensibility. Known values are
/// documented centrally but the contract does not hard-code them
/// into runner branching.
#[derive(Clone, Debug, Eq, PartialEq, PartialOrd, Ord, Hash)]
pub struct CapabilityArea(String);

impl CapabilityArea {
    /// Creates a new capability area label.
    ///
    /// # Panics
    ///
    /// Panics if `area` is empty.
    #[must_use]
    pub fn new(area: impl Into<String>) -> Self {
        let area = area.into();
        assert!(!area.is_empty(), "capability area must be non-empty");
        Self(area)
    }

    /// Borrows the capability area as a string.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl AsRef<str> for CapabilityArea {
    fn as_ref(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for CapabilityArea {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

/// Stable metadata for one validator scenario.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScenarioDescriptor {
    id: ScenarioId,
    name: String,
    capability_area: CapabilityArea,
    supported_backends: Vec<BackendKind>,
    prerequisite: String,
    related_tasks: Vec<String>,
    architecture_refs: Vec<String>,
}

impl ScenarioDescriptor {
    /// Creates a scenario descriptor with the required contract fields.
    ///
    /// `architecture_refs` is optional and may be empty. All other
    /// fields are required for the stable contract.
    ///
    /// # Panics
    ///
    /// Panics if `name` is empty or `supported_backends` is empty, or if `id`
    /// or `capability_area` are invalid.
    #[must_use]
    pub fn new(
        id: impl Into<String>,
        name: impl Into<String>,
        capability_area: impl Into<String>,
        supported_backends: Vec<BackendKind>,
        prerequisite: impl Into<String>,
        related_tasks: Vec<String>,
        architecture_refs: Vec<String>,
    ) -> Self {
        let id = ScenarioId::new(id);
        let name = name.into();
        let capability_area = CapabilityArea::new(capability_area);
        let prerequisite = prerequisite.into();
        assert!(!name.is_empty(), "scenario name must be non-empty");
        assert!(
            !supported_backends.is_empty(),
            "supported backends must be non-empty"
        );
        // `prerequisite` may be empty when no prerequisite exists, but we
        // keep it as a required description field (empty = none).
        Self {
            id,
            name,
            capability_area,
            supported_backends,
            prerequisite,
            related_tasks,
            architecture_refs,
        }
    }

    /// Returns the stable scenario identifier.
    #[must_use]
    pub fn id(&self) -> &ScenarioId {
        &self.id
    }

    /// Returns the stable identifier as a string.
    #[must_use]
    pub fn id_str(&self) -> &str {
        self.id.as_str()
    }

    /// Returns the human-readable scenario name.
    #[must_use]
    pub fn name(&self) -> &str {
        &self.name
    }

    /// Returns the capability area for this scenario.
    #[must_use]
    pub fn capability_area(&self) -> &CapabilityArea {
        &self.capability_area
    }

    /// Returns the supported backend set for this scenario.
    #[must_use]
    pub fn supported_backends(&self) -> &[BackendKind] {
        &self.supported_backends
    }

    /// Returns the prerequisite description.
    ///
    /// An empty string indicates no prerequisite.
    #[must_use]
    pub fn prerequisite(&self) -> &str {
        &self.prerequisite
    }

    /// Returns the related task identifiers.
    #[must_use]
    pub fn related_tasks(&self) -> &[String] {
        &self.related_tasks
    }

    /// Returns optional architecture references.
    #[must_use]
    pub fn architecture_refs(&self) -> &[String] {
        &self.architecture_refs
    }

    /// Returns the legacy description alias (name).
    ///
    /// Kept for compatibility with synthesis that still expects a
    /// `description` accessor.
    #[must_use]
    pub fn description(&self) -> &str {
        &self.name
    }
}

#[cfg(test)]
mod tests {
    use super::{BackendEvidence, BackendKind, CapabilityArea, ScenarioId};

    #[test]
    fn scenario_id_validates_cv_prefix() {
        let id = ScenarioId::new("CV-001");
        assert_eq!(id.as_str(), "CV-001");
    }

    #[test]
    fn scenario_id_rejects_invalid() {
        assert!(ScenarioId::try_new("").is_err());
        assert!(ScenarioId::try_new("001").is_err());
        assert!(ScenarioId::try_new("CV-1").is_err());
        assert!(ScenarioId::try_new("cv-001").is_err());
    }

    #[test]
    fn backend_kind_display() {
        assert_eq!(BackendKind::LoomClient.as_str(), "loom-client");
        assert_eq!(BackendKind::InMemory.as_str(), "in-memory");
        assert_eq!(BackendKind::PostgreSQL.as_str(), "postgresql");
    }

    #[test]
    fn backend_kind_maps_to_explicit_evidence() {
        assert_eq!(
            BackendKind::LoomClient.evidence(),
            BackendEvidence::External
        );
        assert_eq!(BackendKind::InMemory.evidence(), BackendEvidence::InMemory);
        assert_eq!(
            BackendKind::PostgreSQL.evidence(),
            BackendEvidence::PostgreSQL
        );
    }

    #[test]
    fn only_controlled_evidence_is_trusted() {
        assert!(!BackendEvidence::External.is_trusted());
        assert!(BackendEvidence::InMemory.is_trusted());
        assert!(BackendEvidence::PostgreSQL.is_trusted());
        assert!(BackendEvidence::PostgreSQL.is_postgres());
        assert!(!BackendEvidence::InMemory.is_postgres());
    }

    #[test]
    fn capability_area_new() {
        let area = CapabilityArea::new("world");
        assert_eq!(area.as_str(), "world");
    }
}
