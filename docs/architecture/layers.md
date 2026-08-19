# Loom Five-Layer Architecture

> Status: confirmed top-level architecture boundary.
>
> This document defines where responsibilities belong. When a new concept is introduced, the first question should be: **which layer owns it?**

## 1. Overview

Loom is organized around five top-level concepts:

```text
                 Loom Core
                    ↓
           Capability Modules
                    ↓
             World Template
                    ↓
                  World
                    ↑
                    │
               Application
```

These are not five deployment tiers. They are architectural ownership boundaries.

The central distinction is:

- **Core** defines how a persistent intelligent world can exist and run.
- **Capability Module** adds reusable domain/world abilities.
- **World Template** composes capabilities, rules, and defaults into a reusable kind of world.
- **World** is the actual persistent running instance.
- **Application** is the user-facing product that creates, controls, observes, analyzes, or interacts with Worlds.

## 2. Core

### Definition

**Loom Core is the persistent world runtime and the set of domain-neutral world primitives.**

Core answers questions such as:

- How does a World persist and evolve?
- How is time represented and advanced?
- How are Events validated, committed, ordered, replayed, and forked?
- How are State, Entity, Relationship, Agent, Institution, and Timeline represented at the runtime level?
- How does information enter the system without immediately becoming World Truth?
- How is Agent perception isolated from omniscient World State?
- When does an Agent wake, what context can it receive, and when is model cognition actually necessary?
- How do Actions, Affordances, Rules, Memory, Context, and Scheduler interact?

### Core primitives currently established

```text
World
Timeline
World Constitution / Runtime Revision

Entity
Agent
Collective Entity / Institution
Relationship
State

Event
Event Ledger
Snapshot
Clock
Scheduler

Observation
Information Artifact
Claim
Information Space
Channel / Propagation
Exposure / Perception

Agent Knowledge / Belief
Agent Entity Representation
Memory
Need / Goal / Plan / Decision / Intent
Affective State
Context Frame

Action Definition
Affordance
Rule / Norm / Enforcement mechanism
Runtime Commit Authority
```

The exact implementation of these primitives remains subject to later technical design, but their conceptual boundaries are part of the architecture baseline.

### Core does not own domain semantics

Core should not intrinsically know what the following mean:

```text
salary
stock
marriage
job promotion
bank account
combat damage
spell
quest
campaign polling
insurance
medical diagnosis
```

Those meanings belong above Core.

## 3. Capability Module

### Definition

**A Capability Module contributes a reusable kind of world/domain ability on top of Core primitives.**

It is not a complete application and does not own the World lifecycle.

Examples may include:

```text
social
employment
family
economy
health
education
media
politics
finance
combat
inventory
magic
mobility
```

A Capability Module may define domain-specific combinations of:

- Entity/State schemas;
- Relationship types;
- Action definitions;
- Affordance semantics;
- Rule/Norm definitions;
- process semantics;
- Context facets;
- domain-specific memory/knowledge structures;
- source/import semantics;
- analysis projections.

However, runtime data produced by those semantics still belongs to the World/Timeline lifecycle managed by Core.

### Reuse principle

A capability is intended to be reusable across multiple products and world types.

For example:

```text
social
├── Life Simulation Application
├── Public Opinion Application
└── RPG Application

economy
├── Life Simulation Application
├── Strategy Game Application
└── Business Simulation Application
```

The goal is to avoid reimplementing the same world semantics independently inside each Application.

### Composition principle

Capability Modules may coexist in a World, but they should not become an uncontrolled mesh of internal implementation calls. Their shared behavior should be expressed through Core-owned primitives, declared semantics, capabilities, Events, Relationships, Actions, Rules, and runtime coordination.

The detailed Capability Module contract is intentionally **not yet frozen** in this document and remains a later design topic.

## 4. World Template

### Definition

**A World Template is a reusable composition of capabilities, rules, defaults, and configuration for creating a class of Worlds.**

A Template is not a running World and not a user-facing Application.

