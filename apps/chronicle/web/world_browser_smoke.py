#!/usr/bin/env python3
"""Exercise the C1 Historical World flow through the production Rust web front."""

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
    with urllib.request.urlopen(base_url.rstrip("/") + path, timeout=8) as response:
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
        raise AssertionError(f"Historical World browser smoke missing {description}: {needle!r}")


def event_with_title(events: list[dict[str, Any]], needle: str) -> dict[str, Any]:
    for event in events:
        if needle in str(event.get("display", {}).get("title") or ""):
            return event
    raise AssertionError(f"Historical Moment missing event containing {needle!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    chrome = chrome_binary()

    moment = fetch_json(base_url, "/api/v1/public/historical-moment?year=208&limit=100")
    assert moment["schema"] == "chronicle.historical-moment", moment
    assert moment["authority"]["historical_world_state"] is False, moment["authority"]
    assert moment["authority"]["historical_truth"] is False, moment["authority"]
    assert moment["uncertainty"]["absence_is_not_historical_absence"] is True, moment["uncertainty"]
    coverage_years = moment["coverage"]["time"]["years"]
    assert len(coverage_years) == 1 and coverage_years[0]["year"] == 208, coverage_years
    assert coverage_years[0]["event_count"] > 0, coverage_years[0]

    red_cliffs = event_with_title(moment.get("events", []), "赤壁")
    red_cliffs_id = str(red_cliffs["canonical_event_id"])
    assert red_cliffs.get("claims"), red_cliffs
    encoded_event = quote(red_cliffs_id, safe="")

    event_detail = fetch_json(base_url, f"/api/v1/public/events/{encoded_event}")
    participants = [
        item
        for item in event_detail.get("participants", [])
        if item.get("canonical_entity_id")
    ]
    if not participants:
        raise AssertionError("Red Cliffs Event must expose at least one canonical participant")
    cao_cao = next(
        (item for item in participants if item.get("display", {}).get("name") == "曹操"),
        participants[0],
    )
    entity_id = str(cao_cao["canonical_entity_id"])
    entity_name = str(cao_cao.get("display", {}).get("name") or "未命名实体")
    encoded_entity = quote(entity_id, safe="")

    moment_entities = [
        *moment.get("entities", []),
        *moment.get("places", []),
        *moment.get("polities", []),
    ]
    if entity_id not in {str(item.get("canonical_entity_id")) for item in moment_entities}:
        raise AssertionError("Event participant must be represented in Historical Moment related entities")

    world_dom = dump_dom(chrome, f"{base_url}/world?year=208")
    require(world_dom, 'data-view="world"', "World view")
    require(world_dom, 'data-test="historical-time-bar"', "global historical time bar")
    require(world_dom, "公元 208 年", "selected historical year")
    require(world_dom, red_cliffs.get("display", {}).get("title") or "赤壁", "Red Cliffs World card")
    require(world_dom, f"/events/{encoded_event}?year=208", "World to Event time-context link")
    require(world_dom, f"/events/{encoded_event}?year=208#evidence", "World to evidence link")
    require(world_dom, f"/entities/{encoded_entity}?year=208", "World to Entity time-context link")
    require(world_dom, 'data-test="world-limit-note"', "world-state limitation")
    require(world_dom, "没有记录 ≠ 历史上没有发生", "coverage absence semantics")

    event_dom = dump_dom(chrome, f"{base_url}/events/{encoded_event}?year=208#evidence")
    require(event_dom, 'data-view="event"', "Event detail")
    require(event_dom, 'id="evidence"', "Event evidence anchor")
    require(event_dom, "史料与证据", "Event evidence section")
    require(event_dom, f"/entities/{encoded_entity}?year=208", "Event to Entity time-context link")
    require(event_dom, "公元 208 年", "Event historical time context")

    evidence_text = None
    for representation in event_detail.get("representations", []):
        for claim in representation.get("claims", []):
            text = claim.get("claim", {}).get("evidence", {}).get("text")
            if text:
                evidence_text = str(text)
                break
        if evidence_text:
            break
    if not evidence_text:
        raise AssertionError("Red Cliffs Event must preserve at least one source evidence excerpt")
    require(event_dom, evidence_text, "exact persisted source evidence")

    entity_dom = dump_dom(chrome, f"{base_url}/entities/{encoded_entity}?year=208")
    require(entity_dom, 'data-view="entity"', "Entity detail")
    require(entity_dom, entity_name, "selected canonical Entity")
    require(entity_dom, f"/events/{encoded_event}?year=208", "Entity trajectory back to Event with time context")
    require(entity_dom, "公元 208 年", "Entity historical time context")

    sparse_dom = dump_dom(chrome, f"{base_url}/world?year=209")
    require(sparse_dom, 'data-view="world"', "neighboring World view")
    require(sparse_dom, "当前语料未覆盖", "neighboring sparse coverage")
    require(sparse_dom, "没有记录 ≠ 历史上没有发生", "neighboring absence semantics")

    print(
        "C1-T16 Historical World browser flow: PASS "
        f"world=208 event={red_cliffs_id} entity={entity_id} evidence=yes neighbor=209"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
