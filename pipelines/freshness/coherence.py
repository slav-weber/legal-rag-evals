"""Coherence of the source/artifact registries.

The check is a PURE function so it can be adversarially red-proofed with injected-drift fixtures
(no live DB): `check_sources_coherence(...)` → list of problem strings (empty = coherent). The
gate wrapper in the dev-setup script loads the live data and calls it.

Symmetric coverage:
  - SOURCES → source_registry: every code-mirror source is upserted, with matching
    url/cadence/staleness_slo_days (drift = the mirror or the DB is stale);
  - source_registry → SOURCES: a registry row not in the mirror is an ORPHAN — REPORTED, never
    auto-deleted (a DELETE would CASCADE and wipe the source_checks history);
  - ARTIFACTS ⊆ artifact_registry: every orchestrated artifact is FK-registered.
"""

from __future__ import annotations

_MATCH_FIELDS = ("url", "cadence", "staleness_slo_days")


def check_sources_coherence(sources, registry_rows, artifacts, artifact_reg_ids) -> list[str]:
    """sources: list[dict] (freshness.sources.SOURCES). registry_rows: {source_id: {url, cadence,
    staleness_slo_days}}. artifacts: iterable of ARTIFACTS ids. artifact_reg_ids: set of
    artifact_registry ids. Returns a list of problem strings (empty = coherent)."""
    problems: list[str] = []
    src_ids = {s["source_id"] for s in sources}

    for s in sources:  # SOURCES → registry: mirror applied + fields coherent
        r = registry_rows.get(s["source_id"])
        if r is None:
            problems.append(f"source '{s['source_id']}' in sources.py but missing from "
                            f"source_registry (mirror not upserted)")
            continue
        for f in _MATCH_FIELDS:
            if r.get(f) != s.get(f):
                problems.append(f"source '{s['source_id']}' {f} drift: "
                                f"sources.py={s.get(f)!r} vs registry={r.get(f)!r}")

    for sid in registry_rows:  # registry → SOURCES: orphan reported, NOT deleted
        if sid not in src_ids:
            problems.append(f"source_registry has '{sid}' not in sources.py "
                            f"(orphan — add to sources.py or investigate; NOT auto-deleted)")

    for aid in artifacts:  # ARTIFACTS ⊆ artifact_registry (FK integrity)
        if aid not in artifact_reg_ids:
            problems.append(f"artifact '{aid}' in ARTIFACTS but not in artifact_registry "
                            f"(FK/registry drift)")

    return problems
