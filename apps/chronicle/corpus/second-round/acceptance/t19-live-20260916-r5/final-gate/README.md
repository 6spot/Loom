## Current-head staged gate

This directory records the completed staged 0.4 gate for commit
`1c1e002cc97a7dd14e1a549d63a76dd1f0714144`. The gate ran in fixture mode with
`--build --browser-required` and passed the reading, review, performance,
accessibility, person-state and browser suites. The fixture gate is deterministic
offline orchestration and is not live-provider content evidence; the real
provider and publication evidence is retained in the sibling r5 directories.

The gate exercised 5,000 units across 1,000 groups and its generated manifest,
browser results, screenshots and failure-chain checks are retained here. The
first prerequisite attempt, which failed because the test server lacked
`@playwright/test`, is preserved separately under
`../final-gate-prerequisite-failure/`; the dependency was installed before the
passing rerun.
