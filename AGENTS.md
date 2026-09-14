# Loom Agent Instructions

Read this file first. Keep it short.

## Choose what to read

At the start of a new task, read this file and any `AGENTS.md` governing the affected subtree. Then combine the matching rows below; an index is a navigation aid, not an instruction to open every linked document.

| Task includes | Read before that work |
| --- | --- |
| Analysis, discussion, review or advice | The requested material and the code, tests or guide needed to answer the question. |
| Code changes, including UI layout, styles or copy | `docs/development/README.md`, the affected module's development guide, and the code and tests for the changed behavior. |
| Documentation or instruction changes | The affected document and current guides defining or repeating the rule being edited. Use `docs/README.md` if the owner is unclear. |
| Changes to Loom semantics, public API contracts, persisted data contracts, ownership or dependency edges | Also read `docs/architecture/README.md`; resolve the current authority through its reverse supersession table and read the accepted Amendments for the affected topic. |
| Deployment, migration or rollback operations | Also read `docs/deployment/README.md` and the runbook for that operation. |
| An Issue/task linked to `docs/tasks/` | Also read the linked task note and initiative README for scope, ownership and prerequisites. |

UI layout, styles and copy do not trigger architecture reading when these contracts stay unchanged. If classification is unclear, inspect the affected code or document first; reclassify when that inspection reveals a contract change.

Within the same task, including a continuation or context compaction, reuse already-read instructions when their contents are unchanged. Keep the paths, applicable constraints and remaining work in the handoff. Re-read affected material when files change, scope changes or the necessary context is missing. A new task starts with a fresh check.

Repository canonical documents own project architecture and development procedure, subject to higher-priority instructions and the user's authorized scope. Subtree instructions and task notes do not redefine architecture authority.

## Task context

GitHub Issues carry the task goal and acceptance context. Repository task notes may preserve planning, file ownership, dependency diagrams and useful implementation evidence. GitHub PRs carry the delivered repository change and its review/check results.

Task-note metadata is descriptive context. When a task is assigned for implementation, use the current task and Issue as the work to execute, and use linked task notes to understand its boundaries and prerequisites.

The standard delivery flow does not include a separate post-merge bookkeeping change solely to copy final PR or merge metadata into task notes.

## Scope and Skills

- Requests limited to analysis, discussion, review or suggestions are read-only. For implementation requests, complete the authorized work without asking again whether to start or continue.
- Authorization for the same action, target and scope persists across steps, retries and continuations. Ask again only when the proposed action exceeds that authorization or a new constraint requires a decision.
- For automatic Skill selection, match both the requested work and the technology in use. Generic words such as "workflow", "agent" or "website" are not enough to select a provider-specific Skill. An explicitly named Skill is handled according to the user's request and the available tools.
- For example, a Python workflow does not imply Cloudflare Agents SDK; an existing frontend does not imply a Sites deployment; an implementation request does not imply a Skill search or installation.
- A Skill template alone does not authorize extra plan files, approvals, tool installations, deployments or separate branches/worktrees. Use the current repository workflow within the authorized task and higher-priority instructions.
- If a tool is unavailable, identify the affected step and continue independent work. Do not claim that the unavailable tool's check or action succeeded.

## While editing

- Stay inside the accepted task scope.
- Preserve architecture-owned authority, crate boundaries, dependency rules and public API boundaries.
- Do not create duplicate authority, API, initialization, persistence, deployment or test paths.
- Put operational instructions in the canonical development/deployment guide, not in task notes.
- Keep task notes as planning/evidence records, not alternate specifications.
- Add or update tests at the layer that owns the changed contract.
- Do not weaken or skip a failing contract just to make tests pass.

## Continue or pause

| Situation | Action |
| --- | --- |
| Routine naming, component structure or implementation choice within existing contracts | Follow the existing module's conventions and continue. |
| An apparent document conflict resolved by current authority or supersession | Follow the effective rule and record the resolution with the delivery. No extra user approval is needed. |
| An unresolved contract/authority conflict, a new semantic decision without architecture authority, or a required scope/authorization expansion | Pause the dependent implementation, state the unresolved decision and continue independent authorized work. Architecture gaps use the Amendment process in `docs/architecture/README.md`. |
| The task is cancelled, superseded or replaced | Stop the affected task and follow the current request. |

Pausing a dependent step does not require asking the user to approve routine choices elsewhere. Resolve conflicts through the current authority before requesting a decision; never implement a competing contract to work around a blocker.

## Before finishing

- Run the focused checks required by the current CI/development/deployment guides for the changed contract.
- Do not claim checks passed unless they actually ran successfully.
- Record any unverified checks and the reason.
- Keep task documentation accurate when the current delivery already touches it.
- Keep the GitHub PR/Issue description consistent with the delivered work.

Repository delivery completion follows `docs/development/task-completion.md`.

## Maintain this file

Only add repository-wide instructions that apply to most tasks.

Do not add architecture summaries, runbooks, milestone status, copied documentation, CI matrices or warnings about a single past mistake. Fix those at their canonical source instead.
