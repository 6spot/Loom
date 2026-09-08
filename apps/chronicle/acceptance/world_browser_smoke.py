#!/usr/bin/env python3
"""Generic C1-T17 Historical World browser acceptance through the Rust front."""
from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import urllib.request
from typing import Any
from urllib.parse import quote


def fetch_json(base_url: str, path: str) -> dict[str, Any]:
    with urllib.request.urlopen(base_url.rstrip("/") + path, timeout=15) as response:
        return json.load(response)


def chrome_binary() -> str:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    raise RuntimeError("Chrome/Chromium executable not found")


def dump_dom(chrome: str, url: str) -> str:
    result = subprocess.run(
        [
            chrome,
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--virtual-time-budget=5000",
            "--dump-dom",
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return html.unescape(result.stdout)


def require(text: str, needle: str, description: str) -> None:
    if needle not in text:
        raise AssertionError(f"T17 browser smoke missing {description}: {needle!r}")


def year_label(year: int) -> str:
    if year > 0:
        return f"公元 {year} 年"
    if year < 0:
        return f"公元前 {abs(year)} 年"
    return "公元 0 年"


def detail_for_event(
    base_url: str,
    event: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    event_id = str(event.get("canonical_event_id") or "")
    detail = fetch_json(base_url, f"/api/v1/public/events/{quote(event_id, safe='')}")

    presentation = detail.get("reader_presentation")
    if not isinstance(presentation, dict):
        raise AssertionError("selected Event lacks Reader Presentation")
    support_evidence: list[str] = []
    for block in presentation.get("blocks", []):
        for support in block.get("supports", []):
            text = support.get("claim", {}).get("evidence", {}).get("text")
            if isinstance(text, str) and text and text not in support_evidence:
                support_evidence.append(text)
    if not support_evidence:
        raise AssertionError("selected Event lacks Claim-supported Reader Presentation evidence")

    related = [*detail.get("participants", []), *detail.get("places", [])]
    entity = next((item for item in related if item.get("canonical_entity_id")), None)
    if entity is None:
        raise AssertionError("selected Event exposes no canonical Entity/Place drill-down")
    return detail, entity, support_evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--year", required=True, type=int)
    parser.add_argument("--event-id", required=True)
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    chrome = chrome_binary()
    year = args.year

    moment = fetch_json(base_url, f"/api/v1/public/historical-moment?year={year}&limit=100")
    assert moment.get("schema") == "chronicle.historical-moment", moment
    authority = moment.get("authority", {})
    assert authority.get("historical_world_state") is False, authority
    assert authority.get("historical_truth") is False, authority
    assert moment.get("uncertainty", {}).get("absence_is_not_historical_absence") is True
    coverage_years = moment.get("coverage", {}).get("time", {}).get("years", [])
    assert len(coverage_years) == 1 and coverage_years[0].get("year") == year, coverage_years
    if int(coverage_years[0].get("event_count") or 0) < 1:
        raise AssertionError(f"selected year {year} has no represented Events")

    event = next(
        (
            item
            for item in moment.get("events", [])
            if str(item.get("canonical_event_id")) == args.event_id
        ),
        None,
    )
    if event is None:
        raise AssertionError(
            f"selected Event {args.event_id} is not represented in World year {year}"
        )
    event_detail, entity, support_evidence = detail_for_event(base_url, event)
    event_id = str(event["canonical_event_id"])
    event_title = str(event.get("display", {}).get("title") or "未命名事件")
    entity_id = str(entity["canonical_entity_id"])
    entity_name = str(entity.get("display", {}).get("name") or "未命名实体")
    encoded_event = quote(event_id, safe="")
    encoded_entity = quote(entity_id, safe="")

    timeline_dom = dump_dom(chrome, f"{base_url}/timeline?year={year}&limit=100")
    require(timeline_dom, 'data-view="timeline"', "Timeline view")
    require(timeline_dom, event_title, "selected Event on Timeline")
    require(
        timeline_dom,
        f"/events/{encoded_event}?year={year}",
        "Timeline to Event time-context link",
    )

    search_q = quote(event_title, safe="")
    search_dom = dump_dom(chrome, f"{base_url}/search?q={search_q}&year={year}")
    require(search_dom, 'data-view="search"', "Search view")
    require(search_dom, event_title, "selected Event in Search")
    require(
        search_dom,
        f"/events/{encoded_event}?year={year}",
        "Search to Event time-context link",
    )

    world_dom = dump_dom(chrome, f"{base_url}/world?year={year}")
    require(world_dom, 'data-view="world"', "World view")
    require(world_dom, 'data-test="historical-time-bar"', "global historical time bar")
    require(world_dom, year_label(year), "selected historical year")
    require(world_dom, event_title, "new Event on World")
    require(world_dom, f"/events/{encoded_event}?year={year}", "World to Event link")
    require(
        world_dom,
        f"/events/{encoded_event}?year={year}#evidence",
        "World to evidence link",
    )
    require(
        world_dom,
        f"/entities/{encoded_entity}?year={year}",
        "World to Entity link",
    )
    require(world_dom, 'data-test="world-limit-note"', "world-state limitation")
    require(world_dom, "没有记录 ≠ 历史上没有发生", "coverage absence semantics")

    event_dom = dump_dom(chrome, f"{base_url}/events/{encoded_event}?year={year}#evidence")
    require(event_dom, 'data-view="event"', "Event detail")
    require(event_dom, 'id="evidence"', "Event evidence anchor")
    for index, evidence_text in enumerate(support_evidence, start=1):
        require(
            event_dom,
            evidence_text,
            f"Reader Presentation support evidence #{index}",
        )
    require(
        event_dom,
        f"/entities/{encoded_entity}?year={year}",
        "Event to Entity link",
    )
    require(event_dom, year_label(year), "Event time context")

    entity_dom = dump_dom(chrome, f"{base_url}/entities/{encoded_entity}?year={year}#evidence")
    require(entity_dom, 'data-view="entity"', "Entity detail")
    require(entity_dom, entity_name, "selected canonical Entity")
    require(
        entity_dom,
        f"/events/{encoded_event}?year={year}",
        "Entity trajectory back to Event",
    )
    require(entity_dom, year_label(year), "Entity time context")

    presentation = event_detail.get("reader_presentation")
    if not isinstance(presentation, dict) or not any(
        block.get("supports") for block in presentation.get("blocks", [])
    ):
        raise AssertionError("selected Event lacks Claim-supported Reader Presentation")

    print(
        "C1-T17 Historical World browser flow: PASS "
        f"year={year} timeline=yes search=yes event={event_id} entity={entity_id} "
        f"presentation_support_evidence={len(support_evidence)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
