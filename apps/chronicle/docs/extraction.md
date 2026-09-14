# Retired chunk extraction

The C1 chunk extraction path is historical regression material only. The
production worker no longer imports `persistence/extraction.py`,
`chapter_extraction.py`, `chapter_prompt.py`, or a `chunk_model` provider.

Current production processing is the complete natural-chapter staged pipeline
documented in [staged-chapter-production.md](staged-chapter-production.md) and
[worker.md](worker.md). Its translation, extraction, linking, review, and
repair steps all bind the current 0.4 request and acceptance receipt.
