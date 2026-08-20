# Loom World Evolution and Software Change

> Status: confirmed architectural baseline.
>
> This document corrects an earlier software-oriented interpretation of Capability and World versioning. A Loom World does not conceptually "upgrade" as reality evolves. Worlds evolve through their own history; software implementations may be upgraded independently.

## 1. Core distinction

> **Worlds evolve; software upgrades. Never confuse the two.**
>
> **世界只会演化，软件才会升级。**

A World is not a deployed software package whose domain rules are periodically replaced by a newer release. Once created, a World has its own authoritative Timeline, Event history, State, Rules, capabilities and causal evolution.

Real-world-like change is represented as history:

```text
old rule / old state
        ↓
World Event
        ↓
new rule / new capability / new state becomes effective
        ↓
future events resolve under the new conditions
```

Past committed history is not rewritten merely because later rules, technologies, institutions, conventions or capabilities emerge.

## 2. Rule evolution is historical, not an upgrade

A new law, policy, convention or rule does not upgrade the past. It becomes applicable from its effective time according to its own scope and temporal semantics.

Example:

```text
Rule A
valid: 2025-01-01 → 2026-05-31

Rule B
valid: 2026-06-01 → ...
```

Events resolved while Rule A was effective remain historical facts. Events after Rule B becomes effective use Rule B where applicable.

Rules may be introduced, activated, superseded, revoked, expired or replaced. These are World events and state changes, not software upgrades.

## 3. New abilities emerge in the World

The existence of an implementation capable of modeling an ability does not mean that ability already exists or is usable in every World or Timeline.

For example, Loom may have an implementation capable of modeling digital payments while a historical or fictional World has not yet developed them.

Distinguish three layers:

### Implementation Availability

Whether the Loom installation has code capable of expressing and resolving a semantic capability.

### World Semantic Availability

Whether a particular World uses that semantic model at all.

### Runtime Affordance Availability

Whether a particular Entity, at a particular time on a particular Timeline, can actually attempt or use that ability given its State, relationships, resources, knowledge, access and current rules.

These must never collapse into one `enabled` flag.

## 4. Capability Modules provide semantics; they do not rewrite history

Capability Modules define reusable semantic mechanisms that Loom Core can host, such as domain State Facets, Relationship Definitions, Action Definitions, Resolvers and Rules.

They are implementation artifacts. Their package or implementation versions belong to software engineering and reproducibility metadata, not to World Truth.

A World does not know that it is running `employment.basic@1.3.2`. Agents do not perceive package versions unless an Application explicitly models such software metadata as part of that World.

A newer Capability implementation must not silently reinterpret or rewrite committed Events.

## 5. Software upgrade is semantically invisible by default

Core and Capability implementations may evolve for reasons such as:

- bug fixes;
- performance improvements;
- storage changes;
- API compatibility;
- improved indexing;
- safer Runtime behavior;
- implementation refactoring.

By default these changes must preserve World semantics.

For example, replacing a JSON storage representation with normalized tables is a technical migration. It must not create World Events or change Entity identities, Timeline history or previously committed outcomes.

> **Technical migration must be semantically invisible to the World.**

## 6. If implementation semantics change, history still remains immutable

If an old implementation contained a semantic bug or produced an outcome that a new implementation would resolve differently, already committed history remains history.

```text
old implementation
        ↓
Committed Event A
        ↓
Committed Event B
```

Deploying corrected software does not recompute Event A or Event B.

The corrected implementation may affect future resolutions from the point at which it is used.

If the desired question is:

> What would this World have become if the corrected semantics had applied earlier?

that is a counterfactual or corrected historical branch:

```text
Fork at an earlier point
        ↓
Replay / continue using corrected semantics
        ↓
new Timeline
```

The original Timeline remains untouched.

## 7. World Template is a birth recipe, not a subscription

A World Template composes initial semantic capabilities, rules, configuration and initial conditions for creating a World.

```text
World Template
      ↓
Create World
      ↓
Initial State / Rules / Capability semantics
      ↓
World begins its own history
```

After creation, the World is not continuously synchronized with later Template changes.

A later Template revision affects newly created Worlds unless an Application explicitly uses it to create or construct something else. Existing Worlds continue from their own Timeline and State.

> **Template defines how a World is born; it does not continuously control how that World lives.**

## 8. World Constitution should remain narrow

World Constitution must not become a revision counter for ordinary social, legal, technological or institutional change.

Ordinary world evolution belongs to Event, Rule, State and Capability availability within the Timeline.

Constitution should be reserved for genuinely foundational runtime/world-definition constraints that cannot be represented as normal in-world evolution. Its exact minimal scope remains subject to further Core closure review.

## 9. Three independent change mechanisms

Loom must keep these mechanisms conceptually separate:

```text
World Evolution
Rule / State / capability availability changes
→ represented by World history
→ affects the effective present/future according to temporal semantics

Software Evolution
Core / Capability implementation changes
→ deployment and implementation concern
→ semantically invisible by default

Historical Alternative
Different past facts or semantics are desired
→ Fork / Replay
→ produces another Timeline
→ never overwrites the original Timeline
```

## 10. Confirmed laws

1. **Worlds evolve; software upgrades.**
2. A World has no generic domain-level `upgrade` operation.
3. New rules affect the periods in which they are effective; they do not retroactively rewrite committed history.
4. New technologies, practices and abilities appear through World events and state evolution rather than package-version changes.
5. Capability implementation availability, World semantic availability and Entity runtime affordance availability are distinct.
6. Capability package versions are implementation/reproducibility metadata, not World Truth.
7. Technical migrations must be semantically invisible to the World.
8. If corrected software would have changed past outcomes, use Fork/Replay for the alternative history rather than rewriting the original Timeline.
9. A World Template is an initial creation recipe; existing Worlds are not continuously synchronized to later Template changes.
10. World Constitution must remain narrow and must not be used as a catch-all mechanism for ordinary world evolution.
11. Once a World is created, its Timeline, Event Ledger, State and Rules become the authority for how that World has actually evolved.
