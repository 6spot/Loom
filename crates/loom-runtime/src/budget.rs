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
    /// Maximum nested subresolution depth observed in one root execution.
    SubresolutionDepth,
    /// Number of subresolution dispatches attempted in one root execution.
    SubresolutionCount,
}

impl std::fmt::Display for BudgetDimension {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let name = match self {
            Self::Events => "events",
            Self::Effects => "effects",
            Self::WorkMutations => "work_mutations",
            Self::SubresolutionDepth => "subresolution_depth",
            Self::SubresolutionCount => "subresolution_count",
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
    subresolution_depth: usize,
    subresolution_count: usize,
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
            subresolution_depth: 0,
            subresolution_count: 0,
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

    /// Returns the deepest nested subresolution observed so far.
    #[must_use]
    pub const fn subresolution_depth(self) -> usize {
        self.subresolution_depth
    }

    /// Returns the number of subresolution dispatches attempted so far.
    #[must_use]
    pub const fn subresolution_count(self) -> usize {
        self.subresolution_count
    }

    pub(crate) fn combine(self, other: Self) -> Self {
        Self {
            events: self.events.saturating_add(other.events),
            effects: self.effects.saturating_add(other.effects),
            work_mutations: self.work_mutations.saturating_add(other.work_mutations),
            subresolution_depth: self.subresolution_depth.max(other.subresolution_depth),
            subresolution_count: self
                .subresolution_count
                .saturating_add(other.subresolution_count),
        }
    }

    pub(crate) const fn with_subresolution(self, depth: usize, count: usize) -> Self {
        Self {
            subresolution_depth: depth,
            subresolution_count: count,
            ..self
        }
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
    subresolution_depth: Option<usize>,
    subresolution_count: Option<usize>,
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
            subresolution_depth: None,
            subresolution_count: None,
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

    /// Sets the maximum nested subresolution depth for one root execution.
    ///
    /// A root Action/Work resolver has depth zero. Its first child
    /// subresolution has depth one. The limit is checked before the child
    /// resolver is dispatched.
    #[must_use]
    pub const fn with_max_subresolution_depth(mut self, limit: usize) -> Self {
        self.subresolution_depth = Some(limit);
        self
    }

    /// Sets the maximum number of subresolution dispatches for one root
    /// execution. A rejected child still consumes one dispatch budget because
    /// it was routed and executed.
    #[must_use]
    pub const fn with_max_subresolution_count(mut self, limit: usize) -> Self {
        self.subresolution_count = Some(limit);
        self
    }

    /// Returns the configured nested subresolution depth limit.
    #[must_use]
    pub const fn max_subresolution_depth(self) -> Option<usize> {
        self.subresolution_depth
    }

    /// Returns the configured subresolution dispatch-count limit.
    #[must_use]
    pub const fn max_subresolution_count(self) -> Option<usize> {
        self.subresolution_count
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
            (
                BudgetDimension::SubresolutionDepth,
                self.subresolution_depth,
                usage.subresolution_depth,
            ),
            (
                BudgetDimension::SubresolutionCount,
                self.subresolution_count,
                usage.subresolution_count,
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
