"""Deterministic, read-only Chronicle corpus Coverage projection.

Coverage is an application-owned measurement over the currently published
Chronicle corpus. It is deliberately not historical truth: missing rows mean
"not represented in the current corpus", never "nothing happened".

C1-T14 keeps this projection recomputable instead of persisting a second
coverage authority. The latest canonical catalog defines published historical
membership; merely staged/in-flight bundles are excluded.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median
from typing import Any

from read_common import ReadModelError, display_surface, normalized_year


COVERAGE_SCHEMA = "chronicle.coverage"
COVERAGE_VERSION = "0.1"
ABSENCE_SEMANTICS = (
    "A zero or missing Chronicle count means the current corpus does not represent "
    "that material; it is not evidence that no historical event, entity, or source existed."
)
DENSITY_SEMANTICS = (
    "Year density is relative to this Chronicle corpus only. 'unrepresented' means zero "
    "published canonical Events with that observed normalized year; 'sparse' means a "
    "positive count below the median of represented years. It is not a completeness score."
)
DOMAIN_SEMANTICS = (
    "Domain categories are deterministic display surfaces of persisted Event.type values; "
    "Chronicle does not infer an external or exhaustive historical taxonomy here."
)


def _validate_range(from_year: int | None, to_year: int | None) -> None:
    if from_year is not None and not isinstance(from_year, int):
        raise ReadModelError("from_year must be an integer")
    if to_year is not None and not isinstance(to_year, int):
        raise ReadModelError("to_year must be an integer")
    if from_year is not None and to_year is not None and from_year > to_year:
        raise ReadModelError("from_year must be <= to_year")
    for value, name in ((from_year, "from_year"), (to_year, "to_year")):
        if value is not None and (value < -10000 or value > 10000):
            raise ReadModelError(f"{name} is outside the supported reporting range")


def _latest_catalog_sha(conn) -> str | None:
    row = conn.execute(
        """
        SELECT artifact_sha256
        FROM chronicle.canonical_catalogs
        ORDER BY imported_at DESC, artifact_sha256 DESC
        LIMIT 1
        """
    ).fetchone()
    return str(row[0]) if row else None


def _published_labels(conn, catalog_sha: str | None) -> set[str]:
    if catalog_sha is None:
        return set()
    rows = conn.execute(
        """
        SELECT DISTINCT r.bundle_label
        FROM chronicle.canonical_catalog_entities m
        JOIN chronicle.canonical_entity_representations r
          ON r.canonical_id = m.canonical_id
        WHERE m.catalog_sha256 = %s
        UNION
        SELECT DISTINCT r.bundle_label
        FROM chronicle.canonical_catalog_events m
        JOIN chronicle.canonical_event_representations r
          ON r.canonical_id = m.canonical_id
        WHERE m.catalog_sha256 = %s
        ORDER BY 1
        """,
        (catalog_sha, catalog_sha),
    ).fetchall()
    return {str(row[0]) for row in rows}


def _event_rows(conn, catalog_sha: str | None) -> list[dict[str, Any]]:
    if catalog_sha is None:
        return []
    rows = conn.execute(
        """
        SELECT m.canonical_id::text, r.bundle_label, r.record_ref, e.payload
        FROM chronicle.canonical_catalog_events m
        JOIN chronicle.canonical_event_representations r
          ON r.canonical_id = m.canonical_id
        JOIN chronicle.staged_events e
          ON e.bundle_label = r.bundle_label AND e.record_ref = r.record_ref
        WHERE m.catalog_sha256 = %s
        ORDER BY m.canonical_id, r.bundle_label, r.record_ref
        """,
        (catalog_sha,),
    ).fetchall()
    return [
        {
            "canonical_id": row[0],
            "bundle": row[1],
            "ref": row[2],
            "payload": row[3],
        }
        for row in rows
    ]


def _entity_rows(conn, catalog_sha: str | None) -> list[dict[str, Any]]:
    if catalog_sha is None:
        return []
    rows = conn.execute(
        """
        SELECT m.canonical_id::text, r.bundle_label, r.record_ref, e.payload
        FROM chronicle.canonical_catalog_entities m
        JOIN chronicle.canonical_entity_representations r
          ON r.canonical_id = m.canonical_id
        JOIN chronicle.staged_entities e
          ON e.bundle_label = r.bundle_label AND e.record_ref = r.record_ref
        WHERE m.catalog_sha256 = %s
        ORDER BY m.canonical_id, r.bundle_label, r.record_ref
        """,
        (catalog_sha,),
    ).fetchall()
    return [
        {
            "canonical_id": row[0],
            "bundle": row[1],
            "ref": row[2],
            "payload": row[3],
        }
        for row in rows
    ]


def _group_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["canonical_id"]].append(row)
    return dict(grouped)


def _surface_counts(
    grouped: dict[str, list[dict[str, Any]]], field: str
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for rows in grouped.values():
        surface = display_surface(row["payload"].get(field) for row in rows) or "unknown"
        counts[surface] += 1
    return [
        {"value": value, "count": counts[value]}
        for value in sorted(counts, key=lambda item: (-counts[item], item))
    ]


def _event_measurements(
    grouped: dict[str, list[dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    measurements: dict[str, dict[str, Any]] = {}
    for canonical_id, rows in grouped.items():
        years = sorted(
            {
                year
                for row in rows
                if (year := normalized_year(row["payload"])) is not None
            }
        )
        measurements[canonical_id] = {
            "years": years,
            "type": display_surface(row["payload"].get("type") for row in rows) or "unknown",
            "bundles": sorted({row["bundle"] for row in rows}),
        }
    return measurements


def _in_scope(years: list[int], from_year: int | None, to_year: int | None) -> bool:
    if from_year is None and to_year is None:
        return True
    return any(
        (from_year is None or year >= from_year) and (to_year is None or year <= to_year)
        for year in years
    )


def _time_density(
    measurements: dict[str, dict[str, Any]],
    from_year: int | None,
    to_year: int | None,
) -> dict[str, Any]:
    all_years = sorted({year for item in measurements.values() for year in item["years"]})
    known_start = all_years[0] if all_years else None
    known_end = all_years[-1] if all_years else None

    report_start = from_year if from_year is not None else known_start
    report_end = to_year if to_year is not None else known_end
    if report_start is None or report_end is None:
        requested_years: list[int] = []
    else:
        # Reporting is intentionally bounded. The validation range caps the
        # largest possible result at 20,001 tiny rows.
        requested_years = list(range(report_start, report_end + 1))

    per_year_events: dict[int, set[str]] = defaultdict(set)
    per_year_sources: dict[int, set[str]] = defaultdict(set)
    per_year_types: dict[int, Counter[str]] = defaultdict(Counter)
    for canonical_id, item in measurements.items():
        for year in item["years"]:
            if report_start is not None and year < report_start:
                continue
            if report_end is not None and year > report_end:
                continue
            per_year_events[year].add(canonical_id)
            per_year_sources[year].update(item["bundles"])
            per_year_types[year][item["type"]] += 1

    positive_counts = [len(per_year_events[year]) for year in requested_years if per_year_events[year]]
    represented_median = float(median(positive_counts)) if positive_counts else None
    years = []
    for year in requested_years:
        event_count = len(per_year_events[year])
        if event_count == 0:
            density = "unrepresented"
        elif represented_median is not None and event_count < represented_median:
            density = "sparse"
        else:
            density = "represented"
        years.append(
            {
                "year": year,
                "event_count": event_count,
                "source_count": len(per_year_sources[year]),
                "density": density,
                "event_types": [
                    {"value": value, "count": per_year_types[year][value]}
                    for value in sorted(
                        per_year_types[year],
                        key=lambda item: (-per_year_types[year][item], item),
                    )
                ],
            }
        )

    scoped_event_ids = {
        canonical_id
        for canonical_id, item in measurements.items()
        if _in_scope(item["years"], from_year, to_year)
    }
    unknown_time = sum(1 for item in measurements.values() if not item["years"])
    return {
        "known_year_span": {"start_year": known_start, "end_year": known_end},
        "unknown_time_event_count": unknown_time,
        "represented_year_median_event_count": represented_median,
        "requested_year_count": len(requested_years),
        "represented_requested_year_count": sum(1 for item in years if item["event_count"] > 0),
        "unrepresented_requested_year_count": sum(1 for item in years if item["event_count"] == 0),
        "scoped_event_count": len(scoped_event_ids),
        "years": years,
    }


def _source_contributions(
    conn,
    published_labels: set[str],
    event_grouped: dict[str, list[dict[str, Any]]],
    entity_grouped: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    if not published_labels:
        return []
    source_meta = {
        str(row[0]): {"source_ref": row[1], "source_title": row[2]}
        for row in conn.execute(
            """
            SELECT bundle_label, source_ref, source_title
            FROM chronicle.source_bundles
            ORDER BY bundle_label
            """
        ).fetchall()
        if str(row[0]) in published_labels
    }
    claim_counts: Counter[str] = Counter(
        str(row[0])
        for row in conn.execute(
            "SELECT bundle_label FROM chronicle.staged_claims ORDER BY bundle_label, record_ref"
        ).fetchall()
        if str(row[0]) in published_labels
    )
    event_ids: dict[str, set[str]] = defaultdict(set)
    entity_ids: dict[str, set[str]] = defaultdict(set)
    for canonical_id, rows in event_grouped.items():
        for row in rows:
            event_ids[row["bundle"]].add(canonical_id)
    for canonical_id, rows in entity_grouped.items():
        for row in rows:
            entity_ids[row["bundle"]].add(canonical_id)

    result = []
    for label in sorted(published_labels):
        meta = source_meta.get(label, {"source_ref": None, "source_title": None})
        result.append(
            {
                "bundle": label,
                "source_ref": meta["source_ref"],
                "source_title": meta["source_title"],
                "canonical_entity_count": len(entity_ids[label]),
                "canonical_event_count": len(event_ids[label]),
                "claim_count": claim_counts[label],
            }
        )
    return result


def _document_contributions(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            d.document_id::text,
            d.title,
            r.revision_id::text,
            r.revision_no,
            r.source_label,
            r.language,
            r.content_chars,
            j.status
        FROM chronicle.documents d
        JOIN chronicle.document_current_revisions r ON r.document_id = d.document_id
        LEFT JOIN LATERAL (
            SELECT status
            FROM chronicle.ingestion_jobs j
            WHERE j.revision_id = r.revision_id
            ORDER BY j.created_at DESC, j.job_id DESC
            LIMIT 1
        ) j ON TRUE
        ORDER BY d.title, d.document_id
        """
    ).fetchall()
    return [
        {
            "document_id": row[0],
            "title": row[1],
            "current_revision_id": row[2],
            "revision_no": int(row[3]),
            "source_label": row[4],
            "language": row[5],
            "content_chars": int(row[6]),
            "latest_job_status": row[7],
        }
        for row in rows
    ]


