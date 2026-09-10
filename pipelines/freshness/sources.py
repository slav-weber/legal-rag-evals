"""Machine mirror of the data registry — the sources we poll for freshness.

This list is the code-side "source_registry" seed; `probe.py` upserts it into the
Postgres `source_registry` table and polls each entry. All signals were verified
live on 2026-07-04. Probes are LIGHT (a small conditional GET / a JSON metadata
call / a page hash) — never a corpus download.
"""

from __future__ import annotations

# probe_kind:
#   rada_rtxt    — conditional GET of the Rada updates list (Last-Modified / If-Modified-Since)
#   ckan         — CKAN package_show → metadata_modified + resource last_modified
#   hf           — HuggingFace api/datasets/{id} → sha, lastModified
#   listing_hash — GET a listing page → hash of normalised text
#   page_hash    — GET a page → hash of normalised text (no machine signal otherwise)
#   manual       — no machine signal; tracked by hand in the data registry
SOURCES: list[dict] = [
    {
        "source_id": "rada", "name": "data.rada.gov.ua — оновлення НПА",
        "url": "https://data.rada.gov.ua/laws/main/r.txt",
        "probe_kind": "rada_rtxt", "cadence": "daily", "staleness_slo_days": 1,
        "license": "open data (rada)", "probe_params": {},
    },
    {
        "source_id": "ckan-edrsr", "name": "ЄДРСР річні дампи (ДСА, CKAN)",
        "url": "https://data.gov.ua/api/3/action/package_show",
        "probe_kind": "ckan", "cadence": "daily", "staleness_slo_days": 3,
        "license": "CC-BY", "probe_params": {
            "package_id": "ediniy-derzhavniy-reestr-sudovih-rishen-za-2026-rik_7636"},
    },
    {
        "source_id": "ckan-edrnpa", "name": "ЄДРНПА повний дамп (Мінюст, CKAN)",
        "url": "https://data.gov.ua/api/3/action/package_show",
        "probe_kind": "ckan", "cadence": "monthly", "staleness_slo_days": 35,
        "license": "open data (minjust)", "probe_params": {
            "package_id": "c98e830c-e39e-4da6-a13c-f9ba32a79bec"},
    },
    {
        "source_id": "hf-edrsr-kas", "name": "HF overthelex/edrsr-kas (bootstrap)",
        "url": "https://huggingface.co/api/datasets/overthelex/edrsr-kas",
        "probe_kind": "hf", "cadence": "weekly", "staleness_slo_days": 7,
        "license": "CC-BY-4.0", "probe_params": {"pinned_sha": "69861a4b"},
    },
    {
        # URL + method taken from our OWN registry row and verified live — never
        # guessed. windows-1251; signal = hash of the SET of entry
        # IDs on page 1 (not raw HTML — robust to markup/date churn).
        "source_id": "supreme-court", "name": "supreme.court.gov.ua — огляди/дайджести ВС",
        "url": "https://supreme.court.gov.ua/supreme/pres-centr/info_anons_daidgest_oglyad/",
        "probe_kind": "listing_hash", "cadence": "weekly", "staleness_slo_days": 7,
        "license": "open (court)", "probe_params": {
            "encoding": "windows-1251",
            "id_regex": r"/info_anons_daidgest_oglyad/(\d{5,9})/"},
    },
    # Watcher sources (probe_kind='manual'): the light probe does NOT poll these — their OWN
    # collectors write source_checks (rada_backstop.run, rada/reachability). They live here ONLY
    # so probe._upsert_sources is the SINGLE writer of their source_registry row (was an inline
    # self-INSERT in each watcher — since removed). Values match those rows verbatim.
    {
        "source_id": "rada-backstop", "name": "Rada seed-act card backstop (datred/edcnt)",
        "url": "https://data.rada.gov.ua/laws/card/{nreg}.json",
        "probe_kind": "manual", "cadence": "weekly", "staleness_slo_days": 7,
        "license": "open data (rada)", "probe_params": {},
    },
    {
        "source_id": "rada-reachability", "name": "Rada open-data reachability (R-21 watcher signal)",
        "url": "https://data.rada.gov.ua/laws/card/1404-19.json",
        "probe_kind": "manual", "cadence": "hourly", "staleness_slo_days": 1,
        "license": "open data (rada)", "probe_params": {},
    },
]
