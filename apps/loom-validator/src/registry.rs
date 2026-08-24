//! Stable scenario metadata and registry.

use std::{collections::BTreeMap, error::Error, fmt};

use serde::{Deserialize, Serialize};

/// Stable metadata for one validator scenario.
///
/// The identifier is deliberately data owned by the scenario contract. It is
/// not derived from a Rust type, module, or function name, so implementation
/// refactors do not change the scenario identity used by reports and the Task
/// Ledger.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
pub struct ScenarioDescriptor {
    id: String,
    name: String,
    capability_area: String,
    supported_backends: Vec<String>,
    prerequisite_description: String,
    related_tasks: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    architecture_references: Option<Vec<String>>,
}

impl ScenarioDescriptor {
    /// Creates a descriptor with the stable identifier and human-readable name.
    #[must_use]
    pub fn new(id: impl Into<String>, name: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            name: name.into(),
            capability_area: String::new(),
            supported_backends: Vec::new(),
            prerequisite_description: String::new(),
            related_tasks: Vec::new(),
            architecture_references: None,
        }
    }

    /// Returns the stable scenario identifier.
    #[must_use]
    pub fn id(&self) -> &str {
        &self.id
    }

    /// Returns the scenario's human-readable name.
    #[must_use]
    pub fn name(&self) -> &str {
        &self.name
    }

    /// Returns the scenario name as the legacy description view.
    #[must_use]
    pub fn description(&self) -> &str {
        self.name()
    }

    /// Sets the capability area covered by this scenario.
    #[must_use]
    pub fn with_capability_area(mut self, capability_area: impl Into<String>) -> Self {
        self.capability_area = capability_area.into();
        self
    }

    /// Sets the prerequisite description for this scenario.
    #[must_use]
    pub fn with_prerequisite(mut self, prerequisite: impl Into<String>) -> Self {
        self.prerequisite_description = prerequisite.into();
        self
    }

    /// Adds supported backend names, removing duplicates and sorting them.
    #[must_use]
    pub fn with_supported_backends<I, B>(mut self, backends: I) -> Self
    where
        I: IntoIterator<Item = B>,
        B: Into<String>,
    {
        self.supported_backends = sorted_unique(backends);
        self
    }

    /// Adds related Task Ledger or issue identifiers, removing duplicates and
    /// sorting them for stable serialization.
    #[must_use]
    pub fn with_related_tasks<I, T>(mut self, tasks: I) -> Self
    where
        I: IntoIterator<Item = T>,
        T: Into<String>,
    {
        self.related_tasks = sorted_unique(tasks);
        self
    }

    /// Adds optional architecture references, removing duplicates and sorting
    /// them for stable serialization.
    #[must_use]
    pub fn with_architecture_references<I, R>(mut self, references: I) -> Self
    where
        I: IntoIterator<Item = R>,
        R: Into<String>,
    {
        self.architecture_references = Some(sorted_unique(references));
        self
    }

    /// Returns the capability area covered by this scenario.
    #[must_use]
    pub fn capability_area(&self) -> &str {
        &self.capability_area
    }

    /// Returns the supported backend set in deterministic order.
    #[must_use]
    pub fn supported_backends(&self) -> &[String] {
        &self.supported_backends
    }

    /// Returns the scenario's prerequisite description.
    #[must_use]
    pub fn prerequisite_description(&self) -> &str {
        &self.prerequisite_description
    }

    /// Returns related Task Ledger or issue identifiers in deterministic order.
    #[must_use]
    pub fn related_tasks(&self) -> &[String] {
        &self.related_tasks
    }

    /// Returns optional architecture references in deterministic order.
    #[must_use]
    pub fn architecture_references(&self) -> Option<&[String]> {
        self.architecture_references.as_deref()
    }
}

fn sorted_unique<I, T>(values: I) -> Vec<String>
where
    I: IntoIterator<Item = T>,
    T: Into<String>,
{
    let mut values: Vec<_> = values.into_iter().map(Into::into).collect();
    values.sort();
    values.dedup();
    values
}

/// Error returned when a scenario cannot be added to a registry.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RegistryError {
    /// The registry already contains the stable identifier.
    DuplicateScenarioId(String),
    /// A descriptor without a stable identifier is not a registrable scenario.
    EmptyScenarioId,
}

impl fmt::Display for RegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DuplicateScenarioId(id) => {
                write!(formatter, "scenario ID is already registered: {id}")
            }
            Self::EmptyScenarioId => formatter.write_str("scenario ID cannot be empty"),
        }
    }
}

impl Error for RegistryError {}

/// Registry of validator scenario metadata.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct ScenarioRegistry {
    scenarios: BTreeMap<String, ScenarioDescriptor>,
}

impl ScenarioRegistry {
    /// Creates the empty bootstrap registry used before scenario leaves land.
    #[must_use]
    pub const fn bootstrap() -> Self {
        Self {
            scenarios: BTreeMap::new(),
        }
    }

    /// Creates an empty scenario registry.
    #[must_use]
    pub const fn new() -> Self {
        Self::bootstrap()
    }

    /// Adds a scenario descriptor to the registry.
    ///
    /// `BTreeMap` both rejects duplicate stable IDs and makes enumeration
    /// independent of registration order.
    ///
    /// # Errors
    ///
    /// Returns [`RegistryError::EmptyScenarioId`] for an empty ID or
    /// [`RegistryError::DuplicateScenarioId`] when the ID is already present.
    pub fn register(&mut self, scenario: ScenarioDescriptor) -> Result<(), RegistryError> {
        if scenario.id().is_empty() {
            return Err(RegistryError::EmptyScenarioId);
        }

        if self.scenarios.contains_key(scenario.id()) {
            return Err(RegistryError::DuplicateScenarioId(scenario.id().to_owned()));
        }

        self.scenarios.insert(scenario.id().to_owned(), scenario);
        Ok(())
    }

    /// Returns the number of registered scenarios.
    #[must_use]
    pub fn len(&self) -> usize {
        self.scenarios.len()
    }

    /// Reports whether the registry contains no scenarios.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.scenarios.is_empty()
    }

    /// Looks up scenario metadata by stable ID.
    #[must_use]
    pub fn lookup(&self, id: impl AsRef<str>) -> Option<&ScenarioDescriptor> {
        self.scenarios.get(id.as_ref())
    }

    /// Alias for [`Self::lookup`].
    #[must_use]
    pub fn get(&self, id: impl AsRef<str>) -> Option<&ScenarioDescriptor> {
        self.lookup(id)
    }

    /// Enumerates scenario metadata in stable ID order.
    pub fn iter(&self) -> impl Iterator<Item = &ScenarioDescriptor> {
        self.scenarios.values()
    }
}
