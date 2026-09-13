"""Simplified reader text; never normalize source selectors or identity keys."""
from __future__ import annotations

import copy
from functools import lru_cache

from opencc import OpenCC

_CONVERTER = OpenCC("t2s")


@lru_cache(maxsize=512)
def simplified(text: str) -> str:
    return _CONVERTER.convert(text)


def _fields(record, *names):
    for name in names:
        if isinstance(record.get(name), str):
            record[name] = simplified(record[name])


def _records(record, name):
    values = record.get(name)
    return [value for value in values if isinstance(value, dict)] if isinstance(values, list) else []


def narrative_text(value: dict) -> dict:
    """Normalize only editorial text, before review; provider raw output survives."""
    result = copy.deepcopy(value)
    if not isinstance(result, dict):
        return result
    _fields(result, "title")
    for phase in _records(result, "phases"):
        _fields(phase, "label", "period")
    for fact in _records(result, "conclusions"):
        _fields(fact, "question", "text", "value", "reason")
        for reference in _records(fact, "evidence"):
            _fields(reference, "attribution", "note")
    for relation in _records(result, "source_relations"):
        _fields(relation, "reason")
    for paragraph in _records(result, "paragraphs"):
        for segment in _records(paragraph, "segments"):
            _fields(segment, "text", "event_text")
    for entry in _records(result, "entry_points"):
        _fields(entry, "label", "reason")
    for section in _records(result, "navigation"):
        _fields(section, "label")
        for item in _records(section, "items"):
            _fields(item, "label", "reason")
    return result


def history_display(publication: dict) -> dict:
    """Read-only glyph projection. Quotes, source ranges and all IDs stay exact."""
    result = narrative_text(publication)
    for group in _records(result, "groups"):
        _fields(group, "label", "period")
    for paragraph in _records(result, "paragraphs"):
        for entity in _records(paragraph, "entities"):
            _fields(entity, "name")
            for state in _records(entity, "states"):
                _fields(state, "label", "value", "reason")
    return result
