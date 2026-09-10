"""The freshness probe must not turn errors (non-200, junk bodies, missing fields) into a
valid signal.

    uv run python tests/test_freshness_probe_errors.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.freshness import probe  # noqa: E402


class _FakeResp:
    def __init__(self, status=200, text="", jsond=None, ct=""):
        self.status_code = status
        self.content = text.encode("utf-8")
        self.text = text
        self.headers = {"content-type": ct} if ct else {}
        self._j = jsond

    def json(self):
        return self._j


def _src(kind, **pp):
    return {"probe_kind": kind, "url": "http://x", "probe_params": pp}


SEEDS = {"3633-20": "3633-20", "3633-IX": "3633-20"}


def _patch(resp):
    return mock.patch.object(probe, "_get", lambda *a, **k: resp)


class Rada(unittest.TestCase):
    def test_non200_is_probe_fail(self):
        with _patch(_FakeResp(403)):
            sig, note = probe.probe(_src("rada_rtxt"), SEEDS)
        self.assertIsNone(sig)
        self.assertIn("403", note)

    def test_html_junk_is_probe_fail(self):
        with _patch(_FakeResp(200, text="<html><body>captcha</body></html>" + " " * 80)):
            sig, _ = probe.probe(_src("rada_rtxt"), SEEDS)
        self.assertIsNone(sig)

    def test_plaintext_junk_without_nreg_is_probe_fail(self):
        # a plausible-size 200 with NO nreg-like line is not an honest "none".
        with _patch(_FakeResp(200, text="service temporarily unavailable, please try later " * 3)):
            sig, note = probe.probe(_src("rada_rtxt"), SEEDS)
        self.assertIsNone(sig)
        self.assertIn("no nreg", note)

    def test_valid_body_yields_signal(self):
        body = "3633-20\t20260705\tзакон про мобілізацію\n1234-20\t20260701\tінше\n"
        with _patch(_FakeResp(200, text=body)):
            sig, note = probe.probe(_src("rada_rtxt"), SEEDS)
        self.assertIsNotNone(sig)
        self.assertIn("3633-20", note)


class Hf(unittest.TestCase):
    def test_404_is_probe_fail(self):
        with _patch(_FakeResp(404, jsond={})):
            self.assertIsNone(probe.probe(_src("hf", pinned_sha="69861a4b"))[0])

    def test_no_sha_is_probe_fail(self):
        with _patch(_FakeResp(200, jsond={"lastModified": "x"})):
            self.assertIsNone(probe.probe(_src("hf"))[0])

    def test_on_pin(self):
        with _patch(_FakeResp(200, jsond={"sha": "69861a4b1040", "lastModified": "x"})):
            sig, note = probe.probe(_src("hf", pinned_sha="69861a4b"))
        self.assertEqual(sig, "69861a4b1040")
        self.assertNotIn("off-pin", note)

    def test_off_pin_flagged(self):
        with _patch(_FakeResp(200, jsond={"sha": "deadbeef0000", "lastModified": "x"})):
            sig, note = probe.probe(_src("hf", pinned_sha="69861a4b"))
        self.assertIn("off-pin", note)


class Listing(unittest.TestCase):
    def test_non200_no_error_page_hash(self):
        with _patch(_FakeResp(500, text="<html>error</html>")):
            sig, note = probe.probe(_src("listing_hash", id_regex=r"(\d+)"))
        self.assertIsNone(sig)
        self.assertIn("500", note)


if __name__ == "__main__":
    unittest.main(verbosity=2)
