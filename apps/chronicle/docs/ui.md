# Chronicle UI / Product Surface V0

## Design goal

Chronicle should feel like entering a historical world, not browsing an encyclopedia.

The primary user journey is organized around four questions:

1. What did the world look like then?
2. What did this person or entity experience?
3. Why did this happen?
4. What if history had diverged here?

The first release should make the first three excellent and preserve clear source provenance. Counterfactual simulation comes later.

## Global navigation

Primary navigation:

- Home
- Explore
- Timeline
- Map
- People / Entities
- Learn

A global search / question box is always available.

Contextual surfaces can expose:

- Events
- Relationships
- Why / causes
- Sources
- Simulation

## Global World Time Bar

Chronicle should have a persistent historical-time control across major exploration surfaces.

Example:

```text
180      190      200      208      220      230
──────────●────────●────────●────────●──────────
                           ↑
                         208 CE
```

Changing time should update the currently visible historical projection where corpus coverage supports it:

- entity state
- relationships
- political context
- territorial context
- relevant events
- concurrent world context

This should become Chronicle's most recognizable interaction pattern.

## Page 1 — Home

Purpose: provide immediate entry into history.

Hero:

> Go to any moment in history and see what the world was becoming.

Primary input supports dates, entities, events, and natural-language questions.

Examples:

- 208 CE
- Battle of Red Cliffs
- Cao Cao
- What was happening in Rome when Red Cliffs occurred?
- Why did World War I begin?

Below the hero:

- featured historical moments
- popular entities
- guided entry points
- recently expanded corpus coverage

## Page 2 — World at a historical moment

Example: `World · 220 CE`

This is Chronicle's primary page.

Main regions:

- world / regional map or spatial overview
- important events around the selected time
- major people and polities
- “happening at the same time” context
- current lens selector
- global time bar

The page should answer “what did the world look like at this moment?” rather than merely listing dated records.

## Page 3 — Timeline

Timeline supports multiple tracks rather than only a vertical event list.

Possible tracks:

- polity
- person
- region
- war
- politics
- economy
- culture
- technology
- religion

Example:

```text
                   200        208        220
China politics      ●──────────●──────────●
Cao Cao             ●──────────●──────────●
Liu Bei                        ●──────────●
Roman Empire       ─────────────────────────
```

Users can add or remove tracks and compare concurrent trajectories.

## Page 4 — Entity / person detail

Example: Cao Cao.

Primary sections:

- identity summary
- life / entity trajectory
- state at selected historical time
- relationships at selected time
- relevant events
- places
- sources and uncertainty

Timeline nodes are interactive and can shift the global historical time.

Relationships are time-dependent and should update as time changes.

## Page 5 — Event detail

Example: Battle of Red Cliffs.

Primary sections:

- overview
- dating and location
- participants
- sequence
- consequences
- why / causal explanations
- related entities and events
- sources
- uncertainty / disputes

Suggested tabs:

- Overview
- Participants
- Sequence
- Impact
- Why
- Sources

## Page 6 — Why / causal exploration

A visual causal graph explains how an event emerged from prior events, decisions, and structural conditions.

Each causal edge or node must preserve epistemic status, for example:

- historical fact
- strong scholarly consensus
- interpretation
- disputed

Chronicle should not present one interpretation as unquestioned truth when the corpus contains competing claims.

Users should be able to recursively ask “why?” and expand deeper causal context.

## Page 7 — Sources

Every significant historical assertion should be inspectable.

The source surface should expose:

- primary sources
- later historical records
- modern research
- claim provenance
- dating confidence
- disputed values
- competing interpretations

Chronicle should make uncertainty useful for learning rather than hiding it.

## Page 8 — Global search / historical Q&A

Search should resolve against the historical corpus before generating prose.

Supported query types:

- entity
- event
- date / period
- place
- relationship
- natural-language historical question

Answers should link back into concrete Chronicle surfaces such as:

- timeline
- event detail
- entity detail
- sources
- historical moment

AI is a query and explanation interface over the corpus, not the authority that creates historical fact.

## Later surface — “What happened at the same time?”

Users can lock a date and compare regions or civilizations.

Example:

```text
208 CE

China        Battle of Red Cliffs
Rome         Severan period
Persia       Parthian context
India        contemporary regional context
```

This surface becomes more valuable automatically as corpus coverage expands.

## Later surface — Historical map

The map is time-aware. Territory, polity, and relevant contextual layers change with the selected historical time.

The map should never fabricate precision where historical geography is uncertain.

## Later surface — Learning paths

A learning path is a guided journey through the same historical world rather than a separate article system.

Example:

`30 minutes to understand the Three Kingdoms`

Each step moves the user to a real event, person, or historical moment in Chronicle.

## Later surface — Counterfactual simulation

Historical mode and simulation mode must be explicitly separated.

Example:

```text
Actual history
184 ─────── 208 ─────── 220 ─────── 280
              │
              └── Fork: Cao Cao wins Red Cliffs
                   208 ───── ??? ───── ???
```

Before the fork:

- sourced historical corpus

After the fork:

- Loom Runtime simulation
- explicit model / ruleset / revision provenance
- no automatic injection of historical future facts

The UI should visibly warn the user that they are leaving recorded history and entering simulation.

## Lens system

Major exploration surfaces should support semantic lenses such as:

- All
- Politics
- War
- People
- Economy
- Culture
- Technology
- Religion

A lens changes emphasis and filtering, not underlying historical truth.

## Coverage visibility

Chronicle should expose historical-data coverage rather than implying that missing records mean nothing happened.

Long-term coverage views can show density by:

- time
- region
- subject domain
- source quality

This also becomes an internal planning tool for deciding which dataset packs should be expanded next.

## V0 scope

Required:

1. Home
2. World at a historical moment
3. Timeline
4. Entity / person detail
5. Event detail
6. Why / causal exploration
7. Sources
8. Global search / historical Q&A

V0.5 candidates:

- historical map
- relationship graph
- same-time comparison
- guided learning paths
- corpus coverage visualization

V1 candidate:

- counterfactual fork and Loom-powered simulation

The V0 should first prove that Chronicle is already compelling as a historical exploration and learning product without relying on AI counterfactual generation.
