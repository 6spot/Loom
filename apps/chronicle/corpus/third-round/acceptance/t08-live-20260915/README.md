## T08 live T07 evidence

This acceptance bundle records a real HTTP and browser run against the current
PR implementation. The input was uploaded through the Studio API, queued as a
chapter job, processed by the worker, paused for chapter-content review, revised
and accepted, then resumed through resolution, person-state review, publication,
and presentation.

`api-redacted.json` keeps only schema/version fields, state transitions, counts,
and response-shape checks. Credentials, identifiers, hashes, and source text
are intentionally omitted. `browser-result.json` records the Chromium route
assertions; the two screenshots are the corresponding visible results.

The isolated test stack and its temporary data were removed after the evidence
was captured. The pre-existing test services were not changed.
