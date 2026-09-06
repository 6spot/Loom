"""R15 regression: Studio review projection must be human-decidable."""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
READ_API = HERE
if str(READ_API) not in sys.path:
    sys.path.insert(0, str(READ_API))

from studio_reviews import (  # noqa: E402
    _claim_evidence_from_rows,
    _display_projection,
    _entity_display_from_rows,
)


def test_event_projection_resolves_refs_and_preserves_exact_evidence() -> None:
    entity_rows = [
        ("ent_001", {"canonical_name": "周瑜", "type": "person"}),
        ("ent_002", {"canonical_name": "程普", "type": "person"}),
        ("ent_003", {"canonical_name": "赤壁", "type": "place"}),
    ]
    claim_rows = [
        (
            "clm_001",
            {
                "subject": {"kind": "event_ref", "ref": "evt_001"},
                "predicate": "outcome",
                "object": {"kind": "literal", "value": "破"},
                "evidence": {
                    "text": "与曹公战于赤壁，大破之",
                    "source_ref": "src_001",
                    "locator": {"work": "三国志", "chapter": "蜀书·先主传", "paragraph": "1"},
                },
            },
        ),
        (
            "clm_other",
            {
                "subject": {"kind": "entity_ref", "ref": "ent_001"},
                "predicate": "other",
                "object": None,
                "evidence": {"text": "不相关证据", "source_ref": "src_001", "locator": {}},
            },
        ),
    ]
    entities = _entity_display_from_rows(entity_rows)
    evidence = _claim_evidence_from_rows(claim_rows, "evt_001")
    display = _display_projection(
        {
            "kind": "event",
            "type": "battle",
            "title": "赤壁之战",
            "summary": "赤壁交战",
            "time": {
                "original_text": "是岁",
                "source_calendar": {"system": "chinese_lunisolar_regnal", "era": "建安", "era_year": 13},
                "normalized": {"calendar": "proleptic_gregorian", "year": 208, "precision": "year", "conversion_status": "year_only", "approximate": True},
            },
            "participants": [
                {"entity_ref": "ent_001", "role": "参战方"},
                {"entity_ref": "ent_002", "role": "参战方"},
            ],
            "places": ["ent_003"],
        },
        link_kind="event",
        entity_display=entities,
        evidence=evidence,
    )

    assert [item["name"] for item in display["participants"]] == ["周瑜", "程普"]
    assert display["places"] == [{"ref": "ent_003", "name": "赤壁", "type": "place"}]
    assert display["time"]["original_text"] == "是岁"
    assert display["time"]["era"] == "建安"
    assert display["time"]["era_year"] == 13
    assert display["time"]["normalized_year"] == 208
    assert display["evidence"] == [
        {
            "claim_ref": "clm_001",
            "relation": "subject",
            "predicate": "outcome",
            "text": "与曹公战于赤壁，大破之",
            "source_ref": "src_001",
            "locator": {"work": "三国志", "chapter": "蜀书·先主传", "paragraph": "1"},
        }
    ]


def test_entity_projection_uses_only_direct_claim_evidence() -> None:
    rows = [
        (
            "clm_001",
            {
                "subject": {"kind": "entity_ref", "ref": "ent_001"},
                "predicate": "fought",
                "object": {"kind": "entity_ref", "ref": "ent_002"},
                "evidence": {"text": "瑜、普为左右督", "source_ref": "src_001", "locator": {}},
            },
        ),
        (
            "clm_002",
            {
                "subject": {"kind": "entity_ref", "ref": "ent_003"},
                "predicate": "unrelated",
                "object": None,
                "evidence": {"text": "别处文字", "source_ref": "src_001", "locator": {}},
            },
        ),
    ]
    evidence = _claim_evidence_from_rows(rows, "ent_001")
    display = _display_projection(
        {
            "kind": "entity",
            "type": "person",
            "canonical_name": "周瑜",
            "aliases": ["公瑾"],
            "mentions": [{"text": "周瑜"}, {"text": "瑜", "contextual": True}],
        },
        link_kind="entity",
        entity_display={},
        evidence=evidence,
    )
    assert display["name"] == "周瑜"
    assert display["aliases"] == ["公瑾"]
    assert display["mentions"] == ["周瑜", "瑜"]
    assert [item["text"] for item in display["evidence"]] == ["瑜、普为左右督"]


if __name__ == "__main__":
    test_event_projection_resolves_refs_and_preserves_exact_evidence()
    test_entity_projection_uses_only_direct_claim_evidence()
    print("R15 Studio review projection: PASS")
