# Chronicle Product Definition

## Vision

Chronicle is an interactive historical-world application built on Loom.

Its goal is not to present history as a flat list of dated facts, but as a world that can be entered at any moment and explored through time, entities, relationships, events, causes, sources, and eventually counterfactual forks.

A user should be able to ask four natural questions:

1. **What did the world look like then?**
2. **What did this person or entity experience?**
3. **Why did this happen?**
4. **What if history had diverged here?**

## Long-term growth model

Chronicle starts with a narrow, high-density historical slice, but all data belongs to one global historical corpus.

A Three Kingdoms dataset is not a Three Kingdoms application or a separate world model. It is one coverage pack within the same historical knowledge system. Additional packs can extend backward, forward, and geographically until the product naturally becomes Chinese history and then world history.

Product views such as “Three Kingdoms”, “Chinese History”, “World War I”, and “World History” are scopes over the same corpus, not separate storage or runtime silos.

## Core product pillars

### Time

Users can navigate to a historical date or period and inspect the world state associated with it.

### World

Chronicle shows concurrent historical context rather than isolated national timelines. As coverage grows, the same date can reveal what was happening across multiple regions and civilizations.

### People and entities

Users can inspect persistent identities and their trajectories across time: people, polities, organizations, places, armies, ideas, technologies, and other historical entities.

### Why

Events can expose sourced causal explanations, contributing factors, structural conditions, and competing interpretations. Chronicle must distinguish historical fact from interpretation.

### Sources

Historical claims must preserve source provenance, confidence, uncertainty, disagreement, and dating precision. Missing data must never be presented as proof that nothing happened.

### What If

Counterfactual simulation is a later capability. Historical truth before a fork and simulated outcomes after a fork must always be visually and semantically separated.

## V0 product surfaces

The first product version should focus on the historical browsing experience before advanced simulation.

1. Home
2. World at a historical moment
3. Timeline
4. Entity / person detail
5. Event detail
6. Why / causal exploration
7. Sources
8. Global search and historical Q&A

Later additions:

- Historical map
- Relationship graph
- “What happened at the same time?” comparison
- Guided learning paths
- Coverage visualization
- Counterfactual fork and simulation

## Global interaction model

The most distinctive persistent UI element should be a global historical time control. Changing time should update the currently visible world, relationships, entity state, territorial context, and relevant events where supported by the corpus.

The product should make the following distinction explicit:

- **Historical mode:** sourced historical corpus and historical uncertainty.
- **Simulation mode:** a counterfactual Loom Timeline created from a historical fork point.

They must never be silently mixed.
