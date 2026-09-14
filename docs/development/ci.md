# CI routing and merge checks

This guide owns the operational procedure for CI selection and verification.
Changes to routing or merge gates are dedicated CI/governance work.

## Authority and execution

[`tools/ci_routing.py`](../../tools/ci_routing.py) is the single path classifier.
It emits a versioned JSON plan containing selected jobs, step flags, browser
suites, changed documents and reasons. Workflow files execute that plan; do
not add a second path list or shell classifier to a workflow.

- [`ci.yml`](../../.github/workflows/ci.yml) classifies every PR and main push.
  Its stable required check remains **Repository Gate**.
- [`chronicle.yml`](../../.github/workflows/chronicle.yml) is called by CI when
  Chronicle contracts are affected. **Chronicle Gate** validates its selected
  jobs, and the caller's result is a dependency of Repository Gate. It does not
  start a duplicate independent run for the same PR.
- [`validator.yml`](../../.github/workflows/validator.yml) uses the same
  classifier and retains its independent **Validator Gate**. Validator-only
  implementation changes do not compile the core Rust workspace.

The CI and Validator workflow entries still appear on every PR/main push so
their required gates always report a result. Classification and gate jobs are
lightweight; an entry in Actions does not mean every build ran. Inspect the
selected/skipped jobs or the classification summary. Do not add top-level
`paths` filters to these workflows: an absent required check can leave a PR
waiting indefinitely.

All three workflows retain manual dispatch. Dispatch selects all checks owned
by that workflow. Existing offline fixtures, browser requirements, performance
budgets and acceptance scripts remain in use. Live model preflight and
historical full certification are separate procedures.

PR selection uses the merge base of the base/head revisions. Push selection
uses before/after revisions; an initial push compares with the empty tree.
Renames count as deletion plus addition so both owners are selected. File
names are read with NUL delimiters and passed as JSON, including spaces and
newlines. An unsupported event or invalid plan fails classification.

## Functional selection

The classifier is the exact rule source; this table explains its boundaries.

| Change | Selected work |
| --- | --- |
| Core crates/capabilities, server/CLI assembly, core tests or neutral examples | Core Rust checks; no Chronicle or Validator lane. Core Rust is still checked as one workspace, excluding Validator. |
| Validator source or its named certification/helper scripts | Validator static checks and helper syntax checks; no Chronicle or core workspace lane. Full historical certification remains manual. |
| Root Cargo manifests/lock/toolchain | Core Rust, dependency policy and Validator static checks. Chronicle has separate Rust workspaces. |
| Shared `tools/test.sh` or `tools/postgres-test.sh` | Core Rust, deployment configuration and Validator static/helper checks. Chronicle uses separate acceptance harnesses. |
| Ordinary README, AGENTS, CLAUDE or product/development documentation | Routing tests and changed-document checks. The public quickstart/operator documents retain their operational command checks. |
| Repository historical-background-art scripts, brief assets or agent configuration | Their offline archive tests; no application build, database, browser or model call. Skill Markdown follows ordinary documentation routing. |
| Studio presentation and Studio-only UI components | Frontend build consistency, frontend unit tests and Studio/review component suites; no chapter database or public reading stack solely for this change. |
| Source reader components | Source-reading browser acceptance and matching component suites. |
| Synthesized history or person UI | Published-history/person browser acceptance and matching component suites. Shared reading context, position/state types and layout cover both readers. |
| Chapter/model/staged production | Chapter offline and database contracts plus downstream reading/history/person publication acceptance. |
| Narrative/read contracts | Narrative, publication and search contracts, plus both downstream browser gates. |
| Person-state backend | Person-state contracts and published-history/person browser acceptance. |
| Shared schemas, migrations, server boundaries or dependencies | All affected Chronicle contracts. Unknown Chronicle code falls back to the Chronicle boundary; unknown frontend code covers all frontend consumers. |
| CI policy/shared classifier or an unknown repository file | Conservative full selection. Review the summary and add a narrower owned rule plus regression case when appropriate. |

Runtime corpus, prompt, config and fixture inputs are classified before ordinary
documentation. A Markdown or text extension does not make a model input a
documentation-only change. Existing task-note metadata checks remain scoped to
their owners; they do not create a new post-merge bookkeeping requirement.

Committed frontend assets require special handling: when application source or
build configuration also changed, source ownership selects browser suites.
The build still verifies **all** committed dist output against that source.
An asset-only edit selects all frontend consumers, so editing generated files
cannot silently bypass verification.

Some dependencies cross names and directories. R3's gate imports R2 helpers;
changes to those helpers select both gates. History and person pages consume
reading context/layout/types, so these shared frontend files also select both.
Add a dependency rule and a test when a new shared consumer is introduced.

## Results and failure handling

Every plan is shown in the Actions step summary with selected/skipped checks
and reasons. The stable gates run with `always()` and enforce:

1. Classification succeeded.
2. Every selected job exists in the result set and succeeded.
3. Unselected jobs are skipped or successful.
4. A failed, cancelled, missing or unexpectedly skipped selected job blocks
   the gate. Invalid/missing plan data also blocks it.

Chronicle component checks run without PostgreSQL or Docker. Chapter,
narrative and person database jobs run independently. Existing source-reading
and published-history browser gates keep separate real stacks. Frontend unit
tests run once in the component job. Docker builds remain per real-stack job;
image sharing and further cache tuning require separate measurements.

## Change and verify routing

Use a Python environment with the test dependencies installed:

```bash
python3 -m pip install -r tools/requirements-ci.txt
python3 -m unittest discover -s tools -p 'test_ci_routing.py' -v
python3 tools/ci_routing.py classify --paths apps/chronicle/webapp/README.md
python3 tools/ci_routing.py classify --paths apps/chronicle/webapp/src/styles/studio.css
python3 tools/ci_routing.py classify --all
git diff --check
```

The classifier and result gates themselves use only the Python standard
library; PyYAML is used by tests to inspect the actual workflow wiring.
Actionlint can additionally validate the changed workflow expressions and
reusable-workflow interface before opening the PR.

When changing a rule, add a concrete path-to-job regression case. Include mixed
owners, shared dependencies and generated assets where applicable. Git input
tests cover merge-base behavior, initial pushes, renames, deletions and unusual
file names. Gate tests cover failure, cancellation and unexpected skips;
workflow tests verify caller/gate dependencies and retained acceptance commands.

Do not narrow a route until its affected consumers are covered. If ownership
is unclear, retain the broader selection and explain the reason in the rule.
CI policy changes select full verification so the changed workflow graph is
exercised before merge.