def _review_debt(conn) -> dict[str, int]:
    row = conn.execute(
        """
        SELECT
            count(*) FILTER (WHERE status = 'open'),
            count(*) FILTER (WHERE status = 'open' AND payload->>'scope' = 'resolution'),
            count(*) FILTER (WHERE status = 'resolved'),
            count(*) FILTER (WHERE status = 'dismissed')
        FROM chronicle.review_items
        """
    ).fetchone()
    return {
        "open": int(row[0] if row else 0),
        "open_resolution": int(row[1] if row else 0),
        "resolved": int(row[2] if row else 0),
        "dismissed": int(row[3] if row else 0),
    }


def _presentation_coverage(conn, catalog_sha: str | None) -> dict[str, int]:
    if catalog_sha is None:
        return {
            "entity_targets": 0,
            "event_targets": 0,
            "published_entity_targets": 0,
            "published_event_targets": 0,
            "entity_targets_without_published_presentation": 0,
            "event_targets_without_published_presentation": 0,
        }
    row = conn.execute(
        """
        WITH entities AS (
            SELECT canonical_id
            FROM chronicle.canonical_catalog_entities
            WHERE catalog_sha256 = %s
        ), events AS (
            SELECT canonical_id
            FROM chronicle.canonical_catalog_events
            WHERE catalog_sha256 = %s
        ), presented_entities AS (
            SELECT DISTINCT canonical_entity_id AS canonical_id
            FROM chronicle.reader_presentations
            WHERE status = 'published' AND canonical_entity_id IS NOT NULL
        ), presented_events AS (
            SELECT DISTINCT canonical_event_id AS canonical_id
            FROM chronicle.reader_presentations
            WHERE status = 'published' AND canonical_event_id IS NOT NULL
        )
        SELECT
            (SELECT count(*) FROM entities),
            (SELECT count(*) FROM events),
            (SELECT count(*) FROM entities e JOIN presented_entities p USING (canonical_id)),
            (SELECT count(*) FROM events e JOIN presented_events p USING (canonical_id))
        """,
        (catalog_sha, catalog_sha),
    ).fetchone()
    entity_targets = int(row[0])
    event_targets = int(row[1])
    published_entities = int(row[2])
    published_events = int(row[3])
    return {
        "entity_targets": entity_targets,
        "event_targets": event_targets,
        "published_entity_targets": published_entities,
        "published_event_targets": published_events,
        "entity_targets_without_published_presentation": entity_targets - published_entities,
        "event_targets_without_published_presentation": event_targets - published_events,
    }


