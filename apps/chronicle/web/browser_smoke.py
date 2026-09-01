#!/usr/bin/env python3
"""Exercise Chronicle's persisted two-source world through a real headless browser."""

from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import urllib.request
from typing import Any


def fetch_json(base_url: str, path: str) -> dict[str, Any]:
    with urllib.request.urlopen(base_url.rstrip("/") + path, timeout=5) as response:
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
            "--virtual-time-budget=3000",
            "--dump-dom",
            url,
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=20,
    )
    return html.unescape(result.stdout)


def require(text: str, needle: str, description: str) -> None:
    if needle not in text:
        raise AssertionError(f"browser smoke missing {description}: {needle!r}")


def find_item(items: list[dict[str, Any]], *, title: str) -> dict[str, Any]:
    for item in items:
        if item.get("display", {}).get("title") == title:
            return item
    raise AssertionError(f"Timeline missing canonical Event {title!r}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    chrome = chrome_binary()

    all_timeline = fetch_json(base_url, "/v0/timeline?limit=200&offset=0")
    items = all_timeline["items"]
    red_cliffs = find_item(items, title="赤壁之战")
    red_cliffs_id = red_cliffs["canonical_event_id"]
    if red_cliffs.get("source_count") != 2:
        raise AssertionError("Red Cliffs must remain one canonical Event backed by two sources")

    timeline_dom = dump_dom(chrome, f"{base_url}/timeline?from_year=208&to_year=208")
    require(timeline_dom, "赤壁之战", "Red Cliffs Timeline card")
    require(timeline_dom, "三国志·魏书·武帝纪", "Wudi source title on Timeline")
    require(timeline_dom, "三国志·吴书·吴主传", "Wuzhu source title on Timeline")
    if timeline_dom.count(f'data-event-id="{red_cliffs_id}"') != 1:
        raise AssertionError("Red Cliffs canonical Event must render exactly once on Timeline")

    red_detail = fetch_json(base_url, f"/v0/events/{red_cliffs_id}")
    event_dom = dump_dom(chrome, f"{base_url}/events/{red_cliffs_id}")
    require(event_dom, "史料与证据", "Event evidence section")
    require(event_dom, "三国志·魏书·武帝纪", "Wudi Event representation")
    require(event_dom, "三国志·吴书·吴主传", "Wuzhu Event representation")

    evidence_count = 0
    representation_bundles = {
        representation.get("bundle")
        for representation in red_detail.get("representations", [])
    }
    if representation_bundles != {"wudi", "wuzhu"}:
        raise AssertionError(
            f"Red Cliffs must preserve both source representations, got {sorted(representation_bundles)}"
        )
    for representation in red_detail.get("representations", []):
        bundle = representation.get("bundle") or "unknown"
        for claim in representation.get("claims", []):
            evidence = claim.get("claim", {}).get("evidence", {}).get("text")
            if not evidence:
                continue
            evidence_count += 1
            require(event_dom, evidence, f"exact {bundle} evidence in Event DOM")
    if evidence_count == 0:
        raise AssertionError("Red Cliffs Event must expose at least one direct source evidence excerpt")

    cao_cao = next(
        participant
        for participant in red_detail.get("participants", [])
        if participant.get("display", {}).get("name") == "曹操"
    )
    cao_cao_id = cao_cao["canonical_entity_id"]
    require(event_dom, f"/entities/{cao_cao_id}", "canonical Cao Cao Entity link")
    cao_dom = dump_dom(chrome, f"{base_url}/entities/{cao_cao_id}")
    require(cao_dom, "曹操", "Cao Cao canonical Entity page")
    require(cao_dom, "事件轨迹", "Cao Cao event trajectory")
    require(cao_dom, "赤壁之战", "Red Cliffs on Cao Cao trajectory")

    red_cliffs_place = next(
        place
        for place in red_detail.get("places", [])
        if place.get("display", {}).get("name") == "赤壁"
    )
    place_id = red_cliffs_place["canonical_entity_id"]
    place_dom = dump_dom(chrome, f"{base_url}/entities/{place_id}")
    require(place_dom, "作为地点", "place involvement marker")
    require(place_dom, "身份不确定", "uncertain same-name place identity")
    require(place_dom, "赤壁之战", "place-to-Event navigation")

    related_detail = None
    related_item = None
    for item in items:
        if "江陵" not in (item.get("display", {}).get("title") or ""):
            continue
        candidate = fetch_json(base_url, f"/v0/events/{item['canonical_event_id']}")
        if candidate.get("related_events"):
            related_item = item
            related_detail = candidate
            break
    if related_item is None or related_detail is None:
        raise AssertionError("No related-but-distinct Jiangling Event found")
    jiangling_dom = dump_dom(chrome, f"{base_url}/events/{related_item['canonical_event_id']}")
    require(jiangling_dom, "相关事件", "related Event section")
    for related in related_detail["related_events"]:
        require(
            jiangling_dom,
            related["event"]["display"]["title"],
            "related-but-distinct Jiangling Event link",
        )

    print(
        "chronicle browser smoke: PASS "
        f"chrome={chrome} red_cliffs={red_cliffs_id} cao_cao={cao_cao_id} place={place_id} "
        f"evidence={evidence_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
