# Retired chunk segmentation

The C1 section/chunk segmentation path is retained only as historical
documentation. The production worker does not import `persistence/segmentation.py`
or create a fake structure/segment checkpoint.

Current jobs plan immutable natural chapters through `chapter_plan.py`; the
current structure and segment stages persist that plan and one work chunk per
chapter. See [staged-chapter-production.md](staged-chapter-production.md) and
[worker.md](worker.md) for the active contract and safety behavior.
