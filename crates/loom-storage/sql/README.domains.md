# Domain ownership map

- `health/`: database reachability only
- `transaction/`: transaction-local adapter statements
- `world/`: materialized World snapshot reads
- `timeline/`: Timeline metadata/logical state
- `event/`: authoritative committed Event history and associations
- `work/`: durable Work reads and operational claim/retry state
- `binding/`: immutable World Runtime Binding metadata
- `runtime_revision/`: Platform Runtime Revision history/selection
- `logical_journal/`: Timeline Logical Journal persistence
- `session/`: Execution Session/provenance persistence
- `ancestry/`: replay/fork ancestry/history queries
- `ingress/`: durable Ingress operational state
- `projection/`: rebuildable semantic/pgvector projections
