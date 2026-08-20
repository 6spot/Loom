# Loom Applications

User-facing Loom Applications and composition roots live here.

## Unified API rule

Applications consume Loom through `loom-api` rather than importing concrete Capability modules, Storage repositories or Runtime internals as their feature surface.

```text
loom-cli / loom-studio / external client
                ↓
              loom-api
```

`loom-server` is the main composition root and is allowed to know the concrete implementations required to assemble a running process:

```text
Runtime
Storage adapter
Boundary adapter
selected Capability implementations
selected Cognitive Provider adapters
Clock / Entropy implementations
```

That composition privilege must not leak into ordinary Application feature code. After assembly, externally consumable engine behavior is presented through the unified Loom API contract.

## UI direction

The official UI direction is GPUI, with the goal of sharing Rust UI code across native targets and the emerging GPUI Web/WASM backend. The first UI crate will be added only after we pin and validate a concrete GPUI upstream revision.

`loom-studio` will be a `loom-api` consumer. GPUI must not become a dependency of Core, Protocol, Capability, Agency, Runtime or Storage.

See `docs/architecture/governance.md` for the mandatory dependency and public exposure rules.
