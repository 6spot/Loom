# Architecture Amendment 0007 — Chronicle Resolution Review Subjects and Batches

> Status: **ACCEPTED for the Chronicle C1 application boundary.**
>
> Depends on: Architecture Amendment 0006, Chronicle C1-T7/C1-T8, Issue #537.
>
> Scope: Chronicle application-owned persistence/review orchestration only. Loom engine authority and the C0 canonical publication contract are unchanged.

## 1. Trigger

C1-T17 real-machine runs R16 and R18 proved two different sources of operator review debt.

R16 showed that record-pair candidates can multiply when several already-proven representations express one semantic question. The first Amendment-0007 implementation therefore introduced **review subjects**: candidate pairs are collapsed only when the published side is already one canonical identity/event and the incoming side is already one C1-T7 proven `same_entity` / `same_occurrence` component.

R18 then proved that this is still too fine-grained for operator interaction. Several incoming temp refs can remain separate proven components because C1-T7 correctly refuses to invent equivalence, while each of those components asks the operator about the same already-published canonical identity. Studio therefore still surfaced repeated questions such as `诸葛亮 ↔ 诸葛亮` many times.

The acceptance failure is operational, not permission to weaken identity authority. Chronicle needs a second, higher **review batch** layer that reduces repeated questions without treating display grouping as semantic equivalence.

## 2. Unchanged authority boundaries

The following remain normative and unchanged:

- staged source records are immutable and retain temp IDs;
- C0 candidate generation stays conservative and record-pair based;
- the deterministic layer never invents `same_entity` or `same_occurrence`;
- final resolution artifacts remain candidate-link artifacts;
- publication still consumes candidate-level links and preserves all negative constraints;
- `uncertain`, `not_same`, and `related_occurrence` never merge canonical identities;
- names, aliases, titles, model confidence and review presentation are not identity authority.

## 3. Proven review group

A **review group** is the smallest incoming-side semantic component that Chronicle may treat as already equivalent before human cross-source review.

For the published side, latest canonical-catalog representation membership is authoritative. Two published `(bundle, ref)` representations share one canonical component only when the catalog already places them under the same canonical Entity/Event ID.

For the new assembled source, records may share one proven group only through C1-T7 links that are already same-links:

- Entity: `same_entity` only;
- Event: `same_occurrence` only.

The following never create a proven group:

- `uncertain`;
- `not_same`;
- `related_occurrence`;
- shared names/surfaces/aliases;
- model confidence or external historical knowledge.

An explicit negative constraint inside a proposed proven group is a contract contradiction and fails closed.

## 4. Review batch

A **review batch** is an operator-interaction unit, not an equivalence relation.

For one link kind (`entity` or `event`) and one already-published canonical ID, Chronicle may collect multiple proven incoming review groups into one durable ReviewItem batch. The purpose is only to ask the human one coherent question instead of repeating the same published-side identity/event many times.

Every batch must retain:

- deterministic `review_subject_id` and version;
- link kind;
- published canonical ID and all represented published refs;
- every incoming `review_group`, each with deterministic group ID and proven component root;
- all underlying `(resolution_sha256, candidate_id)` keys;
- every member left/right bundle/ref pair;
- aggregated non-authoritative candidate signals;
- the recorded default human decision;
- any explicit per-group human overrides.

No candidate key may belong to more than one persisted batch in one frozen review plan.

Grouping several incoming review groups into one batch does **not** imply those groups are mutually the same Entity/Event. It creates no semantic edge and cannot be consumed by canonical publication as equivalence.

## 5. Human decision and exception overrides

The normal operator path is one decision for the whole batch. That default decision may fan out to all incoming groups only because the human explicitly chose it after seeing the batch's evidence.

When the operator finds an exception, Studio must allow `存在例外，展开逐组判断`. The reviewer can then record a different allowed C0 decision, rationale and confidence for one or more review groups.

For example, one Entity batch may record:

- default: `same_entity`;
- group A: default applies;
- group B override: `not_same`;
- group C override: `uncertain`.

The existence of the batch never causes A/B/C to become equivalent to one another. Only the resulting candidate-level human decisions carry authority.

Group overrides must fail closed when:

- an override names a group absent from the frozen batch;
- the same group is overridden more than once;
- a decision is outside the exact C0 vocabulary for the link kind;
- confidence/rationale validation fails;
- group membership no longer covers the same candidate keys persisted in the batch.

## 6. Deterministic candidate fan-out

After review, Chronicle deterministically expands the batch default plus per-group overrides back to every underlying candidate key. Existing `build_final_resolutions` and C0 publication logic then consume ordinary candidate-level decisions exactly as before.

Fan-out must fail closed when:

- a candidate is missing from the frozen batch plan;
- one candidate is covered by multiple groups/batches;
- terminal review rows would propagate conflicting decisions to one candidate;
- the persisted batch plan no longer covers exactly the deterministic initial candidate set.

The optimization therefore changes the number of questions shown to a human, not the granularity or authority of final resolution/publication evidence.

## 7. Resume and audit determinism

Review materialization is frozen per job once any resolution ReviewItems are committed. Resume adopts that persisted plan only when candidate coverage still matches the deterministic initial resolutions; it does not silently rematerialize against a later catalog snapshot.

Pre-amendment candidate-level jobs and Amendment-0007 v0.1 proven-subject jobs remain auditable on their frozen plans. Fresh jobs use the review-batch version. A single job may not silently mix plan generations.

All member refs, candidate IDs, group IDs, signals and propagated decisions remain durable in ReviewItem payload/audit history.

## 8. Studio presentation

Studio presents the batch as the top-level human unit:

- one queue row per batch, normally one published canonical Entity/Event;
- readable names/aliases and exact source evidence first;
- visible `N 个来源候选组 / M 个底层候选` counts;
- one default decision form;
- explicit exception mode for per-group overrides;
- individual temp IDs, hashes and candidate keys under technical/audit details.

The UI must state that batching is only question organization and is not an identity conclusion.

## 9. Acceptance consequences

Chronicle C1-T17 may proceed only after regression proves that:

1. several unproven incoming refs that all candidate against one published canonical Entity/Event produce one batch with multiple review groups, not N queue rows;
2. different published canonical IDs remain separate batches;
3. proven within-book same-links still collapse refs into one review group;
4. Event `related_occurrence` / `uncertain` never become proven groups;
5. one default decision fans out to all candidate keys;
6. a per-group override affects only that group's candidate keys;
7. invalid/duplicate overrides fail closed;
8. unchanged input + persisted review plan resumes without duplicate debt;
9. candidate-level final resolution and publication semantics remain unchanged;
10. Studio exposes readable batch/group evidence and the explicit exception workflow;
11. exact-head Chronicle, Chronicle Docker and Chronicle Live Model Contract all pass before the next real-machine run.
