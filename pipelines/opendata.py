"""Optional Authorization for data.gov.ua (CKAN) open-data requests.

An OPEN_DATA_API_KEY was added on 2026-07-06 (in the gitignored .env). When
present, CKAN calls send `Authorization: Bearer <key>`; when absent, requests stay
anonymous exactly as before (the key is optional — its absence never breaks a run).
The key is NEVER logged or printed — only injected into request headers here.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def auth_headers(headers: dict | None = None) -> dict:
    """Return `headers` plus an Authorization bearer if OPEN_DATA_API_KEY is set.

    Use for data.gov.ua / CKAN requests only. No key -> unchanged (anonymous).
    """
    out = dict(headers or {})
    key = os.getenv("OPEN_DATA_API_KEY")
    if key:
        out["Authorization"] = f"Bearer {key}"
    return out


def have_key() -> bool:
    """True if an OPEN_DATA_API_KEY is configured (never reveals the value)."""
    return bool(os.getenv("OPEN_DATA_API_KEY"))