def build_coverage(
    conn,
    *,
    from_year: int | None = None,
    to_year: int | None = None,
    include_operational: bool = False,
) -> dict[str, Any]:
    """Build one deterministic Coverage response using SELECT-only state."""
    _validate_range(from_year, to_year)
    catalog_sha = _latest_catalog_sha(conn)
    published_labels = _published_labels(conn, catalog_sha)
    event_grouped = _group_rows(_event_rows(conn, catalog_sha))
    entity_grouped = _group_rows(_entity_rows(conn, catalog_sha))
    event_measurements = _event_measurements(event_grouped)

    scoped_event_ids = {
        canonical_id
        for canonical_id, item in event_measurements.items()
        if _in_scope(item["years"], from_year, to_year)
    }
    domain_counts: Counter[str] = Counter(
        event_measurements[canonical_id]["type"] for canonical_id in scoped_event_ids
    )

    claim_rows = conn.execute(
        "SELECT bundle_label, payload FROM chronicle.staged_claims ORDER BY bundle_label, record_ref"
    ).fetchall()
    published_claims = [row[1] for row in claim_rows if str(row[0]) in published_labels]
    predicate_counts = Counter(
        str(payload.get("predicate") or "unknown") for payload in published_claims
    )

    payload: dict[str, Any] = {
        "schema": COVERAGE_SCHEMA,
        "version": COVERAGE_VERSION,
        "authority": {
            "kind": "derived_projection",
            "historical_truth": False,
            "mutates_history": False,
            "publication_boundary": "latest_canonical_catalog",
            "absence_semantics": ABSENCE_SEMANTICS,
            "density_semantics": DENSITY_SEMANTICS,
            "domain_semantics": DOMAIN_SEMANTICS,
        },
        "query": {"from_year": from_year, "to_year": to_year},
        "catalog": {
            "status": "published" if catalog_sha is not None else "unknown",
            "latest_catalog_sha256": catalog_sha,
            "published_source_bundle_count": len(published_labels),
        },
        "time": _time_density(event_measurements, from_year, to_year),
        "sources": _source_contributions(
            conn, published_labels, event_grouped, entity_grouped
        ),
        "domains": {
            "basis": "event.type",
            "event_types": [
                {"value": value, "count": domain_counts[value]}
                for value in sorted(domain_counts, key=lambda item: (-domain_counts[item], item))
            ],
            "claim_predicates": [
                {"value": value, "count": predicate_counts[value]}
                for value in sorted(
                    predicate_counts, key=lambda item: (-predicate_counts[item], item)
                )
            ],
        },
        "entities": {
            "canonical_count": len(entity_grouped),
            "types": _surface_counts(entity_grouped, "type"),
        },
        "events": {
            "canonical_count": len(event_grouped),
            "scoped_canonical_count": len(scoped_event_ids),
            "types": _surface_counts(
                {key: event_grouped[key] for key in scoped_event_ids}, "type"
            ),
        },
        "claims": {"published_source_claim_count": len(published_claims)},
        "presentations": _presentation_coverage(conn, catalog_sha),
        "review_debt": _review_debt(conn),
    }
    if include_operational:
        payload["documents"] = _document_contributions(conn)
    return payload
