#!/usr/bin/env python3
"""Exercise the published history/source-locator flow through the web front."""

from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote, urlencode


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
        raise AssertionError(f"published reading browser smoke missing {description}: {needle!r}")


def search_path(query: str, *, kind: str = "all", limit: int = 20) -> str:
    return "/api/v1/public/search?" + urlencode({"q": query, "kind": kind, "limit": limit})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")
    chrome = chrome_binary()

    history = fetch_json(base_url, "/api/v1/public/history")
    publication = history["publication"]
    if not publication or not publication.get("version"):
        raise AssertionError("a published history edition is required")
    entries = publication.get("entry_points", [])
    red_cliffs = next((entry for entry in entries if entry.get("label") == "赤壁之战"), None)
    if red_cliffs is None or red_cliffs.get("event_id") is None:
        raise AssertionError("published history must expose an exact 赤壁之战 event entry")
    version = str(publication["version"])
    paragraph_id = str(red_cliffs["paragraph_id"])
    event_id = str(red_cliffs["event_id"])
    history_url = f"/history/{quote(version, safe='')}/{quote(paragraph_id, safe='')}"

    catalog = quote(str(publication["catalog_sha"]), safe="")
    encoded_event = quote(event_id, safe="")
    preview = fetch_json(
        base_url,
        f"/api/v1/public/reading-events/{encoded_event}/preview?catalog={catalog}",
    )
    sources = preview.get("sources", [])
    if len(sources) != 2:
        raise AssertionError(f"published event preview must retain two sources, got {len(sources)}")
    if not all(source.get("original_entry") for source in sources):
        raise AssertionError("every published source must retain its original entry locator")

    targets = fetch_json(
        base_url,
        f"/api/v1/public/reading-events/{encoded_event}/targets?catalog={catalog}",
    )
    if not targets.get("targets"):
        raise AssertionError("published event must expose at least one exact reading target")

    history_dom = dump_dom(chrome, base_url + history_url)
    require(history_dom, 'data-view="history-reading"', "history reader")
    require(history_dom, "合成正文中的赤壁之战", "published history paragraph")
    require(history_dom, f'data-version="{version}"', "published version pin")
    require(history_dom, "曹操", "history context entity")

    event_query = urlencode({"catalog": publication["catalog_sha"], "version": version})
    event_url = f"{base_url}/events/{encoded_event}?{event_query}"
    event_dom = dump_dom(chrome, event_url)
    require(event_dom, 'data-view="event"', "event source locator")
    require(event_dom, "已发布历史正文", "published event mapping section")
    require(event_dom, history_url, "exact published paragraph link")
    require(event_dom, "三国志·魏书·武帝纪", "Wudi source evidence")
    require(event_dom, "三国志·吴书·吴主传", "Wuzhu source evidence")
    require(event_dom, "公至赤壁，与备战，不利。", "Wudi excerpt")
    require(event_dom, "遇于赤壁，大破曹公军。", "Wuzhu excerpt")
    if "史料与证据" in event_dom or "Reader Presentation" in event_dom:
        raise AssertionError("event source locator must not render the retired encyclopedia cards")

    cao_search = fetch_json(base_url, search_path("曹操", kind="entity"))
    cao_result = next(
        (item for item in cao_search.get("items", []) if item.get("display", {}).get("name") == "曹操"),
        None,
    )
    if cao_result is None:
        raise AssertionError("person search must return 曹操")
    cao_id = str(cao_result["canonical_id"])
    cao_dom = dump_dom(chrome, f"{base_url}{cao_result['navigation_path']}?{event_query}")
    require(cao_dom, 'data-view="entity"', "person page")
    require(cao_dom, "曹操", "canonical person")
    require(cao_dom, "事件轨迹", "person event trajectory")
    require(cao_dom, "赤壁之战", "person event mapping")
    require(cao_dom, f"catalog={publication['catalog_sha']}", "person published catalog context")
    if f"/events/{event_id}?year=" in cao_dom:
        raise AssertionError("person links must not invent a historical year query")

    chibi_search = fetch_json(base_url, search_path("赤壁"))
    chibi_event = next(
        (
            item
            for item in chibi_search.get("items", [])
            if item.get("kind") == "event" and item.get("canonical_id") == event_id
        ),
        None,
    )
    if chibi_event is None:
        raise AssertionError("event search must preserve the canonical Red Cliffs event")
    chibi_place = next(
        (
            item
            for item in chibi_search.get("items", [])
            if item.get("kind") == "entity" and item.get("display", {}).get("name") == "赤壁"
        ),
        None,
    )
    if not chibi_place or chibi_place.get("identity_uncertain") is not True:
        raise AssertionError("same-name place search must remain visibly uncertain")
    chibi_dom = dump_dom(chrome, f"{base_url}/search?q={quote('赤壁', safe='')}")
    require(chibi_dom, "身份不确定", "uncertain place marker")
    require(chibi_dom, history_url, "event search published location")
    require(chibi_dom, f"/entities/{chibi_place['canonical_id']}", "place entity navigation")

    place_dom = dump_dom(chrome, f"{base_url}{chibi_place['navigation_path']}?{event_query}")
    require(place_dom, "作为地点", "place involvement")
    require(place_dom, "身份不确定", "place uncertainty")
    require(place_dom, "赤壁之战", "place event trajectory")

    retired_paths = (
        "/world",
        "/timeline",
        "/api/v1/public/timeline?limit=20",
        f"/api/v1/public/events/{encoded_event}",
        "/api/v1/public/historical-moment?year=208",
    )
    for path in retired_paths:
        try:
            with urllib.request.urlopen(base_url + path, timeout=8) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        if status != 404:
            raise AssertionError(f"retired public path must be typed 404: {path} -> {status}")

    print(
        "chronicle published reading browser smoke: PASS "
        f"version={version} paragraph={paragraph_id} event={event_id} person={cao_id} sources=2"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
