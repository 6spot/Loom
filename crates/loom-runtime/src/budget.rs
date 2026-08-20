//! Small, Runtime-owned Resolution budget accounting.

use loom_protocol::Resolution;

/// A v0 budget dimension enforced before candidate validation begins.
///
/// These limits are Runtime policy, not World semantics. They bound the
/// number of protocol items the Runtime will inspect in one Resolution and do
/// not alter the pinned Timeline version or the meaning of a Capability
/// rejection.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BudgetDimension {
    /// Number of proposed Events in the Resolution.
    Events,
    /// Number of nested World Effects across all proposed Events.
    Effects,
    /// Number of proposed Durable Work mutations.
    WorkMutations,
}

impl std::fmt::Display for BudgetDimension {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let name = match self {
            Self::Events => "events",
            Self::Effects => "effects",
            Self::WorkMutations => "work_mutations",
        };
        formatter.write_str(name)
    }
}

/// The measured size of one untrusted Resolution.
///
/// `BudgetUsage` is calculated by Runtime before applying any Effect. It is
/// diagnostic execution metadata, not a persisted World value or a Capability
/// input that can be changed after validation starts.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct BudgetUsage {
    events: usize,
    effects: usize,
    work_mutations: usize,
}

impl BudgetUsage {
    /// Counts protocol items in a Resolution without applying its Effects.
    #[must_use]
    pub fn from_resolution(resolution: &Resolution) -> Self {
        let effects = resolution
            .events
            .iter()
            .map(|event| event.effects.len())
            .sum();
        Self {
            events: resolution.events.len(),
            effects,
            work_mutations: resolution.work.len(),
        }
    }

    /// Returns the number of proposed Events.
    #[must_use]
    pub const fn events(self) -> usize {
        self.events
    }

    /// Returns the number of nested Effects.
    #[must_use]
    pub const fn effects(self) -> usize {
        self.effects
    }

    /// Returns the number of Work mutations.
    #[must_use]
    pub const fn work_mutations(self) -> usize {
        self.work_mutations
    }
}

/// A Runtime policy limiting the amount of protocol data one Resolution may
/// ask the Effect Engine to inspect.
///
/// `None` means that a dimension is not limited by this policy. The default is
/// unlimited because the caller that owns Runtime policy must choose limits
/// appropriate for its deployment. A budget failure is a Runtime validation
/// error and is distinct from `loom_protocol::Rejection`.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ResolutionBudget {
    events: Option<usize>,
    effects: Option<usize>,
    work_mutations: Option<usize>,
}

impl ResolutionBudget {
    /// Creates a budget from optional limits for the v0 dimensions.
    #[must_use]
    pub const fn new(
        max_events: Option<usize>,
        max_effects: Option<usize>,
        max_work_mutations: Option<usize>,
    ) -> Self {
        Self {
            events: max_events,
            effects: max_effects,
            work_mutations: max_work_mutations,
        }
    }

    /// Returns a policy with no v0 dimension limits.
    #[must_use]
    pub const fn unlimited() -> Self {
        Self::new(None, None, None)
    }

    /// Sets the maximum number of Events while preserving other limits.
    #[must_use]
    pub const fn with_max_events(mut self, limit: usize) -> Self {
        self.events = Some(limit);
        self
    }

    /// Sets the maximum number of nested Effects while preserving other
    /// limits.
    #[must_use]
    pub const fn with_max_effects(mut self, limit: usize) -> Self {
        self.effects = Some(limit);
        self
    }

    /// Sets the maximum number of Work mutations while preserving other
    /// limits.
    #[must_use]
    pub const fn with_max_work_mutations(mut self, limit: usize) -> Self {
        self.work_mutations = Some(limit);
        self
    }

    /// Returns the configured Event limit.
    #[must_use]
    pub const fn max_events(self) -> Option<usize> {
        self.events
    }

    /// Returns the configured Effect limit.
    #[must_use]
    pub const fn max_effects(self) -> Option<usize> {
        self.effects
    }

    /// Returns the configured Work mutation limit.
    #[must_use]
    pub const fn max_work_mutations(self) -> Option<usize> {
        self.work_mutations
    }

    pub(crate) fn check(self, usage: BudgetUsage) -> Result<(), BudgetError> {
        let dimensions = [
            (BudgetDimension::Events, self.events, usage.events),
            (BudgetDimension::Effects, self.effects, usage.effects),
            (
                BudgetDimension::WorkMutations,
                self.work_mutations,
                usage.work_mutations,
            ),
        ];

        for (dimension, limit, actual) in dimensions {
            if let Some(limit) = limit
                && actual > limit
            {
                return Err(BudgetError {
                    dimension,
                    limit,
                    actual,
                });
            }
        }
        Ok(())
    }
}

/// A typed failure raised when a Resolution exceeds a Runtime budget.
///
/// This failure prevents validation from producing a `ValidatedResolution`;
/// it is not a Capability semantic rejection and must remain on the Runtime
/// error path.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BudgetError {
    /// Dimension whose configured limit was exceeded.
    pub dimension: BudgetDimension,
    /// Configured maximum for the dimension.
    pub limit: usize,
    /// Measured Resolution usage.
    pub actual: usize,
}

impl std::fmt::Display for BudgetError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            formatter,
            "resolution {} budget exceeded: {} > {}",
            self.dimension, self.actual, self.limit
        )
    }
}

impl std::error::Error for BudgetError {}
