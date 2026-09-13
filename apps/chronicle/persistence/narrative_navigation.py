"""Reviewed navigation and a conservative projection for older publications.

Navigation covers reading positions, not historical state intervals. It never
fills missing dates or changes the phase attached to a paragraph.
"""
from __future__ import annotations

import re

from common import PersistenceError


def validate_navigation(sections, paragraphs, entries):
    positions = {p["id"]: n for n, p in enumerate(paragraphs)}
    cursor, selected = 0, set()
    for section in sections:
        if not section["label"].strip():
            raise PersistenceError("historical navigation: section labels must not be blank")
        start = positions.get(section["first_paragraph_id"])
        end = positions.get(section["last_paragraph_id"])
        if start != cursor or end is None or end < cursor:
            raise PersistenceError("historical navigation: sections must cover all paragraphs in order without gaps or overlaps")
        previous = start - 1
        for item in section["items"]:
            position = positions.get(item["paragraph_id"])
            if position is None or not start <= position <= end or position <= previous:
                raise PersistenceError("historical navigation: nodes must be distinct, ordered paragraphs inside their section")
            if not item.get("label", "").strip() or not item.get("reason", "").strip():
                raise PersistenceError("historical navigation: nodes need a label and selection reason")
            previous = position
            selected.add(item["paragraph_id"])
        cursor = end + 1
    if cursor != len(paragraphs):
        raise PersistenceError("historical navigation: sections omit the end of the narrative")
    if not {entry["paragraph_id"] for entry in entries} <= selected:
        raise PersistenceError("historical navigation: every curated entry must appear on the axis")


def _year_label(year):
    return "年代未详" if year is None else f"公元前 {-year} 年" if year < 0 else f"{year} 年"


def public_navigation(publication):
    """Project public nodes from accepted positions, with no model or DB calls."""
    paragraphs = publication["paragraphs"]
    positions = {p["id"]: n for n, p in enumerate(paragraphs)}
    group_by_id = {g["id"]: g for g in publication["groups"]}
    entries = {entry["paragraph_id"]: entry for entry in publication["entry_points"]}
    sections = publication.get("navigation")
    if sections is None:
        sections = []
        for group in publication["groups"]:
            start = positions[group["first_paragraph_id"]]
            end = start + group["count"] - 1
            if not sections or sections[-1]["_year"] != group["year"]:
                sections.append({"label": _year_label(group["year"]), "_year": group["year"],
                    "first_paragraph_id": group["first_paragraph_id"], "last_paragraph_id": paragraphs[end]["id"], "items": []})
            section = sections[-1]
            section["last_paragraph_id"] = paragraphs[end]["id"]
            # Known time changes can orient reading. Unknown phases cannot each
            # create another event; use already curated entries within that run.
            if group["year"] is not None:
                section["items"].append({"paragraph_id": group["first_paragraph_id"], "label": group["label"]})
            for entry in entries.values():
                if start <= positions[entry["paragraph_id"]] <= end:
                    section["items"] = [item for item in section["items"] if item["paragraph_id"] != entry["paragraph_id"]]
                    section["items"].append(entry)
        for section in sections:
            if not section["items"]:
                # A time interval remains reachable without pretending its
                # first internal phase was selected as an important event.
                section["items"] = [{"paragraph_id": section["first_paragraph_id"], "label": "从这段读起"}]
    result = []
    for section in sections:
        start, end = positions[section["first_paragraph_id"]], positions[section["last_paragraph_id"]]
        items = []
        for item in sorted(section["items"], key=lambda item: positions[item["paragraph_id"]]):
            paragraph = paragraphs[positions[item["paragraph_id"]]]
            group = group_by_id[paragraph["group_id"]]
            entry = entries.get(item["paragraph_id"])
            items.append({"paragraph_id": item["paragraph_id"], "ordinal": positions[item["paragraph_id"]],
                          "label": item["label"],
                          "period": group["period"], "importance": "major" if entry else "detail"})
        # A shared era appears once. This only removes a literal repeated
        # prefix in display text, never infers or normalizes historical dates.
        periods = [item["period"] for item in items if item["period"]]
        era_matches = [re.match(r"^([^，·]{1,30}?年)", period) for period in periods]
        era = era_matches[0][1] if era_matches and all(match and match[1] == era_matches[0][1] for match in era_matches) else None
        years = {group_by_id[p["group_id"]]["year"] for p in paragraphs[start:end + 1]}
        if len(years) != 1 or None in years:
            era = None
        if era:
            for item in items:
                if item["period"] and item["period"].startswith(era):
                    item["period"] = item["period"][len(era):].strip(" ，·") or None
        result.append({"id": section["first_paragraph_id"], "label": section["label"], "period": era,
                       "start": start, "end": end, "items": items})
    return result
