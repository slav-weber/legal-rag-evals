"""Eval harness core: mechanical fields, taxonomy (+precision_drift), golden, score.
Pure logic — no LM/DB (generate is stubbed); the CLI gate tests run the harness in a
subprocess on stub backends only.

    uv run python -m unittest discover -s tests -p test_harness.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval import harness as H  # noqa: E402


def _result(cited_pairs, resolved_ids=None, abstain=False, prose_unbacked=None):
    """A generate()-shaped result: candidates C1..Cn from cited_pairs, resolved = resolved_ids."""
    cands = [{"id": f"C{i}", "act": a, "unit_path": p, "citation": f"{a} {p}"}
             for i, (a, p) in enumerate(cited_pairs, 1)]
    ids = resolved_ids if resolved_ids is not None else [c["id"] for c in cands]
    return {"candidates": cands, "resolved": {i: "s" for i in ids}, "abstained": abstain,
            "dovidka": {"vysnovok": "v", "obgruntuvannya": []},
            "lint": {"prose_refs_unbacked": prose_unbacked or [], "leaked_cids": []}}


class Mechanical(unittest.TestCase):
    def test_cited_stems_and_abstain(self):
        r = _result([("A", "ст.1"), ("A", "ст.2/п.3")], resolved_ids=["C1", "C2"])
        mf = H.mechanical_fields(r)
        self.assertEqual(mf["cited"], {("A", "ст.1"), ("A", "ст.2")})   # ст.2/п.3 → stem ст.2
        self.assertFalse(mf["abstain"])
        self.assertEqual(mf["outside_set"], [])

    def test_outside_set_probe(self):
        r = _result([("A", "ст.1")], resolved_ids=["C9"])               # C9 not a candidate
        self.assertEqual(H.mechanical_fields(r)["outside_set"], ["C9"])


class Taxonomy(unittest.TestCase):
    def test_correct(self):
        tax = H.classify(_result([("A", "ст.1")]), [("A", "ст.1")])
        self.assertEqual(tax["correct"], [("A", "ст.1")])
        self.assertEqual(tax["null"], [])

    def test_null_when_missed_not_abstained(self):
        tax = H.classify(_result([("A", "ст.1")]), [("A", "ст.1"), ("A", "ст.2")])
        self.assertEqual(tax["null"], [("A", "ст.2")])            # gold missed, not abstained

    def test_abstain_is_not_null(self):
        tax = H.classify(_result([], abstain=True), [("A", "ст.2")])   # abstained → honest
        self.assertEqual(tax["null"], [])
        self.assertTrue(tax["abstain"])

    def test_wrong_pick_candidate(self):
        tax = H.classify(_result([("A", "ст.3")]), [("A", "ст.1")])     # cited a norm not in gold
        self.assertEqual(tax["wrong_pick_candidates"], [("A", "ст.3")])

    def test_hallucination_is_gate_breach(self):
        tax = H.classify(_result([("A", "ст.1")], resolved_ids=["C9"]), [("A", "ст.1")])
        self.assertEqual(tax["hallucination"], 1)                       # id outside set → breach

    def test_precision_drift_signal(self):
        r = _result([("A", "ст.1")], prose_unbacked=["303"])      # gold cited BUT prose drifts
        self.assertTrue(H.classify(r, [("A", "ст.1")])["precision_drift_signal"])

    def test_abstain_with_citations_not_scored_as_answered(self):
        # an abstained dovidka delivers NO citations (the render shows only the note) — even if
        # `resolved` carried a valid id it is NOT correct/wrong_pick/drift. RED before the
        # abstain early-return (only `null` was abstain-gated → inflated recall).
        r = _result([("A", "ст.1")], prose_unbacked=["303"], abstain=True)   # abstained BUT cited
        tax = H.classify(r, [("A", "ст.1")])
        self.assertEqual(tax["correct"], [])
        self.assertEqual(tax["null"], [])
        self.assertEqual(tax["wrong_pick_candidates"], [])
        self.assertFalse(tax["precision_drift_signal"])
        self.assertTrue(tax["abstain"])


class Golden(unittest.TestCase):
    def test_mechanical_hard_pass_and_red(self):
        case = {"bug_ref": "x", "kind": "mechanical",
                "expect": {"cited": [["A", "ст.1"]], "abstain": False}}
        ok, _ = H.check_golden(case, _result([("A", "ст.1")]))
        self.assertTrue(ok)
        ok, mism = H.check_golden(case, _result([("A", "ст.9")]))       # cited wrong norm
        self.assertFalse(ok)
        self.assertTrue(mism)

    def test_precision_drift_signal_non_gating(self):
        case = {"bug_ref": "x", "kind": "precision_drift",
                "expect": {"must_not_contain": ["підлягає безумовно"]}}
        r = {"dovidka": {"vysnovok": "строк підлягає безумовно", "obgruntuvannya": []}}
        ok, mism = H.check_golden(case, r)
        self.assertFalse(ok)                                            # signal fired
        self.assertTrue(mism)

    def test_committed_golden_loads_and_requires_bug_ref(self):
        cases = H.load_golden()                                # the committed golden records
        self.assertGreaterEqual(len(cases), 2)
        self.assertTrue(all(c["bug_ref"] for c in cases))


class Score(unittest.TestCase):
    def test_by_class_isolation(self):
        # regression for the defaultdict(dict(agg)) pollution bug — per-class must NOT
        # accumulate the running overall. Two classes, each 1 correct → each 1/1, not cumulative.
        rows = [{"id": 1, "class": "a", "expected": [("A", "ст.1")]},
                {"id": 2, "class": "b", "expected": [("A", "ст.2")]}]
        res = H.score(rows, H._stub_run)                      # stub echoes gold → all correct
        self.assertEqual(res["overall"]["correct"], 2)
        self.assertEqual(res["by_class"]["a"]["correct"], 1)
        self.assertEqual(res["by_class"]["b"]["correct"], 1)
        self.assertEqual(res["by_class"]["a"]["gold"], 1)

    def test_duplicate_gold_denominator_deduped(self):
        # a duplicated gold line must NOT undercount recall (the numerator is a set, so the
        # denominator must be too). RED before len(set(expected)): correct 1 / gold 2 = 0.5.
        rows = [{"id": 1, "class": "a", "expected": [("A", "ст.1"), ("A", "ст.1")]}]
        res = H.score(rows, H._stub_run)                              # stub echoes → 1 correct
        self.assertEqual(res["overall"]["gold"], 1)                   # deduped, not 2
        self.assertEqual(res["overall"]["correct"], 1)


class GoldenTeeth(unittest.TestCase):
    """A golden that cannot fail is not a golden — the committed cases have TEETH, and the
    loader rejects toothless / bug_ref-less cases."""

    def test_drift_fires_and_clean_passes(self):
        c05 = next(c for c in H.load_golden() if "стягнення" in c["question"])
        drift = {"dovidka": {"vysnovok": "", "obgruntuvannya": [
            {"teza": "постанова підлягає виконанню протягом 3 місяців з дня винесення"}]}}
        clean = {"dovidka": {"vysnovok": "", "obgruntuvannya": [
            {"teza": "постанова НЕ підлягає виконанню, якщо не було звернено до виконання "
                     "протягом 3 місяців"}]}}
        self.assertFalse(H.check_golden(c05, drift)[0])              # teeth FIRE on the drift
        self.assertTrue(H.check_golden(c05, clean)[0])              # PASS on the correct phrasing

    def _tmp_golden(self, obj):
        import json
        import tempfile
        d = Path(tempfile.mkdtemp())
        (d / "g.jsonl").write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return d

    def test_toothless_rejected(self):
        with self.assertRaises(H.GoldenFormatError):
            H.load_golden(self._tmp_golden({"bug_ref": "x", "kind": "precision_drift",
                                            "expect": {}}))

    def test_missing_bug_ref_rejected(self):
        with self.assertRaises(H.GoldenFormatError):
            H.load_golden(self._tmp_golden({"kind": "mechanical",
                                            "expect": {"cited": [["A", "ст.1"]]}}))


class Sabotage(unittest.TestCase):
    """The gate MUST be able to redden (a sabotage probe committed as a test) — the RED paths
    EXECUTE."""

    def test_hallucination_reddens(self):
        r = {"candidates": [{"id": "C1", "act": "A", "unit_path": "ст.1"}],
             "resolved": {"C9": "x"}, "abstained": False, "lint": {}}
        tax = H.classify(r, [("A", "ст.1")])
        self.assertEqual(tax["hallucination"], 1)                  # gate RED condition

    def test_golden_mechanical_mismatch_reddens(self):
        case = {"bug_ref": "x", "kind": "mechanical", "question": "q",
                "expect": {"cited": [["A", "ст.1"]]}}
        bad = {"candidates": [], "resolved": {}, "abstained": False, "dovidka": {}}
        gr = H.run_golden([case], lambda row: bad)                  # expected citation not produced
        self.assertEqual(gr["mechanical_red"], ["x"])          # gate reddens on mechanical golden


class Noise(unittest.TestCase):
    def test_stub_noise_zero_and_persistable(self):
        # two-level: the stub is deterministic → set-flip-rate 0, gold-flips 0, and the detail
        # carries per-pass mech data so write_noise can PERSIST it (unpersisted = no check).
        n = H.measure_noise([{"id": 1, "expected": [("A", "ст.1")]}], H._stub_run, passes=2)
        self.assertEqual(n["set_flip_rate"], 0.0)
        self.assertEqual(n["gold_flips"], 0)
        self.assertIn("cited", n["detail"][0]["passes"][0])        # per-pass detail present

    def test_gold_flip_is_an_incident(self):
        # a run_fn whose gold-citation presence differs across passes → gold_flip (hard incident).
        seq = iter([_result([("A", "ст.1")]), _result([])])   # pass 1 cites gold, pass 2 does not
        n = H.measure_noise([{"id": 1, "expected": [("A", "ст.1")]}], lambda row: next(seq),
                            passes=2)
        self.assertEqual(n["gold_flips"], 1)


class Sufficiency(unittest.TestCase):
    """sufficient@k + diyi/act-scoped aggregation."""

    def test_gold_in_candidates_is_sufficient_even_uncited(self):
        r = _result([("A", "ст.1"), ("B", "ст.2")], resolved_ids=[])   # RETRIEVED but not cited
        s = H.sufficient_at_k(r, [("A", "ст.1")])
        self.assertTrue(s["sufficient"])              # sufficiency ≠ citing (retrieval ceiling)
        self.assertEqual(s["missing"], [])

    def test_gold_absent_from_candidates_is_insufficient(self):
        s = H.sufficient_at_k(_result([("A", "ст.1")]), [("B", "ст.9")])
        self.assertFalse(s["sufficient"])
        self.assertEqual(s["missing"], [("B", "ст.9")])

    def test_score_counts_insufficient_retrieval(self):
        # gold ∉ candidates → a `null` that is NOT the generator's fault; sufficient@k separates it.
        res = H.score([{"id": 1, "class": "c", "expected": [("Z", "ст.99")]}],
                      lambda row: _result([("A", "ст.1")]))
        self.assertEqual(res["overall"]["insufficient"], 1)
        self.assertEqual(res["overall"]["null"], 1)       # miss recorded too — but attributable

    def test_score_aggregates_diyi_and_act_flags(self):
        def run(row):
            r = _result([("A", "ст.1")])
            r["lint"]["diyi_refs_unbacked"] = ["294"]
            r["lint"]["prose_refs_ambiguous_act"] = ["5"]
            r["lint"]["prose_internal_vocab"] = ["cid", "кандидат"]   # rollup was unpinned before
            return r
        res = H.score([{"id": 1, "class": "c", "expected": [("A", "ст.1")]}], run)
        self.assertEqual(res["overall"]["diyi_unbacked"], 1)
        self.assertEqual(res["overall"]["ambiguous_act"], 1)
        self.assertEqual(res["overall"]["vocab_flags"], 2)            # classes, not occurrences
        self.assertEqual(res["detail"][0]["lint"]["prose_internal_vocab"], ["cid", "кандидат"])


class RunPersistence(unittest.TestCase):
    """Golden verdict persisted in the write_run header; dovidka prose persisted in the run
    detail; stub-flip guarded to noise mode."""

    def test_write_run_header_persists_golden_verdict(self):
        import json
        import tempfile
        with mock.patch.dict("os.environ", {"DATA_DIR": tempfile.mkdtemp()}):
            p = H.write_run({"overall": {}, "by_class": {}, "detail": []}, "R1",
                            {"mechanical_red": ["bug-001"], "drift_signals": ["8c25575"]})
        hdr = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(hdr["golden"],
                         {"mechanical_red": ["bug-001"], "drift_signals": ["8c25575"]})

    def test_write_run_header_omits_golden_when_absent(self):
        import json
        import tempfile
        with mock.patch.dict("os.environ", {"DATA_DIR": tempfile.mkdtemp()}):
            p = H.write_run({"overall": {}, "by_class": {}, "detail": []}, "R2")   # compat
        self.assertNotIn("golden", json.loads(p.read_text(encoding="utf-8").splitlines()[0]))

    def test_score_detail_persists_dovidka_prose(self):
        def run(row):
            r = _result([("A", "ст.1")])
            r["dovidka"] = {"vysnovok": "Висновок.", "diyi": ["Крок 1."],
                            "obgruntuvannya": [{"teza": "Теза.", "citations": ["C1"]}]}
            return r
        res = H.score([{"id": 1, "class": "c", "expected": [("A", "ст.1")]}], run)
        dov = res["detail"][0]["dovidka"]
        self.assertEqual((dov["vysnovok"], dov["diyi"], dov["tezy"]),
                         ("Висновок.", ["Крок 1."], ["Теза."]))

    def test_stub_flip_rejected_outside_noise_mode(self):
        import subprocess
        import sys as _sys
        root = str(Path(__file__).resolve().parents[1])
        r = subprocess.run(
            [_sys.executable, "-m", "eval.harness", "--mode", "score", "--backend", "stub-flip",
             "--etalons", "eval/data/retrieval_gold_v0.jsonl"],
            cwd=root, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)                # guard: stub-flip ⇒ --mode noise only


class Pins(unittest.TestCase):
    """Pins for the mutations an earlier version of this suite let survive."""

    def test_run_safe_collects_error_not_crash(self):
        def _boom(row):
            raise RuntimeError("finish=length")
        res = H.score([{"id": 1, "class": "a", "expected": [("A", "ст.1")]}], _boom)
        self.assertEqual(len(res["errors"]), 1)                    # collected, not crashed
        self.assertEqual(res["overall"]["n"], 0)

    def test_write_run_unique_per_run_id(self):
        import tempfile
        with mock.patch.dict("os.environ", {"DATA_DIR": tempfile.mkdtemp()}):
            p1 = H.write_run({"overall": {}, "by_class": {}, "detail": []}, "R1")
            p2 = H.write_run({"overall": {}, "by_class": {}, "detail": []}, "R2")
        self.assertNotEqual(p1.name, p2.name)                     # unique run files (no clobber)

    def test_golden_bad_kind_rejected(self):
        # give the case VALID teeth (must_not_contain) so ONLY the kind-check can reject it.
        # With {expect:{cited}} the teeth-check rejects it too (a non-mechanical kind with only
        # `cited` is toothless) → deleting the kind-check survives → the pin was a no-op.
        import json
        import tempfile
        d = Path(tempfile.mkdtemp())
        case = {"bug_ref": "x", "kind": "weird", "expect": {"must_not_contain": ["x"]}}
        (d / "g.jsonl").write_text(json.dumps(case), encoding="utf-8")
        with self.assertRaises(H.GoldenFormatError):
            H.load_golden(d)

    def test_key_points_fail_loud(self):
        import json
        import tempfile
        from eval import retrieval_eval as R
        d = Path(tempfile.mkdtemp())
        f = d / "g.jsonl"
        f.write_text(json.dumps({"id": 1, "question": "q", "gold_citations": [],
                                 "gold_key_points": "not-a-list"}), encoding="utf-8")
        with self.assertRaises(R.GoldFormatError):
            R._load_gold(f, {"3543-12"})


class CliGate(unittest.TestCase):
    """CLI subprocess test: --mode gate must exit 1 on a golden RED-leg breach, 0 when clean —
    so a mutation that drops golden from the red condition is caught end-to-end. Stub backends
    only; no live LLM."""

    def _run(self, backend):
        import subprocess
        import sys as _sys
        root = str(Path(__file__).resolve().parents[1])
        return subprocess.run(
            [_sys.executable, "-m", "eval.harness", "--mode", "gate", "--backend", backend,
             "--etalons", "eval/data/retrieval_gold_v0.jsonl"],
            cwd=root, capture_output=True, text=True).returncode

    def test_clean_stub_gate_green_abstain_red(self):
        self.assertEqual(self._run("stub"), 0)              # oracle satisfies mechanical golden
        self.assertEqual(self._run("stub-abstain"), 1)            # golden RED-leg → exit 1


class NoiseGate(unittest.TestCase):
    """Noise-exit pin: the --mode noise exit-1 wiring, pinned via subprocess like CliGate.
    stub-flip flips the garnish every 2nd pass → set-flip-rate 1.0 > NOISE_FLIP_THRESHOLD,
    exercising the SET-level (rate) branch end-to-end (GOLD-flips 0 isolates it from the gold
    branch, which is unit-covered by Noise::test_gold_flip_is_an_incident)."""

    def _run(self, backend):
        import os as _os
        import subprocess
        import sys as _sys
        import tempfile
        root = str(Path(__file__).resolve().parents[1])
        env = {**_os.environ, "DATA_DIR": tempfile.mkdtemp()}     # hermetic: noise file → temp dir
        return subprocess.run(
            [_sys.executable, "-m", "eval.harness", "--mode", "noise", "--backend", backend,
             "--etalons", "eval/data/retrieval_gold_v0.jsonl", "--passes", "2"],
            cwd=root, capture_output=True, text=True, env=env)

    def test_set_flip_reddens_noise_gate(self):
        r = self._run("stub-flip")
        self.assertEqual(r.returncode, 1)                # set-flip-rate > threshold → exit 1
        self.assertIn("GOLD-flips 0", r.stdout)          # gold stable → it is the RATE branch


if __name__ == "__main__":
    unittest.main(verbosity=2)
