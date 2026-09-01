# Chronicle Resolution v0.1

Chronicle extraction is source-owned. Resolution is a later derived layer that relates records across independently ingested sources without rewriting either source bundle.

## Data lifecycle

```text
Raw source A -> staged bundle A ─┐
                                 ├─ Resolution Links -> later canonical publication
Raw source B -> staged bundle B ─┘
```

The staged bundles remain auditable records of what each source says. Resolution never erases source perspective.

## Entity resolution

An Entity link answers whether two staged Entity candidates refer to the same historical identity.

V0 decisions:

- `same_entity`
- `not_same`
- `uncertain`

A shared name is only a candidate signal. Names are not identity.

## Event resolution

An Event link answers whether two source Event records describe the same underlying historical occurrence.

V0 decisions:

- `same_occurrence`
- `related_occurrence`
- `not_same`
- `uncertain`

This distinction matters because source boundaries differ. One biography may describe a campaign as one coarse Event while another splits it into several actions. Those records may be related without being identical.

## Candidate blocking vs semantic resolution

Deterministic code is allowed to narrow the pair search space using mechanically available structure, but blocking must not turn weak shared context into an identity decision.

### Entity blocking

V0 Entity candidates require:

- the same Entity type; and
- at least one exact stable surface shared across canonical name, aliases, or non-contextual mentions.

This intentionally avoids fuzzy-name identity matching in the first pass.

### Event blocking

All Event candidates require compatible historical time. When both sources provide season or month and those values conflict, the pair is rejected.

Broad Event families such as `military`, `battle`, and `movement` require stronger structural overlap:

- at least one shared participant; and
- at least one shared place.

Narrow types such as `death`, `birth`, `surrender`, `retreat`, and `epidemic` may qualify when the exact Event type and at least one participant match even if one source omits place detail.

Two or more shared participants are also sufficient to send a pair to semantic adjudication.

This prevents high-frequency actors such as a ruler or commander, combined only with a broad year and broad Event type, from generating large numbers of meaningless candidate pairs.

Candidate blocking never creates a canonical merge by itself.

A closed-world resolver agent receives only blocked candidate pairs and decides their relationship. It may not invent canonical UUIDs, add outside historical knowledge, or rewrite source refs.

## Resolution link identity

V0 resolution output uses candidate IDs such as:

```text
ec_001
vc_001
```

These are run-local link identifiers, not published historical identity.

The final link records retain both bundle labels and staged record refs so every decision is traceable back to the two source-owned records.

## Confidence

`confidence` on a resolution link means confidence that the link decision is correct.

It is not:

- extraction confidence;
- historical truth confidence;
- source reliability.

These concepts remain separate.

## Canonical publication is deferred

C0-T7 deliberately stops before canonical publication. It does not assign UUIDv7 IDs or create canonical Entity/Event rows.

A later publication layer may consume accepted resolution links to decide whether to:

- attach a staged Entity to an existing canonical Entity;
- create a new canonical Entity;
- group multiple source Events under one canonical Event;
- keep related-but-distinct Events separate;
- preserve ambiguity for later review.

The source bundles and source Claims remain intact regardless of that later decision.
