# Chronicle UI / Product Surface V0

> 第二轮按来源连续阅读的布局、时间轴、事件预览和返回契约见 [reading-experience.md](reading-experience.md)，数据组织见 [continuous-reading.md](continuous-reading.md)。2026-09-11 确认的正式前台方向为正序多史料历史流，事件／时期仅作阅读锚点；左轴、中间正文、右上附近事件、右下人物／地点当时状态。最新要求与人物页职责见 [historical-narrative-design.md](historical-narrative-design.md)。直接替换正式前台，独立原型不再作为交付目标；下文长期多轨／世界状态／地图方向不扩大 R2 验收。

## Design goal

Chronicle should feel like entering a historical world, not browsing an encyclopedia.

The primary user journey is organized around four questions:

1. What did the world look like then?
2. What did this person or entity experience?
3. Why did this happen?
4. What if history had diverged here?

The first release should make the first three excellent and preserve clear source provenance. Counterfactual simulation comes later.

## Global navigation

The homepage offers important periods and events as entry points into continuous
historical reading, with search available throughout. Event and period entries
locate a passage without filtering the main narrative. People have separate
detail pages. Source books and chapters are reached through evidence inspection.
Later navigation may include:

- Home
- Explore
- Timeline
- Map
- People / Entities
- Learn

A global search / question box is always available.

In the current React front the public nav is 世界 / 时间线 / 搜索 / 篇章 /
连续阅读 / Studio. 篇章 (`/chapters`) lists published immutable reading
versions; `/chapters/{publication_id}` renders the complete single-column
vernacular text with on-demand source references (see chapter-production
§§7–8). Direct open and refresh of both paths serve the SPA shell from the
Rust front; API failures stay typed JSON and never fall back to the shell.
Reader states: loading, empty directory, 404 for unpublished or unknown
versions, request error with retry, source panel (window → chapter-wide)
with close restoring the reading position.

Continuous reading (second round, C2-R2-T15) adds `/read` and
`/read/{stream_id}?catalog={sha}&at={unit_id}`. `/read` lists published
reading streams and fixes the exploration snapshot; entering a stream
combines the content window, the narrative-time side axis, the single active
unit controller, event-word previews and the current-person/place panel.
The reading page replaces the global HistoricalTimeBar with a compact bar
showing only the active unit's server-compiled narrative time; an explicit
“在历史时间线查看” link converts a single exact normalized year into the
existing timeline filter, and never rewrites the reading URL. Event and
entity detail pages accept an optional `catalog` snapshot and can return to
the exact reading locator through a same-site return token. Direct deep
links, refresh and browser back/forward are supported. Longer-term tracks,
map and why surfaces remain out of scope.

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

The main content is a chronological, continuous narrative synthesized from the
available sources. A restrained left axis locates the current historical stage.
The right side shows nearby event anchors above compact rows for people and
places, including their evidenced state at the active passage. Personal actions
belong in detailed life history. Original material is available through deeper
inspection. Event terms open a light preview and can locate their anchors in the
same historical flow, with a return to the previous reading position.

The page should explain how the moment developed and what was happening around
it. Concurrent regional context, richer lenses and a historical map can extend
this surface when the data supports them; missing spatial or political state must
not be invented to fill the layout.

## Page 3 — Timeline

The current design prioritizes continuous chronological reading. Periods and
events are navigation anchors; their boundaries do not end or filter the reading
flow. There is no fixed background/course/aftermath division. Multiple comparative
tracks are a later extension over the same historical corpus.

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
