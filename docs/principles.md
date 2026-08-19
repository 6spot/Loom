# Loom Core Design Principles

> Status: confirmed architectural baseline.
>
> This document records principles that have been explicitly agreed during Loom's architecture design. It is intentionally stricter and more stable than exploratory design notes. New implementation work should preserve these principles unless a later architecture decision explicitly supersedes them.

## 1. World and runtime

1. Loom Core is a **world runtime**, not a domain-specific simulator.
2. A World is a persistent object that continues to exist across requests, model calls, reports, pauses, and resumptions.
3. World State may only be changed through **committed World Events**.
4. The Event Ledger is append-only and immutable; previously committed history is never silently rewritten.
5. Current State is a materialized projection used for efficient execution and querying; it must remain reconstructible from retained history and snapshots.
6. Events store their fully resolved effects. Nondeterministic reasoning, randomness, or model inference may happen before commit, but committed outcomes are frozen.
7. A Timeline is a first-class historical/runtime branch of a World. Historical replay that changes causal outcomes creates a new Timeline instead of overwriting an existing one.
8. World Time, external occurrence time, Loom receipt time, effective/valid time, and commit order are separate concepts. Ledger sequence is the authoritative linear commit order.

## 2. Truth, information, and cognition

9. **World Truth, Information Space, and Agent Knowledge are separate layers.**
10. An external Observation records what a source reported or what Loom observed; it is not automatically World Truth.
11. A Claim is a reusable semantic proposition. Claims may be supported, contradicted, corrected, or interpreted differently by different Worlds and Agents.
12. An Information Artifact is the carrier of information, such as a report, filing, article, announcement, message, video, or internal document. Artifact, Observation, and Claim are distinct objects.
13. Truth does not automatically propagate. An Agent only knows information through an actual perception, communication, discovery, or accessible information path.
14. Awareness of a Claim is not belief in that Claim.
15. Agent belief may remain inconsistent with World Truth for long periods. Incorrect belief is a valid world state and may cause real Events.
16. Belief is private cognition; Expression is an action. An Agent may believe one thing and publicly express another.

## 3. Agent existence and computation

17. **Agent existence is persistent; Agent compute is on demand.**
18. Agents are dormant by default. A Stimulus may make an Agent eligible to wake, but a Stimulus does not imply an LLM call.
19. Runtime should use cheap deterministic routing, relevance filtering, policies, routines, heuristics, lightweight models, and batching before expensive cognition.
20. LLM reasoning is a last cognitive resource for important, novel, ambiguous, conflicting, or high-uncertainty decisions.
21. An Agent may wake and still choose `NO_ACTION`, `WAIT`, `DEFER`, or abandon a goal. The world must not force activity merely because cognition occurred.
22. Agent output is an Action Intent, not a direct State mutation. Runtime remains the sole authority that validates and commits Events.
23. Agent cognition must not directly access omniscient World State unless that Agent is explicitly modeled as omniscient. Context must respect the Agent's actual knowledge boundary.

## 4. Context and bounded cognition

24. **Context is budgeted attention.**
25. A Runtime Context Frame is a temporary projection of the relevant world slice, not a copy of World State and not a permanently maintained mega-object.
26. Actual Situation Context and Agent Perceived Context are separate.
27. Visibility/knowledge eligibility is evaluated before relevance. A secret does not enter an Agent's context merely because it is relevant.
28. Context is multi-faceted and may combine temporal, spatial, social, institutional, normative, goal, information, and domain-specific facets.
29. World Context -> Agent Context -> Cognitive Prompt Context are separate filtering stages.
30. Long-term memory may be large; Working Memory and prompt context must remain aggressively bounded.
31. Important Decisions may retain compact context references/revisions for auditability without copying the entire context.

## 5. Memory and learning

32. **World History is not Agent Memory.** What happened and what an Agent remembers are separate.
33. Experience does not automatically become long-term Memory. Memory encoding is selective and Agent-local.
34. Memory should conceptually distinguish episodic experience, semantic/entity knowledge, skill/procedural state, habit/policy, and working memory.
35. Knowledge/Belief represents current cognition; Memory records retained traces and the history from which cognition formed.
36. Forgetting primarily changes accessibility, fidelity, or recall strength; it does not delete Loom's historical evidence.
37. Repeated experience should consolidate into more compact Beliefs, Relationship patterns, Skills, Habits, or Policies rather than causing linear active-memory growth forever.
38. An Agent may reinterpret an old experience when new evidence arrives without rewriting the historical Event.
39. Memory retrieval may determine which people, paths, methods, and prior experiences an Agent can currently think of; recall can therefore create new perceived Affordances.

## 6. Goals, personality, emotion, and decision

40. Need, Goal, Plan, Decision, Intent, and Event are distinct concepts.
41. Goals describe desired states, not merely actions.
42. Agents may hold multiple conflicting Goals. Goal importance and urgency change over time.
43. Personality is a **bias, not destiny**. It affects decision tendencies but does not permanently forbid actions.
44. Values influence decisions but do not make otherwise feasible actions physically impossible.
45. Every major Decision is time-local: the same Agent may rationally choose differently on different days because Needs, Goals, Beliefs, Resources, Relationships, Mood, Pressure, or Context changed.
46. Agents are boundedly rational. They reason from their own limited knowledge and limited candidate set rather than optimizing from omniscient global state.
47. Emotion is a lightweight Agent-local state produced through appraisal of perceived events, not a fixed lookup from Event type.
48. Personality, Need Pressure, Emotion, and Mood are separate. Emotion and stress may change attention, recall, risk perception, goal priority, and decision style.
49. Internal affect is not automatically externally visible. Expression is separately decided and other Agents may misread it.

