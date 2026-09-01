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
from urllib.parse import urlencode


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


def search_path(query: str, *, kind: str = "all", limit: int = 20) -> str:
    return "/v0/search?" + urlencode({"q": query, "kind": kind, "limit": limit})


def browser_search_url(base_url: str, query: str) -> str:
    return f"{base_url}/search?{urlencode({'q': query})}"


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

    # C0-T12: exercise the real search API and the browser search view.
    cao_search = fetch_json(base_url, search_path("曹操", kind="entity"))
    cao_results = [
        item
        for item in cao_search.get("items", [])
        if item.get("display", {}).get("name") == "曹操"
    ]
    if len(cao_results) != 1:
        raise AssertionError(f"Cao Cao search must return one canonical Entity, got {len(cao_results)}")
    cao_result = cao_results[0]
    if cao_result.get("canonical_id") != cao_cao_id:
        raise AssertionError("Cao Cao search result must navigate to the existing canonical Entity")
    if cao_result.get("source_count") != 2:
        raise AssertionError("Cao Cao search result must preserve both sources")
    matched_bundles = {
        surface.get("bundle")
        for surface in cao_result.get("match", {}).get("matched_surfaces", [])
        if surface.get("bundle")
    }
    if matched_bundles != {"wudi", "wuzhu"}:
        raise AssertionError(f"Cao Cao search provenance must include both sources, got {matched_bundles}")

    cao_search_dom = dump_dom(chrome, browser_search_url(base_url, "曹操"))
    require(cao_search_dom, "曹操", "Cao Cao search result")
    require(cao_search_dom, f"/entities/{cao_cao_id}", "Cao Cao canonical search navigation")
    require(cao_search_dom, "为什么命中", "search match explanation")
    require(cao_search_dom, "三国志·魏书·武帝纪", "Wudi search provenance")
    require(cao_search_dom, "三国志·吴书·吴主传", "Wuzhu search provenance")

    chibi_search = fetch_json(base_url, search_path("赤壁"))
    chibi_event = next(
        (
            item
            for item in chibi_search.get("items", [])
            if item.get("kind") == "event"
            and item.get("display", {}).get("title") == "赤壁之战"
        ),
        None,
    )
    if chibi_event is None or chibi_event.get("canonical_id") != red_cliffs_id:
        raise AssertionError("Chibi search must surface the existing canonical Red Cliffs Event")
    chibi_places = [
        item
        for item in chibi_search.get("items", [])
        if item.get("kind") == "entity" and item.get("display", {}).get("name") == "赤壁"
    ]
    if len(chibi_places) != 2 or len({item.get("canonical_id") for item in chibi_places}) != 2:
        raise AssertionError("Chibi search must keep the two uncertain place identities distinct")
    if not all(item.get("identity_uncertain") is True for item in chibi_places):
        raise AssertionError("Both same-name Chibi place search results must remain visibly uncertain")

    chibi_search_dom = dump_dom(chrome, browser_search_url(base_url, "赤壁"))
    require(chibi_search_dom, f"/events/{red_cliffs_id}", "Red Cliffs Event search navigation")
    require(chibi_search_dom, "身份不确定", "uncertain place marker in search")
    for item in chibi_places:
        require(
            chibi_search_dom,
            f"/entities/{item['canonical_id']}",
            "distinct uncertain Chibi place search navigation",
        )

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
    related_ids = set()
    for related in related_detail["related_events"]:
        related_ids.add(related["event"]["canonical_event_id"])
        require(
            jiangling_dom,
            related["event"]["display"]["title"],
            "related-but-distinct Jiangling Event link",
        )

    jiangling_search = fetch_json(base_url, search_path("江陵", kind="event", limit=50))
    jiangling_results = [
        item
        for item in jiangling_search.get("items", [])
        if item.get("kind") == "event" and "江陵" in (item.get("display", {}).get("title") or "")
    ]
    jiangling_ids = {item.get("canonical_id") for item in jiangling_results}
    expected_jiangling_ids = {related_item["canonical_event_id"], *related_ids}
    if not expected_jiangling_ids.issubset(jiangling_ids):
        raise AssertionError(
            "Jiangling search must surface related-but-distinct canonical Events separately"
        )
    jiangling_search_dom = dump_dom(chrome, browser_search_url(base_url, "江陵"))
    for canonical_id in expected_jiangling_ids:
        require(
            jiangling_search_dom,
            f"/events/{canonical_id}",
            "related-but-distinct Jiangling search navigation",
        )

    print(
        "chronicle browser smoke: PASS "
        f"chrome={chrome} red_cliffs={red_cliffs_id} cao_cao={cao_cao_id} place={place_id} "
        f"evidence={evidence_count} search=PASS"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
