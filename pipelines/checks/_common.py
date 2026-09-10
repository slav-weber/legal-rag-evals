"""Shared helpers for the pre-build data-source checks.

These are read-only probes of open data sources. Politeness is MANDATORY:
User-Agent ``OpenData`` for Rada / data.gov.ua, <= 60 req/min with a 5-7s
pause between requests, and never pull more than ~50 MB from any single
resource.
"""

from __future__ import annotations

import sys
import time

import httpx

# Windows consoles often default to cp1251 and mojibake/crash on Cyrillic output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

RADA_UA = "OpenData"
POLITE_PAUSE_S = 6.0          # 5-7s between requests to Rada / data.gov.ua
MAX_BYTES = 50 * 1024 * 1024  # 50 MB politeness cap per resource

_last_call = {"t": 0.0}


class RadaRoutingError(RuntimeError):
    """A data.rada opendata endpoint answered with a REDIRECT instead of the resource.

    data.rada serves JSON/text only to the OpenData User-Agent and does NOT redirect a
    well-formed opendata request; a 3xx means the request was routed away — the UA was
    lost on the wire, or the IP hit Rada's temporary anti-DDoS block that bounces
    non-opendata clients to the human site zakon.rada.gov.ua (which serves HTML and
    would silently poison a JSON/text caller). Surface it, never follow it. The
    2026-07-09 "migration" false alarm came from exactly this — a browser UA + a
    followed 302 to zakon-HTML looked like the JSON API had moved when it had not."""


def polite_sleep() -> None:
    """Block so consecutive polite requests stay >= POLITE_PAUSE_S apart."""
    elapsed = time.monotonic() - _last_call["t"]
    if 0 < elapsed < POLITE_PAUSE_S:
        time.sleep(POLITE_PAUSE_S - elapsed)
    _last_call["t"] = time.monotonic()


def get(
    url: str,
    *,
    ua: str = RADA_UA,
    headers: dict | None = None,
    range_header: str | None = None,
    timeout: float = 90.0,
    polite: bool = True,
    follow_redirects: bool = False,
) -> httpx.Response:
    """GET a URL with the polite defaults. ``polite=False`` skips the pause (use for a
    burst of Range reads against one already-open resource).

    ``follow_redirects`` defaults to False. An opendata endpoint that answers a
    3xx is an anomaly, not a hop to follow — following it (to zakon-HTML) is what turned
    a lost-UA / anti-DDoS episode into a phantom "API migration". A redirect raises a
    self-diagnosing RadaRoutingError naming the UA actually sent. Callers with a
    LEGITIMATE redirect (same-host attachment 302, arbitrary external snapshot URL,
    a CKAN/HF endpoint) opt in with ``follow_redirects=True``."""
    if polite:
        polite_sleep()
    h = {"User-Agent": ua}
    if headers:
        h.update(headers)
    if range_header:
        h["Range"] = range_header
    r = httpx.get(url, headers=h, timeout=timeout, follow_redirects=follow_redirects)
    if not follow_redirects and r.is_redirect:
        loc = r.headers.get("location", "?")
        raise RadaRoutingError(
            f"{url} -> HTTP {r.status_code} redirect to {loc!r}; UA sent={ua!r}. "
            f"An opendata endpoint must answer 200 to UA 'OpenData' with no redirect; "
            f"a 3xx = request routed away (UA lost / temporary IP anti-DDoS block).")
    return r


def get_text(url: str, *, encoding: str = "utf-8", **kw) -> str:
    r = get(url, **kw)
    r.raise_for_status()
    r.encoding = encoding
    return r.text


def get_json(url: str, **kw):
    r = get(url, **kw)
    r.raise_for_status()
    return r.json()


def header(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def die(msg: str) -> None:
    print(f"CHECK FAILED: {msg}")
    sys.exit(1)
