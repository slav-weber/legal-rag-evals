"""HTTP-client tests: honest reachability signal + no-follow RadaRoutingError.

    uv run python tests/test_rada_reachability.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.checks import _common as cm  # noqa: E402
from pipelines.rada import reachability as rc  # noqa: E402


class _Resp:
    """Minimal httpx.Response stand-in (status/headers/content + is_redirect)."""

    def __init__(self, status, ct="", body=b"", loc=None):
        self.status_code = status
        self.headers = {}
        if ct:
            self.headers["content-type"] = ct
        if loc:
            self.headers["location"] = loc
        self.content = body

    @property
    def is_redirect(self):
        return self.status_code in (301, 302, 303, 307, 308)


class Classify(unittest.TestCase):
    def test_green_json(self):
        r = _Resp(200, "application/json; charset=utf-8", b'{"dokid": 1}')
        self.assertEqual(rc.classify(r)[0], rc.GREEN)

    def test_red_html_body(self):
        # 200 but HTML (the UA-routing-to-zakon case that faked a «migration»)
        r = _Resp(200, "text/html; charset=utf-8", b"<!DOCTYPE html>")
        self.assertEqual(rc.classify(r)[0], rc.RED)

    def test_red_json_ct_but_not_object(self):
        r = _Resp(200, "application/json", b"garbage not json")
        self.assertEqual(rc.classify(r)[0], rc.RED)

    def test_yellow_403(self):
        # temporary anti-DDoS IP block -> YELLOW (back off in hours), not RED
        self.assertEqual(rc.classify(_Resp(403, "text/html", b"blocked"))[0], rc.YELLOW)

    def test_red_redirect_with_correct_ua(self):
        r = _Resp(302, loc="https://zakon.rada.gov.ua/laws/card/1404-19.json")
        self.assertEqual(rc.classify(r)[0], rc.RED)

    def test_error_5xx(self):
        self.assertEqual(rc.classify(_Resp(503))[0], rc.ERROR)


class GetNoFollow(unittest.TestCase):
    def test_raises_rada_routing_error_on_redirect(self):
        fake = _Resp(302, loc="https://zakon.rada.gov.ua/laws/card/x.json")
        with mock.patch.object(cm.httpx, "get", return_value=fake), \
             mock.patch.object(cm, "polite_sleep", lambda: None):
            with self.assertRaises(cm.RadaRoutingError):
                cm.get("https://data.rada.gov.ua/laws/card/x.json")

    def test_opt_in_follow_does_not_raise(self):
        # a legit same-host attachment 302 with follow_redirects=True must NOT raise
        fake = _Resp(302, loc="https://data.rada.gov.ua/laws/file/text/1/x")
        with mock.patch.object(cm.httpx, "get", return_value=fake), \
             mock.patch.object(cm, "polite_sleep", lambda: None):
            r = cm.get("https://data.rada.gov.ua/laws/file/x", follow_redirects=True)
            self.assertEqual(r.status_code, 302)

    def test_200_passes_through(self):
        fake = _Resp(200, "application/json", b"{}")
        with mock.patch.object(cm.httpx, "get", return_value=fake), \
             mock.patch.object(cm, "polite_sleep", lambda: None):
            self.assertEqual(cm.get("https://data.rada.gov.ua/x.json").status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
