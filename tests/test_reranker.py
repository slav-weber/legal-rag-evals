"""Reranker pins: honest degradation on a load failure, model DRIFT → red, pin validated once.

FlagReranker (the 1.1 GB model on the GPU) is MOCKED — unit tests touch no GPU and load no weights.
Live behaviour is proven separately by `uv run python -m ml.reranker --check-pin / --smoke`; the
live rerank gate is not part of this extract. The committed ml/reranker_reference.json supplies
the reference scores here. The one test that patches `FlagEmbedding.FlagReranker` itself skips
when the optional `rerank` extra is not installed; everything else runs without it.

    uv run python -m unittest discover -s tests -p test_reranker.py -q
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import reranker  # noqa: E402

_RERANK_EXTRA = unittest.skipUnless(importlib.util.find_spec("FlagEmbedding") is not None,
                                    "optional rerank extra not installed")


class Load(unittest.TestCase):
    def setUp(self):
        reranker._MODEL = None
        reranker._PIN_OK = False

    def tearDown(self):
        reranker._MODEL = None
        reranker._PIN_OK = False

    @_RERANK_EXTRA
    def test_load_failure_is_rerankerunavailable(self):
        # FlagReranker raising (OOM / model absent / no GPU) → RerankerUnavailable (honest
        # degradation): the caller degrades down the ladder, it is NOT a crash nor a silent RRF
        # pass-off.
        with mock.patch("FlagEmbedding.FlagReranker", side_effect=OSError("model absent")):
            with self.assertRaises(reranker.RerankerUnavailable):
                reranker._load()

    def test_rerank_empty_docs_short_circuits(self):
        # no candidates → [] WITHOUT loading the model (no GPU touched, no pin needed).
        with mock.patch.object(reranker, "_load", side_effect=AssertionError("must not load")):
            self.assertEqual(reranker.rerank("q", []), [])

    def test_model_name_from_env(self):
        with mock.patch.dict("os.environ", {"RERANK_MODEL": "Org/Model"}):
            self.assertEqual(reranker._model_name(), "Org/Model")


class Pin(unittest.TestCase):
    """Reference-score pin (mirror of the embedder's reference-vector). The committed reference is
    the source of truth; a live drift beyond tolerance is a model swap → SystemExit (refuse)."""

    def setUp(self):
        reranker._MODEL = None
        reranker._PIN_OK = False
        self.ref = json.loads(reranker.REFERENCE_PATH.read_text(encoding="utf-8"))
        self.ref_scores = [p["score"] for p in self.ref["pairs"]]

    def tearDown(self):
        reranker._MODEL = None
        reranker._PIN_OK = False

    def test_reference_file_is_committed_and_shaped(self):
        # the pin artefact exists with model, sha256, revision, and relevant>irrelevant scores.
        self.assertEqual(self.ref["model"], reranker.DEFAULT_MODEL)
        self.assertEqual(len(self.ref["sha256"]), 64)
        self.assertTrue(self.ref["revision"])
        rel = next(p for p in self.ref["pairs"] if p["tag"] == "relevant")["score"]
        irr = next(p for p in self.ref["pairs"] if p["tag"] == "irrelevant")["score"]
        self.assertGreater(rel, irr)                    # relevant outscores irrelevant

    def test_pin_ok_when_live_equals_reference(self):
        # Δ=0 (live == reference, the in-process determinism observed live) → pin OK, no drift.
        with mock.patch.object(reranker, "_score_pairs", lambda pairs: list(self.ref_scores)):
            note = reranker.check_pin()
        self.assertIn("pin OK", note)

    def test_tolerance_boundary_at_and_over(self):
        # |Δ| exactly == tol → still OK (not > tol); just over → SystemExit (drift). Pins the
        # threshold that separates fp16/driver noise from a model swap.
        tol = self.ref["tolerance"]
        at = [s + tol for s in self.ref_scores]              # |Δ| == tol → within
        with mock.patch.object(reranker, "_score_pairs", lambda pairs: at):
            self.assertIn("pin OK", reranker.check_pin())
        over = [s + tol + 0.01 for s in self.ref_scores]     # |Δ| > tol → drift
        with mock.patch.object(reranker, "_score_pairs", lambda pairs: over):
            with self.assertRaises(SystemExit):
                reranker.check_pin()

    def test_drift_beyond_tolerance_is_systemexit(self):
        # a DIFFERENT model on the same name drifts the scores hard → refuse to rerank (SystemExit).
        drifted = [s + 10.0 for s in self.ref_scores]
        with mock.patch.object(reranker, "_score_pairs", lambda pairs: drifted):
            with self.assertRaises(SystemExit):
                reranker.check_pin()

    def test_name_mismatch_is_systemexit(self):
        # RERANK_MODEL points at a different model than the reference records → red (pin drift).
        with mock.patch.dict("os.environ", {"RERANK_MODEL": "Other/Model"}), \
             mock.patch.object(reranker, "_score_pairs", lambda pairs: list(self.ref_scores)):
            with self.assertRaises(SystemExit):
                reranker.check_pin()

    def test_pin_validated_once_then_cached(self):
        # rerank() calls check_pin the FIRST time only (then _PIN_OK short-circuits it).
        calls = {"n": 0}

        def _score(pairs):
            calls["n"] += 1
            if len(pairs) == len(self.ref_scores):
                return list(self.ref_scores)
            return [0.0] * len(pairs)

        with mock.patch.object(reranker, "_score_pairs", _score):
            reranker.rerank("q", ["d1"])          # pin check (2-pair) + score (1-pair)
            reranker.rerank("q", ["d2"])          # pin already ok → score only
        # 3 calls: pin(1) + doc(1) + doc(1); NOT a second pin check.
        self.assertEqual(calls["n"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
