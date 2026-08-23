//! Small, Runtime-owned Resolution budget accounting.

use loom_protocol::Resolution;
use serde::{Deserialize, Serialize};

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
    /// Number of mediated entropy requests made in one root execution.
    EntropyRequests,
    /// Total bytes returned by mediated entropy requests in one root execution.
    EntropyBytes,
    /// Largest individual mediated entropy request in one root execution.
    EntropyRequestBytes,
    /// Number of mediated semantic queries made in one root execution.
    SemanticQueries,
    /// Number of semantic hits returned in one root execution.
    SemanticResults,
    /// Total deterministic bytes returned by semantic queries.
    SemanticResultBytes,
    /// Largest semantic query depth observed in one root execution.
    SemanticDepth,
    /// Largest semantic filter count observed in one root execution.
    SemanticFilters,
}

impl std::fmt::Display for BudgetDimension {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let name = match self {
            Self::Events => "events",
            Self::Effects => "effects",
            Self::WorkMutations => "work_mutations",
            Self::SubresolutionDepth => "subresolution_depth",
            Self::SubresolutionCount => "subresolution_count",
            Self::EntropyRequests => "entropy_requests",
            Self::EntropyBytes => "entropy_bytes",
            Self::EntropyRequestBytes => "entropy_request_bytes",
            Self::SemanticQueries => "semantic_queries",
            Self::SemanticResults => "semantic_results",
            Self::SemanticResultBytes => "semantic_result_bytes",
            Self::SemanticDepth => "semantic_depth",
            Self::SemanticFilters => "semantic_filters",
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
    entropy_requests: usize,
    entropy_bytes: usize,
    entropy_request_bytes: usize,
    semantic_queries: usize,
    semantic_results: usize,
    semantic_result_bytes: usize,
    semantic_depth: usize,
    semantic_filters: usize,
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
            entropy_requests: 0,
            entropy_bytes: 0,
            entropy_request_bytes: 0,
            semantic_queries: 0,
            semantic_results: 0,
            semantic_result_bytes: 0,
            semantic_depth: 0,
            semantic_filters: 0,
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

    /// Returns the number of mediated entropy requests observed so far.
    #[must_use]
    pub const fn entropy_requests(self) -> usize {
        self.entropy_requests
    }

    /// Returns the total number of mediated entropy bytes observed so far.
    #[must_use]
    pub const fn entropy_bytes(self) -> usize {
        self.entropy_bytes
    }

    /// Returns the largest individual entropy request observed so far.
    #[must_use]
    pub const fn entropy_request_bytes(self) -> usize {
        self.entropy_request_bytes
    }

    /// Returns the number of mediated semantic queries observed so far.
    #[must_use]
    pub const fn semantic_queries(self) -> usize {
        self.semantic_queries
    }

    /// Returns the number of semantic hits observed so far.
    #[must_use]
    pub const fn semantic_results(self) -> usize {
        self.semantic_results
    }

    /// Returns the total deterministic semantic result bytes observed so far.
    #[must_use]
    pub const fn semantic_result_bytes(self) -> usize {
        self.semantic_result_bytes
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
            entropy_requests: self.entropy_requests.saturating_add(other.entropy_requests),
            entropy_bytes: self.entropy_bytes.saturating_add(other.entropy_bytes),
            entropy_request_bytes: self.entropy_request_bytes.max(other.entropy_request_bytes),
            semantic_queries: self.semantic_queries.saturating_add(other.semantic_queries),
            semantic_results: self.semantic_results.saturating_add(other.semantic_results),
            semantic_result_bytes: self
                .semantic_result_bytes
                .saturating_add(other.semantic_result_bytes),
            semantic_depth: self.semantic_depth.max(other.semantic_depth),
            semantic_filters: self.semantic_filters.max(other.semantic_filters),
        }
    }

    pub(crate) const fn with_subresolution(self, depth: usize, count: usize) -> Self {
        Self {
            subresolution_depth: depth,
            subresolution_count: count,
            ..self
        }
    }

    pub(crate) const fn with_entropy(self, request_bytes: usize) -> Self {
        let entropy_request_bytes = if self.entropy_request_bytes > request_bytes {
            self.entropy_request_bytes
        } else {
            request_bytes
        };
        Self {
            entropy_requests: self.entropy_requests.saturating_add(1),
            entropy_bytes: self.entropy_bytes.saturating_add(request_bytes),
            entropy_request_bytes,
            ..self
        }
    }

    pub(crate) fn with_semantic_request(self, depth: usize, filters: usize) -> Self {
        Self {
            semantic_queries: self.semantic_queries.saturating_add(1),
            semantic_depth: self.semantic_depth.max(depth),
            semantic_filters: self.semantic_filters.max(filters),
            ..self
        }
    }

