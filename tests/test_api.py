"""Thin API seam pins. FastAPI TestClient on a STUB backend; the live LLM is NEVER called in
the suite (generate_fn is injected). Covers: the 200 shape with lint/duration in meta,
abstain=200, 200+degraded (honest degradation surfaced), 422 (blank / bad as_of / >2000 chars),
503 via monkeypatch (no stacktrace body), and the startup reranker pin (drift → refuse to start;
unavailable → start degraded).

    uv run python -m unittest discover -s tests -p test_api.py -q
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _HermeticData(unittest.TestCase):
    """The seam writes a trace per request — point DATA_DIR at a temp dir so the suite NEVER
    writes into the real data dir."""

    def setUp(self):
        import shutil
        self.data_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data_dir, ignore_errors=True)   # no orphan temp dirs
        p = mock.patch.dict("os.environ", {"DATA_DIR": self.data_dir})
        p.start()
        self.addCleanup(p.stop)

    def _trace_lines(self) -> list[str]:
        path = Path(self.data_dir) / "traces" / "t14" / "traces.jsonl"
        return path.read_text(encoding="utf-8").splitlines() if path.is_file() else []


def _result(**over) -> dict:
    """A valid generate()-shaped result (the seam only reads it — no pipeline run)."""
    r = {
        "dovidka": {"vysnovok": "Висновок.", "diyi": [], "abstain": False,
                    "obgruntuvannya": [{"teza": "Теза.", "citations": ["C1"]}]},
        "resolved": {"C1": "Акт, ст.1"},
        "candidates": [{"id": "C1", "act": "X", "unit_path": "ст.1", "citation": "Акт, ст.1"}],
        "abstained": False, "route": "channels", "degraded": [], "reranked": True, "dropped": {},
        "lint": {"prose_refs_unbacked": [], "leaked_cids": [], "diyi_refs_unbacked": [],
                 "prose_refs_ambiguous_act": []},
        "attempts": [{"request_id": "rid-xyz"}],
    }
    r.update(over)
    return r


def _client(gen, verify_pin=lambda: "stub-pin"):
    from fastapi.testclient import TestClient

    from api.main import create_app
    return TestClient(create_app(generate_fn=gen, verify_pin=verify_pin))


class ApiSeam(_HermeticData):
    def test_trace_written_so_trace_ref_resolves(self):
        # Regression: trace_ref used to be a DANGLING pointer — the seam never called
        # write_trace, so the request_id resolved to nothing. Now the POSTed request_id MUST
        # appear in the t14 trace pool.
        b = _client(lambda q, a: _result()).post(
            "/api/generate", json={"question": "Що передбачає ст.1?"}).json()
        lines = self._trace_lines()
        self.assertTrue(lines, "seam wrote no trace — trace_ref would dangle")
        # Match the FIELD, not a substring of the JSON line — a substring would also pass if
        # the id merely landed in some unrelated field.
        ids = [json.loads(ln)["attempts"][-1]["request_id"] for ln in lines]
        self.assertIn(b["trace_ref"], ids)                   # the handle RESOLVES to the record

    def test_trace_write_failure_drops_trace_ref(self):
        # a handle that resolves to nothing is worse than no field: if persistence fails, the
        # response must carry trace_ref=None rather than a dangling id — AND must not 500 the
        # caller.
        with mock.patch("pipelines.rag.generate.write_trace", side_effect=OSError("disk full")):
            r = _client(lambda q, a: _result()).post("/api/generate", json={"question": "щось"})
        self.assertEqual(r.status_code, 200)                 # persistence failure ≠ 500
        self.assertIsNone(r.json()["trace_ref"])

    def test_504_timeout(self):
        # 504 was the only uncovered leg of the contract. GENERATE_TIMEOUT_S is a module global
        # read at request time → patchable; a slow stub trips it.
        import time as _t

        def _slow(q, a):
            _t.sleep(0.5)
            return _result()
        with mock.patch("api.main.GENERATE_TIMEOUT_S", 0.05):
            r = _client(_slow).post("/api/generate", json={"question": "щось"})
        self.assertEqual(r.status_code, 504)
        b = r.json()
        self.assertEqual(b["error"], "timeout")
        self.assertEqual(set(b), {"error", "message"})       # uniform body, no stacktrace

    def test_ok_200_shape_lint_and_duration_in_meta(self):
        c = _client(lambda q, a: _result())
        r = c.post("/api/generate", json={"question": "Що передбачає ст.1?"})
        self.assertEqual(r.status_code, 200)
        b = r.json()
        self.assertEqual(set(b), {"dovidka", "html", "meta", "trace_ref"})
        self.assertEqual(b["trace_ref"], "rid-xyz")          # request_id ONLY, never a path
        self.assertIn("prose_refs_ambiguous_act", b["meta"]["lint"])   # act-scoped lint surfaced
        self.assertIsInstance(b["meta"]["duration_ms"], int)           # duration reported in ms

    def test_as_of_passed_through(self):
        seen = {}

        def _gen(q, a):
            seen["as_of"] = a
            return _result()
        c = _client(_gen)
        c.post("/api/generate", json={"question": "щось", "as_of": "2024-01-15"})
        self.assertEqual(seen["as_of"], "2024-01-15")

    def test_abstain_is_200(self):
        res = _result(abstained=True, attempts=[],
                      dovidka={"vysnovok": "Недостатньо підстав.", "diyi": [],
                               "obgruntuvannya": [], "abstain": True})
        r = _client(lambda q, a: res).post("/api/generate", json={"question": "щось"})
        self.assertEqual(r.status_code, 200)                 # abstain = valid outcome
        b = r.json()
        self.assertTrue(b["meta"]["abstained"])
        self.assertIsNone(b["trace_ref"])                    # no attempts → None, not a path

    def test_degraded_reranker_is_200_and_surfaced(self):
        res = _result(degraded=["reranker"], reranked=False)
        b = _client(lambda q, a: res).post("/api/generate", json={"question": "щось"}).json()
        self.assertEqual(b["meta"]["degraded"], ["reranker"])   # degradation surfaced, not 500
        self.assertFalse(b["meta"]["reranked"])

    def test_422_blank_question(self):
        r = _client(lambda q, a: _result()).post("/api/generate", json={"question": "   "})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"], "validation_error")   # uniform body, not detail array

    def test_422_bad_as_of(self):
        r = _client(lambda q, a: _result()).post("/api/generate",
                                                 json={"question": "щось", "as_of": "15.01.2024"})
        self.assertEqual(r.status_code, 422)

    def test_422_question_too_long(self):
        r = _client(lambda q, a: _result()).post("/api/generate", json={"question": "я" * 2001})
        self.assertEqual(r.status_code, 422)

    def test_503_deepseek_unavailable_no_stacktrace(self):
        import httpx
        import openai

        def _boom(q, a):
            raise openai.APIConnectionError(request=httpx.Request("POST", "http://localhost:1234"))
        r = _client(_boom).post("/api/generate", json={"question": "щось"})
        self.assertEqual(r.status_code, 503)
        b = r.json()
        self.assertEqual(b["error"], "generation_unavailable")
        self.assertEqual(set(b), {"error", "message"})       # NO internal fields
        self.assertNotIn("Traceback", r.text)                # no stacktrace leaked

    def test_500_internal_error_clean_body(self):
        def _boom(q, a):
            raise RuntimeError("db exploded with secret dsn=...")
        r = _client(_boom).post("/api/generate", json={"question": "щось"})
        self.assertEqual(r.status_code, 500)
        self.assertEqual(set(r.json()), {"error", "message"})
        self.assertNotIn("secret", r.text)                   # internal detail not leaked


class RealGeneratePath(_HermeticData):
    """The seam's own default generate path, with the database, retrieval and candidates faked and
    only the provider call failing. The 503/500 tests above inject a generate() that raises; these
    fail inside the real one, where an outage caught as an abstain would come back as a 200 that
    tells the user the law gives no answer."""

    HITS = [{"content_hash": "h1", "act": "X", "unit_path": "ст.1", "citation": "ст.1"}]
    CANDS = [{"id": "C1", "citation": "Акт X, ст.1", "act": "X", "unit_path": "ст.1",
              "content_hash": "h1", "text": "t1"}]

    def _post_with_provider_raising(self, exc):
        from contextlib import nullcontext
        with mock.patch("pipelines.db.connect", lambda: nullcontext(None)), \
             mock.patch("pipelines.rag.retrieval.search",
                        lambda *a, **k: (self.HITS, {"route": "channels"})), \
             mock.patch("pipelines.rag.generate.build_candidates",
                        lambda conn, hits: (self.CANDS, {})), \
             mock.patch("ml.llm_client.call_tool_deepseek", side_effect=exc):
            return _client(None).post("/api/generate", json={"question": "щось"})

    def test_provider_outage_inside_generate_is_503_not_an_abstain(self):
        import httpx
        import openai
        r = self._post_with_provider_raising(
            openai.APIConnectionError(request=httpx.Request("POST", "https://api.deepseek.com")))
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"], "generation_unavailable")

    def test_provider_failure_inside_generate_is_500_not_an_abstain(self):
        # a missing key or a truncated tool call raises RuntimeError inside the client
        r = self._post_with_provider_raising(RuntimeError("DEEPSEEK_API_KEY not set"))
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.json()["error"], "internal_error")


class Lifespan(_HermeticData):
    """Reranker pin at STARTUP — drift refuses to start, a load failure starts degraded."""

    def test_pin_drift_refuses_start(self):
        from fastapi.testclient import TestClient

        from api.main import create_app

        def _drift():
            raise SystemExit("reranker pin drift — refuse to serve the wrong model")
        app = create_app(generate_fn=lambda q, a: _result(), verify_pin=_drift)
        with self.assertRaises(RuntimeError):                # drift → startup fails, no bind
            with TestClient(app):                            # entering ctx runs lifespan/startup
                pass

    def test_reranker_unavailable_starts_degraded(self):
        from fastapi.testclient import TestClient

        from api.main import create_app
        from ml.reranker import RerankerUnavailable

        def _unavail():
            raise RerankerUnavailable("no GPU / model not loaded")
        app = create_app(generate_fn=lambda q, a: _result(degraded=["reranker"], reranked=False),
                         verify_pin=_unavail)
        with TestClient(app) as c:                           # startup catches → server DOES start
            r = c.post("/api/generate", json={"question": "щось"})
        self.assertEqual(r.status_code, 200)                 # degraded, not a startup failure


if __name__ == "__main__":
    unittest.main(verbosity=2)
