//! Scenario registry metadata.

/// Stable metadata for one validator scenario.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScenarioDescriptor {
    id: String,
    description: String,
}

impl ScenarioDescriptor {
    /// Creates a scenario descriptor without implementing the scenario yet.
    #[must_use]
    pub fn new(id: impl Into<String>, description: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            description: description.into(),
        }
    }

    /// Returns the stable scenario identifier.
    #[must_use]
    pub fn id(&self) -> &str {
        &self.id
    }

    /// Returns the scenario's human-readable description.
    #[must_use]
    pub fn description(&self) -> &str {
        &self.description
    }
}

/// Registry of validator scenario metadata.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct ScenarioRegistry {
    scenarios: Vec<ScenarioDescriptor>,
}

impl ScenarioRegistry {
    /// Creates the empty bootstrap registry used before scenario leaves land.
    #[must_use]
    pub const fn bootstrap() -> Self {
        Self {
            scenarios: Vec::new(),
        }
    }

    /// Adds a scenario descriptor to the registry.
    pub fn register(&mut self, scenario: ScenarioDescriptor) {
        self.scenarios.push(scenario);
    }

    /// Returns the number of registered scenarios.
    #[must_use]
    pub const fn len(&self) -> usize {
        self.scenarios.len()
    }

    /// Reports whether the registry contains no scenarios.
    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.scenarios.is_empty()
    }

    /// Enumerates registered scenario metadata in registration order.
    pub fn iter(&self) -> impl Iterator<Item = &ScenarioDescriptor> {
        self.scenarios.iter()
    }
}