    pub(crate) fn with_semantic_result(self, results: usize, bytes: usize) -> Self {
        Self {
            semantic_results: self.semantic_results.saturating_add(results),
            semantic_result_bytes: self.semantic_result_bytes.saturating_add(bytes),
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
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(default)]
pub struct ResolutionBudget {
    events: Option<usize>,
    effects: Option<usize>,
    work_mutations: Option<usize>,
    subresolution_depth: Option<usize>,
    subresolution_count: Option<usize>,
    entropy_requests: Option<usize>,
    entropy_bytes: Option<usize>,
    entropy_request_bytes: Option<usize>,
    semantic_queries: Option<usize>,
    semantic_results: Option<usize>,
    semantic_result_bytes: Option<usize>,
    semantic_depth: Option<usize>,
    semantic_filters: Option<usize>,
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
            entropy_requests: None,
            entropy_bytes: None,
            entropy_request_bytes: None,
            semantic_queries: None,
            semantic_results: None,
            semantic_result_bytes: None,
            semantic_depth: None,
            semantic_filters: None,
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

    /// Sets the maximum number of mediated entropy requests for one root.
    #[must_use]
    pub const fn with_max_entropy_requests(mut self, limit: usize) -> Self {
        self.entropy_requests = Some(limit);
        self
    }

    /// Sets the maximum total mediated entropy bytes for one root.
    #[must_use]
    pub const fn with_max_entropy_bytes(mut self, limit: usize) -> Self {
        self.entropy_bytes = Some(limit);
        self
    }

    /// Sets the maximum bytes permitted in one mediated entropy request.
    #[must_use]
    pub const fn with_max_entropy_request_bytes(mut self, limit: usize) -> Self {
        self.entropy_request_bytes = Some(limit);
        self
    }

    /// Returns the maximum number of mediated entropy requests.
    #[must_use]
    pub const fn max_entropy_requests(self) -> Option<usize> {
        self.entropy_requests
    }

    /// Returns the maximum total mediated entropy bytes.
    #[must_use]
    pub const fn max_entropy_bytes(self) -> Option<usize> {
        self.entropy_bytes
    }

    /// Returns the maximum bytes permitted in one mediated entropy request.
    #[must_use]
    pub const fn max_entropy_request_bytes(self) -> Option<usize> {
        self.entropy_request_bytes
    }

    /// Returns the configured semantic query limit.
    #[must_use]
    pub const fn max_semantic_queries(self) -> Option<usize> {
        self.semantic_queries
    }

    /// Returns the configured semantic hit limit.
    #[must_use]
    pub const fn max_semantic_results(self) -> Option<usize> {
        self.semantic_results
    }

    /// Returns the configured semantic result-byte limit.
    #[must_use]
    pub const fn max_semantic_result_bytes(self) -> Option<usize> {
        self.semantic_result_bytes
    }

    /// Returns the configured semantic depth limit.
    #[must_use]
    pub const fn max_semantic_depth(self) -> Option<usize> {
        self.semantic_depth
    }

    /// Returns the configured semantic filter-count limit.
    #[must_use]
    pub const fn max_semantic_filters(self) -> Option<usize> {
        self.semantic_filters
    }

    /// Sets the maximum semantic queries per root execution.
    #[must_use]
    pub const fn with_max_semantic_queries(mut self, limit: usize) -> Self {
        self.semantic_queries = Some(limit);
        self
    }

    /// Sets the maximum semantic hits per root execution.
    #[must_use]
    pub const fn with_max_semantic_results(mut self, limit: usize) -> Self {
        self.semantic_results = Some(limit);
        self
    }

    /// Sets the maximum semantic result bytes per root execution.
    #[must_use]
    pub const fn with_max_semantic_result_bytes(mut self, limit: usize) -> Self {
        self.semantic_result_bytes = Some(limit);
        self
    }

    /// Sets the maximum semantic query depth per root execution.
    #[must_use]
    pub const fn with_max_semantic_depth(mut self, limit: usize) -> Self {
        self.semantic_depth = Some(limit);
        self
    }

    /// Sets the maximum semantic filter count per query.
    #[must_use]
    pub const fn with_max_semantic_filters(mut self, limit: usize) -> Self {
        self.semantic_filters = Some(limit);
        self
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
            (
                BudgetDimension::EntropyRequests,
                self.entropy_requests,
                usage.entropy_requests,
            ),
            (
                BudgetDimension::EntropyBytes,
                self.entropy_bytes,
                usage.entropy_bytes,
            ),
            (
                BudgetDimension::EntropyRequestBytes,
                self.entropy_request_bytes,
                usage.entropy_request_bytes,
            ),
            (
                BudgetDimension::SemanticQueries,
                self.semantic_queries,
                usage.semantic_queries,
            ),
            (
                BudgetDimension::SemanticResults,
                self.semantic_results,
                usage.semantic_results,
            ),
            (
                BudgetDimension::SemanticResultBytes,
                self.semantic_result_bytes,
                usage.semantic_result_bytes,
            ),
            (
                BudgetDimension::SemanticDepth,
                self.semantic_depth,
                usage.semantic_depth,
            ),
            (
                BudgetDimension::SemanticFilters,
                self.semantic_filters,
                usage.semantic_filters,
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
