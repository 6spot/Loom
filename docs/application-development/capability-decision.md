# Capability decision guide

Not every application feature should become a Loom Capability.

## Keep logic in the application when

The behavior is mainly:

- UI/presentation;
- workflow orchestration over existing public Loom operations;
- import/export transformation;
- product-specific policy that does not define reusable World semantics;
- derived search/indexing over public reads;
- external integration glue.

## Consider a Capability when

The behavior defines reusable semantic rules that should participate in Loom execution, for example:

- new domain Actions with deterministic semantic effects;
- durable Facet/Event behavior owned as part of World semantics;
- reusable validation or reaction rules required across multiple applications;
- semantics that must be replay/fork consistent under Loom Runtime authority.

## Warning signs

Do not create a Capability merely because application code feels large.

Do not modify Runtime merely because an application needs a new domain operation.

Do not give a Capability direct Storage or Runtime ownership to simplify an application workflow.

## Decision path

Use this order:

```text
Can existing public Loom semantics express it?
        ↓ yes
keep it in the application
        ↓ no
Is this reusable World semantic behavior?
        ↓ yes
consider a Capability
        ↓ no
keep it application-owned or redesign the product workflow
```

A Capability that changes architecture authority or introduces new cross-layer semantics still follows the repository Architecture Amendment rules where applicable.
