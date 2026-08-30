# CI Governance Task Ledger

This ledger owns repository-level CI and merge-gate policy changes that must not be hidden inside ordinary product, architecture, Scheduler, Storage, API, or Validator feature leaves.

Only dedicated CI/governance tasks may intentionally change `.github/workflows/**` or the scripts that directly define repository CI gate policy.

## Tasks

| Task | Issue | Status | Depends on | Purpose |
| --- | --- | --- | --- | --- |
| CI-GOV-T01 | #428 | completed | — | Retire completed VALR-T24 full certification from routine CI and establish Code Owner coverage for CI authority surfaces. |

## Governance boundary

- Product/architecture tasks may state the validation they require, but do not own repository merge-gate policy.
- Validator regression may block a change when a capability contract actually regresses.
- Historical/final certification procedures must not remain permanent development gates after their certification initiative closes.
- Changes to CI authority surfaces require a dedicated governance task and review; ordinary executable leaves should treat such edits as out of scope.