## 7. Actions and affordances

50. Action Definitions describe available kinds of behavior. Affordances are computed dynamically from current Agent and Timeline state.
51. **Can I?** and **Will I?** are separate questions. Capability determines feasibility; Motivation/Decision determines choice.
52. Underlying model knowledge must never automatically become Agent knowledge or skill.
53. Skill, Resource, Tool, Permission, Access, Relationship, Location, Health, and Context may all affect Affordance.
54. Skill is not merely boolean; proficiency and action difficulty may matter and may evolve through learning, practice, injury, or disuse.
55. Actual Affordance and Perceived Affordance are distinct. An Agent may attempt something it mistakenly believes possible, or fail to consider something it could actually do.
56. A missing path does not necessarily make a Goal impossible. Alternative actions, public channels, social contacts, or discovery mechanisms may create other routes.
57. Relationships create possibilities, not guaranteed results.
58. Direct and mediated access are distinct. An Agent may be unable to solve a problem directly but know someone or some channel that may advance it.
59. Social routing proceeds through real Agent decisions. A mediator is an Agent, not a transparent graph hop.
60. Referral, forwarding/escalation, and delegation are distinct mechanisms.
61. Planning may be progressive: take one reachable step, gain new information/context, then plan the next step.

## 8. Rules and real-world flexibility

62. Loom distinguishes **impossibility, prohibition, and enforcement**.
63. A rule's existence does not imply compliance, detection, judgment, enforcement, or equal consequences.
64. Hard Runtime Invariants should be few and protect world/runtime consistency rather than encode social expectations.
65. Most laws, policies, procedures, permissions, conventions, and norms are not physical impossibilities and may be violated, bypassed, overridden, ignored, or selectively enforced.
66. Event occurrence and compliance evaluation are separate. An action may factually happen while being unauthorized, irregular, prohibited, or socially disapproved.
67. Formal rules, legitimate exceptions, discretionary authority, informal practice, and outright violations are distinct concepts.
68. Enforcement actors are themselves World Entities/Agents and may delay, refuse, misjudge, favor, corrupt, or violate rules.
69. Formal Norms and Emergent Social Norms may diverge.
70. Agent belief about a rule or enforcement risk may differ from the actual rule and actual enforcement behavior.

## 9. Relationships, identity, and institutions

71. One Person/Agent remains one World Entity even when participating in many institutions, roles, countries, companies, families, and social contexts.
72. Membership, Citizenship, Employment, Family status, Role, and other identities are expressed through Relationships/Statuses rather than single-value fields on a Person.
73. Loom natively supports **multiplex relationships**: the same entities may simultaneously have multiple relationships with different meanings and states.
74. Structural/objective relationships and subjective relationship states are separate.
75. Subjective social states are directional. Alice trusting Bob does not imply Bob trusts Alice.
76. Knowing of an Entity, recognizing it, being familiar with it, and having a direct relationship with it are distinct.
77. Each Agent may maintain an Agent-local Entity Representation. That representation may be incomplete, stale, or wrong.
78. Actual Social Graph and Agent Perceived Social Graph are distinct.
79. Formal Authority and actual Influence are distinct.
80. Role/Relationship may create Permission, Access, Authority, Obligation, or new Affordances, but other personal relationships and goals continue to affect behavior inside institutional contexts.
81. A person's contextual Role changes which identity facets are salient; it does not create a separate Agent persona.
82. Collective Entity / Institution is the general abstraction for companies, governments, agencies, schools, families, associations, media organizations, informal groups, and other persistent collectives.
83. Institutions may contain other Institutions, but structural `PART_OF` does not imply absolute control.
84. Institutional Information Assets and Agent Memory are separate. Access may be revoked while previously internalized Knowledge, Memory, and Skill remain with the Agent.

## 10. Information provenance and organizations

85. Institutions and other Entities may publish or issue Information Artifacts through Channels.
86. Official media, government agencies, companies, exchanges, research bodies, and other organizations should be represented through the same Entity/Institution identity system used elsewhere in the World.
87. Provenance should remain traceable across Publisher/Issuer -> Channel -> Artifact -> Observation -> Claim -> World/Agent interpretation.
88. A source's publication is a fact about what that source said; the proposition contained in that publication is not automatically true.
89. Internal organizational information and public information may have different visibility and release times.

## 11. Architecture layering

90. Loom uses five top-level architectural concepts: **Core, Capability Module, World Template, World, and Application**.
91. Core defines how worlds exist and run.
92. Capability Modules add reusable domain/world abilities without becoming complete products.
93. World Templates compose capabilities, rules, and defaults into reusable world configurations.
94. A World is the actual persistent running instance with its own timelines, entities, state, history, and constitution/configuration.
95. An Application is a product experience that creates, controls, observes, analyzes, or interacts with Worlds. **Application is not World.**
96. The same Capability Module may be reused by multiple Applications and World Templates.
97. New Applications should not require forking or rewriting Core when the required behavior can be expressed through existing world primitives and Capability Modules.

## 12. Change discipline

98. Reusable standards and capabilities may evolve over time, but running Worlds must not silently change semantics because the platform was upgraded.
99. Runtime behavior, capability definitions, rules, and schemas that affect reproducibility must be versioned or otherwise revision-addressable.
100. Existing Worlds should remain pinned to their chosen semantic versions/revisions until an explicit migration or world-level change occurs.
101. Historical facts and committed Events are never rewritten merely to adopt a new standard. If historical causal results must change, use a new Timeline/Fork.
102. New projects and new Worlds may default to newer stable standards while older Worlds preserve their historical semantics.
