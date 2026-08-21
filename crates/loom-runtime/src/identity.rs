//! Runtime-owned technical identity allocation boundary.
//!
//! Core carries strong identity values but deliberately does not choose a clock
//! or entropy source. Runtime owns when World/Timeline identities are allocated,
//! while applications/tests may inject a deterministic allocator. Capability
//! resolution and the public Loom API never receive the allocator itself.

use loom_core::{TimelineId, WorldId};

/// Allocates fresh technical identities for Runtime-owned World lifecycle work.
///
/// Implementations select the UUID/time/random mechanism. Returned values are
/// technical identity only: their ordering is not World history, their clock is
/// not World Time, and possession of an ID grants no commit authority. Runtime
/// requires non-nil results before lifecycle persistence is attempted.
pub trait IdentityAllocator {
    /// Allocates a fresh World identity.
    fn allocate_world_id(&self) -> WorldId;

    /// Allocates a fresh Timeline identity.
    fn allocate_timeline_id(&self) -> TimelineId;
}

/// Default Runtime allocator using RFC 9562 UUID version 7 identities.
///
/// `UUIDv7`'s platform timestamp/randomness is used only to create sortable
/// technical identifiers. It never determines semantic World Time or Timeline
/// Event order; committed Event ordering remains `EventSeq`.
#[derive(Clone, Copy, Debug, Default)]
pub struct UuidV7IdentityAllocator;

impl IdentityAllocator for UuidV7IdentityAllocator {
    fn allocate_world_id(&self) -> WorldId {
        WorldId::from_uuid(uuid::Uuid::now_v7())
    }

    fn allocate_timeline_id(&self) -> TimelineId {
        TimelineId::from_uuid(uuid::Uuid::now_v7())
    }
}

#[cfg(test)]
mod tests {
    use super::{IdentityAllocator, UuidV7IdentityAllocator};

    #[test]
    fn default_allocator_produces_non_nil_v7_identifiers() {
        let allocator = UuidV7IdentityAllocator;
        let world = allocator.allocate_world_id();
        let timeline = allocator.allocate_timeline_id();

        assert!(!world.is_nil());
        assert!(!timeline.is_nil());
        assert_eq!(world.as_uuid().get_version_num(), 7);
        assert_eq!(timeline.as_uuid().get_version_num(), 7);
        assert_ne!(world.to_string(), timeline.to_string());
    }
}
