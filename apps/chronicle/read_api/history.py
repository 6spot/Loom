"""Published synthesized history. All reads pin one immutable version."""
from __future__ import annotations

import re
from urllib.parse import parse_qs

import narrative_store
from common import PersistenceError
from read_common import ReadModelError, ReadModelNotFound

PREFIX = '/v0/history'


def _query(raw, allowed):
    query = parse_qs(raw, keep_blank_values=True)
    if set(query) - set(allowed) or any(len(values) != 1 for values in query.values()):
        raise ReadModelError('unknown or repeated history query parameter')
    return {name: values[0] for name, values in query.items()}


def _int(query, key, default, low, high):
    raw = query.get(key, str(default))
    if not re.fullmatch(r'0|[1-9][0-9]*', raw):
        raise ReadModelError(f'{key} must be an integer')
    value = int(raw)
    if not low <= value <= high:
        raise ReadModelError(f'{key} must be between {low} and {high}')
    return value


def _publication(conn, query, required=True):
    if required and not query.get('version'):
        raise ReadModelError('history reads require a fixed version')
    try:
        publication = narrative_store.read_publication(conn, query.get('version'))
    except PersistenceError as exc:
        raise ReadModelError(str(exc)) from exc
    if publication is None and (required or query.get('version') is not None):
        raise ReadModelNotFound('this historical narrative version is not published')
    return publication


def _metadata(publication):
    if publication is None:
        return None
    by_id = {p['id']: p for p in publication['paragraphs']}
    groups = {g['id']: g for g in publication['groups']}
    entries = []
    for entry in publication['entry_points']:
        target = by_id[entry['paragraph_id']]
        group = groups[target['group_id']]
        entries.append({**entry, 'ordinal': target['ordinal'], 'year': group['year'],
                        'period': group['period'], 'excerpt': ''.join(s['text'] for s in target['segments'])[:160]})
    return dict(version=publication['publication_version'], catalog_sha=publication['catalog_sha'],
                title=publication['title'], paragraph_count=len(by_id), first_paragraph_id=publication['paragraphs'][0]['id'],
                groups=publication['groups'], entry_points=entries)


def dispatch_history(conn, path, raw_query):
    if path == PREFIX:
        query = _query(raw_query, {'version'})
        return dict(schema='chronicle.history-directory', version='0.1',
                    publication=_metadata(_publication(conn, query, required=False)))
    if path == PREFIX + '/paragraphs':
        query = _query(raw_query, {'version', 'start', 'at', 'limit'})
        limit = _int(query, 'limit', 20, 1, 50)
        if 'at' in query and 'start' in query:
            raise ReadModelError('choose either at or start')
        pub = _publication(conn, query)
        paragraphs = pub['paragraphs']
        if 'at' in query:
            if not re.fullmatch(r'hp_[0-9a-f]{24}', query['at']):
                raise ReadModelError('invalid historical paragraph id')
            target = next((p for p in paragraphs if p['id'] == query['at']), None)
            if target is None:
                raise ReadModelNotFound('paragraph is outside this fixed narrative version')
            start = target['ordinal'] // limit * limit
        else:
            start = _int(query, 'start', 0, 0, len(paragraphs) - 1)
        end = min(start + limit, len(paragraphs))
        return dict(schema='chronicle.history-page', version='0.1', publication_version=pub['publication_version'],
                    paragraphs=paragraphs[start:end], start=start, total=len(paragraphs),
                    previous_start=max(0, start - limit) if start else None,
                    next_start=end if end < len(paragraphs) else None)
    if path.startswith(PREFIX + '/conclusions/'):
        query = _query(raw_query, {'version'})
        pub = _publication(conn, query)
        fact_id = path[len(PREFIX + '/conclusions/'):]
        fact = next((fact for fact in pub['conclusions'] if fact['id'] == fact_id), None)
        if fact is None:
            raise ReadModelNotFound('conclusion is outside this narrative version')
        evidence = [{**pub['evidence'][ref['id']], **ref} for ref in fact['evidence']]
        used_sources = {item['source_id'] for item in evidence}
        return dict(schema='chronicle.history-conclusion', version='0.1', publication_version=pub['publication_version'],
                    conclusion={**fact, 'evidence': evidence}, source_relations=[r for r in pub['source_relations']
                        if r['left'] in used_sources and r['right'] in used_sources])
    raise ReadModelNotFound('history route not found')
