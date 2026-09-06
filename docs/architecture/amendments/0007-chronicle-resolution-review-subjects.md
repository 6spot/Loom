# Architecture Amendment 0007 — Chronicle Resolution Review Subjects

> Status: **ACCEPTED for the Chronicle C1 application boundary.**
>
> Depends on: Architecture Amendment 0006, Chronicle C1-T7/C1-T8, Issue #537.
>
> Scope: Chronicle application-owned persistence/review orchestration only. Loom engine authority and the C0 canonical publication contract are unchanged.

## 1. Trigger

C1-T17 real-machine run R16 proved that the existing human-review materialization unit is too fine-grained. C1-T7 correctly preserves non-boundary repeated source records and C1-T8 correctly refuses to invent identity automatically, but C1-T8 then opens one durable `ReviewItem` for every cross-source candidate pair. Repeated representations of the same already-known identity can therefore multiply operator debt even when several candidate pairs express one semantic question.

The acceptance failure is operational, not permission to weaken identity authority: the system must reduce duplicate questions without turning shared names, aliases, confidence, or model output into automatic historical identity.

## 2. Affected clauses

This amendment refines only the **human-review materialization layer** between:

1. C1-T7 assembled source bundle + `within_book_links`;
2. C1-T8 conservative C0 cross-source candidate generation; and
3. the existing candidate-level final resolution / C0 canonical publication path.

The following remain normative and unchanged:

- staged source records are immutable and retain temp IDs;
- C0 candidate generation stays conservative and record-pair based;
- the deterministic layer never invents `same_entity` or `same_occurrence`;
- human decisions use the existing C0 vocabulary;
- final resolution artifacts remain candidate-link artifacts;
- publication still consumes candidate-level links and preserves all negative constraints;
- `uncertain`, `not_same`, and `related_occurrence` never merge canonical identities.

## 3. Review subject

Chronicle may materialize one durable **review subject** for multiple underlying candidate links when, and only when, every member candidate connects the same proven semantic component on each side.

A review subject is a presentation/orchestration projection. It is not a new canonical identity object and carries no historical authority before a human decision.

Every review subject must retain:

- deterministic `review_subject_id` and version;
- link kind (`entity` or `event`);
- all underlying `(resolution_sha256, candidate_id)` keys;
- every member left/right bundle/ref pair;
- the published-side component authority;
- the incoming-source component authority;
- aggregated non-authoritative candidate signals;
- the one recorded human decision and rationale after review.

No underlying candidate may belong to more than one review subject in one frozen review plan.

## 4. Published-side equivalence authority

For the already-published side, the latest canonical catalog is authoritative for representation membership.

Two published `(bundle, ref)` representations may share one review-subject component only when the canonical catalog already places them under the same canonical Entity/Event ID.

Shared names, aliases, source titles, model confidence, or candidate signals are not sufficient.

If one published representation is observed under conflicting canonical IDs, materialization fails closed.

## 5. Incoming-source equivalence authority

For the new assembled source, review-subject components may union records only through C1-T7 links that are already **proven same-links**:

- Entity: `same_entity` only;
- Event: `same_occurrence` only.

The following are never equivalence edges:

- `uncertain`;
- `not_same`;
- `related_occurrence`;
- shared surface/name/alias by itself;
- model confidence or external historical knowledge.

Event grouping is therefore at least as strict as Entity grouping and cannot collapse a campaign/sequence merely because events are related.

An explicit negative constraint (`not_same`, or Event `related_occurrence`) inside a proposed proven component is a contract contradiction and fails closed.

## 6. One human decision, deterministic fan-out

The operator reviews one semantic component pair instead of every member temp-ID pair.

After the operator records an allowed C0 decision, Chronicle deterministically fans that single decision back out to **every underlying candidate key** in the subject. The existing `build_final_resolutions` path then produces ordinary candidate-level resolution artifacts exactly as before.

Fan-out must fail closed when:

- a candidate is missing from the frozen subject plan;
- one candidate is covered by multiple subjects;
- two terminal review rows would propagate conflicting decisions to one candidate;
- the persisted subject plan no longer covers exactly the current initial candidate set.

Thus the optimization changes the number of questions shown to a human, not the granularity or authority of final resolution/publication evidence.

## 7. Resume and audit determinism

Review-subject materialization is frozen per job once any subject ReviewItems are committed. On resume Chronicle adopts that persisted plan only when its member candidate coverage exactly matches the deterministic initial resolutions; it does not silently rematerialize against a later catalog snapshot.

Pre-amendment jobs that already contain candidate-level resolution reviews remain on their legacy plan. A job may not mix legacy candidate-level ReviewItems with review-subject ReviewItems.

All member refs, candidate IDs, signals, and propagated decisions remain durable in ReviewItem payload/audit history.

## 8. Studio presentation

Studio should present the review subject as the human unit:

- readable component names/aliases and exact source evidence first;
- member/candidate count visible;
- one decision form per subject;
- individual temp IDs, hashes and candidate keys under technical/audit details.

The UI must not imply that grouping itself is an identity decision.

## 9. Acceptance consequences

Chronicle C1-T17 may proceed only after regression proves that:

1. many candidate pairs connecting one published canonical identity to one proven incoming component produce one ReviewItem;
2. unproven same-name incoming records remain separate;
3. Event `related_occurrence` / `uncertain` do not form components;
4. one subject decision expands to every underlying C0 candidate key;
5. unchanged input + persisted review plan resumes without duplicate debt;
6. candidate-level final resolution and publication semantics remain unchanged;
7. exact-head Chronicle, Chronicle Docker and Chronicle Live Model Contract all pass before the next real-machine run.