Examples:

```text
modern-human-life
modern-society
real-world-mirror
corporate-society
medieval-fantasy
```

For example, a `modern-human-life` template might compose:

```text
human/social capability
employment capability
family capability
economy capability
health capability
institution/government capability
media/information capability

+ default rule sets
+ default capability configuration
+ default world constitution/profile
```

A Template therefore answers:

> "If I want to create this kind of world, what reusable capabilities and default rules/configuration should be assembled?"

Templates should remain versionable because future Worlds may use newer standards while existing Worlds preserve their historical semantics.

## 5. World

### Definition

**A World is the actual persistent world instance running under Loom Runtime.**

A World has a stable identity and contains or references its actual runtime data, including:

```text
World identity
Capability bindings
World constitution / rule revisions
Timelines
Entities and Agents
Institutions and Relationships
State projections
Event history
Information state
```

A World is not an API request, simulation job, report, or application session.

### Timeline relationship

A World may contain multiple Timelines:

```text
World
├── Main Timeline
├── Prediction Timeline A
├── Counterfactual Timeline B
└── Correction / Experiment Timeline C
```

The World defines the shared universe identity/configuration boundary; a Timeline represents one concrete historical evolution/runtime branch of that World.

### World is not Application

The same World may be observed or manipulated by multiple Applications, subject to permissions and product semantics.

For example, one persistent real-world mirror could potentially be consumed by:

```text
Public Opinion Application
Risk Analysis Application
Prediction Application
Research/Observer Application
```

without duplicating the underlying World merely because the product experience differs.

## 6. Application

### Definition

**An Application is an upper-layer product built with Loom.**

It defines what users are trying to accomplish and how they interact with one or more Worlds.

Examples:

```text
Life Simulator
RPG / Strategy Game
Public Opinion Analysis
Prediction / Scenario Analysis
Social Experiment Platform
Decision Sandbox
Reality Mirror Dashboard
```

Applications may:

- create Worlds from Templates;
- choose/configure capabilities;
- interact with existing Worlds;
- observe one or more Timelines;
- present narrative or visual projections;
- provide user intervention tools;
- perform analysis/reporting;
- fork scenarios for experiments or prediction.

An Application should not redefine Core semantics merely because its user experience is different.

### Product vs world distinction

A game is a product experience, not necessarily a special type of Runtime.

A single underlying World might be exposed as:

```text
Game UI
Narrative experience
Research dashboard
Automated simulation observer
```

without changing the fundamental World runtime model.

## 7. Examples

### Life Simulation

```text
Application:
Life Simulator

World Template:
modern-human-life

Capabilities:
social
employment
family
economy
health
media
institution

Core:
standard Loom world runtime
```

### RPG

```text
Application:
RPG Game

World Template:
medieval-fantasy

Capabilities:
social
character
inventory
combat
quest
economy
magic

Core:
standard Loom world runtime
```

### Public Opinion Analysis

```text
Application:
Public Opinion Analysis

World Template:
modern-society / real-world-mirror

Capabilities:
social
media
institution
information propagation
source ingestion
analysis projections

Core:
standard Loom world runtime
```

The domain changes. The Core world model does not.

## 8. Ownership test

When adding a new concept, use this test:

- If it defines **how every Loom world can exist/run**, it belongs in **Core**.
- If it defines a **reusable kind of world/domain ability**, it belongs in a **Capability Module**.
- If it defines a **reusable composition of capabilities/rules/defaults**, it belongs in a **World Template**.
- If it is **persistent runtime data/history for one created universe**, it belongs to a **World/Timeline**.
- If it defines **what a user does with Loom or how the experience is presented**, it belongs in an **Application**.

If a feature seems to belong to multiple layers, split the responsibilities instead of collapsing the boundaries.

## 9. Stable boundary

The following distinction is now part of Loom's architecture baseline:

> **Core -> Capability Module -> World Template -> World <- Application**

Future design discussions should preserve this separation unless a later explicit architecture decision supersedes it.
