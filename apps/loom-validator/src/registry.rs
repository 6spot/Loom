//! Scenario registry with deterministic enumeration and stable IDs.

use std::collections::BTreeMap;
use std::fmt;

use crate::scenario::{ScenarioDescriptor, ScenarioId};

/// Error returned when registry operations fail.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RegistryError {
    /// A scenario with the same stable ID already exists.
    DuplicateId(ScenarioId),
}

impl fmt::Display for RegistryError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DuplicateId(id) => write!(f, "duplicate scenario id: {id}"),
        }
    }
}

impl std::error::Error for RegistryError {}

/// Registry of validator scenario metadata.
///
/// Enumeration is deterministic (sorted by stable `CV-` identifier) and
/// duplicate identifiers are rejected. Lookup by stable ID is supported.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct ScenarioRegistry {
    scenarios: BTreeMap<ScenarioId, ScenarioDescriptor>,
}

impl ScenarioRegistry {
    /// Creates the empty bootstrap registry used before scenario leaves land.
    #[must_use]
    pub fn bootstrap() -> Self {
        Self {
            scenarios: BTreeMap::new(),
        }
    }

    /// Registers a scenario descriptor.
    ///
    /// Returns an error if a scenario with the same stable ID already exists.
    ///
    /// # Errors
    ///
    /// Returns [`RegistryError::DuplicateId`] when `scenario.id()` is already present.
    pub fn register(&mut self, scenario: ScenarioDescriptor) -> Result<(), RegistryError> {
        let id = scenario.id().clone();
        if self.scenarios.contains_key(&id) {
            return Err(RegistryError::DuplicateId(id));
        }
        self.scenarios.insert(id, scenario);
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

    /// Returns a reference to a scenario by its stable string ID.
    #[must_use]
    pub fn get(&self, id: &str) -> Option<&ScenarioDescriptor> {
        // Validate lookup via ScenarioId parsing but allow any string; if parsing fails we just search by string.
        self.scenarios
            .iter()
            .find(|(k, _)| k.as_str() == id)
            .map(|(_, v)| v)
    }

    /// Returns a reference to a scenario by its typed identifier.
    #[must_use]
    pub fn get_by_id(&self, id: &ScenarioId) -> Option<&ScenarioDescriptor> {
        self.scenarios.get(id)
    }

    /// Enumerates registered scenario metadata in deterministic order (sorted by ID).
    pub fn iter(&self) -> impl Iterator<Item = &ScenarioDescriptor> {
        self.scenarios.values()
    }

    /// Enumerates scenario IDs in deterministic order.
    pub fn ids(&self) -> impl Iterator<Item = &ScenarioId> {
        self.scenarios.keys()
    }
}

#[cfg(test)]
mod tests {
    use super::{RegistryError, ScenarioRegistry};
    use crate::scenario::{BackendKind, ScenarioDescriptor, ScenarioId};

    fn descriptor(id: &str) -> ScenarioDescriptor {
        ScenarioDescriptor::new(
            id,
            format!("scenario {id}"),
            "world",
            vec![BackendKind::LoomClient],
            "none",
            vec!["VAL-T2".to_string()],
            vec![],
        )
    }

    #[test]
    fn duplicate_ids_are_rejected() {
        let mut registry = ScenarioRegistry::bootstrap();
        assert!(registry.register(descriptor("CV-001")).is_ok());
        let err = registry.register(descriptor("CV-001")).unwrap_err();
        assert_eq!(err, RegistryError::DuplicateId(ScenarioId::new("CV-001")));
        assert_eq!(registry.len(), 1);
    }

    #[test]
    fn enumeration_order_is_deterministic() {
        let mut a = ScenarioRegistry::bootstrap();
        a.register(descriptor("CV-003")).unwrap();
        a.register(descriptor("CV-001")).unwrap();
        a.register(descriptor("CV-002")).unwrap();

        let mut b = ScenarioRegistry::bootstrap();
        b.register(descriptor("CV-001")).unwrap();
        b.register(descriptor("CV-002")).unwrap();
        b.register(descriptor("CV-003")).unwrap();

        let ids_a: Vec<_> = a.iter().map(|d| d.id_str().to_string()).collect();
        let ids_b: Vec<_> = b.iter().map(|d| d.id_str().to_string()).collect();
        assert_eq!(ids_a, vec!["CV-001", "CV-002", "CV-003"]);
        assert_eq!(ids_a, ids_b);
    }

    #[test]
    fn lookup_by_id() {
        let mut registry = ScenarioRegistry::bootstrap();
        registry.register(descriptor("CV-010")).unwrap();
        assert!(registry.get("CV-010").is_some());
        assert!(registry.get("CV-999").is_none());
        assert!(registry.get_by_id(&ScenarioId::new("CV-010")).is_some());
    }
}
