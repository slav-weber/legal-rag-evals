"""The STRUCTURAL citation gate: the LLM cites ONLY candidate IDs; the resolver rejects any
out-of-set ID → retry → honest abstain (a hallucinated citation is structurally impossible).
The LLM client and retrieval are MOCKED — no API / LM / DB.

    uv run python -m unittest discover -s tests -p test_generate.py -q
"""

from __future__ import annotations

import html as _html
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.rag import generate as G  # noqa: E402


class ActCitation(unittest.TestCase):
    def test_same_article_different_acts_render_distinctly(self):
        # «ст.5» of two acts MUST differ — act_title is composed in (chunks.citation lacks it,
        # which was the source of the 78 cross-act collisions).
        a = G.act_citation({"citation": "ст. 5 · ред. 2026", "act_title": "Кодекс А"})
        b = G.act_citation({"citation": "ст. 5 · ред. 2026", "act_title": "Закон Б"})
        self.assertNotEqual(a, b)
        self.assertIn("Кодекс А", a)
        self.assertIn("Закон Б", b)

    def test_no_double_prefix_when_title_already_present(self):
        c = G.act_citation({"citation": "Кодекс А, ст. 5", "act_title": "Кодекс А"})
        self.assertEqual(c, "Кодекс А, ст. 5")

    def test_falls_back_to_act_when_no_title(self):
        self.assertEqual(G.act_citation({"citation": "ст. 5", "act": "8073-10"}), "8073-10, ст. 5")


class Resolve(unittest.TestCase):
    CANDS = [{"id": "C1", "citation": "Акт X, ст.1"}, {"id": "C2", "citation": "Акт Y, ст.2"}]

    def test_in_set_resolves_out_of_set_is_invalid(self):
        dov = {"obgruntuvannya": [{"teza": "t", "citations": ["C1", "C9"]},
                                  {"teza": "u", "citations": ["C2"]}]}
        resolved, invalid = G.resolve_citations(dov, self.CANDS)
        self.assertEqual(set(resolved), {"C1", "C2"})
        self.assertEqual(invalid, ["C9"])                 # the GATE: out-of-set → invalid
        self.assertEqual(resolved["C1"], "Акт X, ст.1")

    def test_empty(self):
        self.assertEqual(G.resolve_citations({"obgruntuvannya": []}, self.CANDS), ({}, []))


class Gate(unittest.TestCase):
    """generate() gate: valid IDs pass; out-of-set IDs retry then abstain; a model abstain
    short-circuits."""

    HITS = [{"content_hash": "h1", "act": "X", "unit_path": "ст.1", "citation": "ст.1"}]
    CANDS = [{"id": "C1", "citation": "Акт X, ст.1", "act": "X", "unit_path": "ст.1",
              "content_hash": "h1", "text": "t1"}]

    def _tool(self, returns):
        from ml.llm_client import ToolResult
        state = {"n": 0}

        def _fn(messages, tool, **kw):
            r = returns[min(state["n"], len(returns) - 1)]
            state["n"] += 1
            return ToolResult(args=r, model="m", prompt_tokens=1, completion_tokens=1,
                              total_tokens=2, cache_hit_tokens=0, request_id=f"rid{state['n']}")
        return state, _fn

    def _run(self, returns, dropped=None, capture=None, **gen_kw):
        state, fn = self._tool(returns)

        def _search(conn, question, as_of=None, k=10):
            if capture is not None:
                capture["k"] = k
            return self.HITS, {"route": "channels"}

        with mock.patch("pipelines.rag.retrieval.search", _search), \
             mock.patch.object(G, "build_candidates",
                               lambda conn, hits: (self.CANDS, dropped or {})), \
             mock.patch("ml.llm_client.call_tool_deepseek", fn):
            res = G.generate(None, "q", **gen_kw)
        return res, state["n"]

    def test_default_k_is_10(self):
        cap = {}
        self._run([{"vysnovok": "v", "obgruntuvannya": [{"teza": "t", "citations": ["C1"]}],
                    "abstain": False}], capture=cap)
        self.assertEqual(cap["k"], 10)                     # k=10 follows the measured recall@10

    def test_dropped_surfaced_in_result(self):
        good = {"vysnovok": "v", "obgruntuvannya": [{"teza": "t", "citations": ["C1"]}],
                "abstain": False}
        res, _ = self._run([good], dropped={"budget": ["ст.9"], "n_before": 2, "n_kept": 1})
        self.assertEqual(res["dropped"]["budget"], ["ст.9"])   # dropped candidates are not silent

    def test_degraded_surfaced_in_result(self):
        # Search-meta degradation MUST reach the result (else the API meta looks healthy while
        # the reranker fell back). Additive propagation, gate/resolver untouched.
        good = {"vysnovok": "v", "obgruntuvannya": [{"teza": "t", "citations": ["C1"]}],
                "abstain": False}
        _, fn = self._tool([good])
        meta = {"route": "channels", "degraded": ["reranker"], "reranked": False}
        with mock.patch("pipelines.rag.retrieval.search", lambda *a, **k: (self.HITS, meta)), \
             mock.patch.object(G, "build_candidates", lambda conn, hits: (self.CANDS, {})), \
             mock.patch("ml.llm_client.call_tool_deepseek", fn):
            res = G.generate(None, "q")
        self.assertEqual(res["degraded"], ["reranker"])       # degradation surfaced, not dropped
        self.assertFalse(res["reranked"])

    def test_retry_appends_assistant_tool_call_turn(self):
        bad = {"vysnovok": "v", "obgruntuvannya": [{"teza": "t", "citations": ["C9"]}],
               "abstain": False}
        good = {"vysnovok": "v", "obgruntuvannya": [{"teza": "t", "citations": ["C1"]}],
                "abstain": False}
        seen = {}

        def _fn(messages, tool, **kw):
            from ml.llm_client import ToolResult
            seen["roles"] = [m["role"] for m in messages]
            r = bad if len(seen.get("all", [])) == 0 else good
            seen.setdefault("all", []).append(1)
            return ToolResult(args=r, model="m", prompt_tokens=1, completion_tokens=1,
                              total_tokens=2, cache_hit_tokens=0, request_id="rid",
                              tool_call_id="tc1", raw_arguments="{}")
        with mock.patch("pipelines.rag.retrieval.search",
                        lambda *a, **k: (self.HITS, {"route": "channels"})), \
             mock.patch.object(G, "build_candidates", lambda conn, hits: (self.CANDS, {})), \
             mock.patch("ml.llm_client.call_tool_deepseek", _fn):
            G.generate(None, "q")
        self.assertIn("assistant", seen["roles"])          # the retry carries the assistant turn
        self.assertIn("tool", seen["roles"])

    def test_valid_ids_pass_no_retry(self):
        res, ncalls = self._run([{"vysnovok": "v", "obgruntuvannya": [
            {"teza": "t", "citations": ["C1"]}], "abstain": False}])
        self.assertFalse(res["abstained"])
        self.assertEqual(res["resolved"], {"C1": "Акт X, ст.1"})
        self.assertEqual(ncalls, 1)                       # no regeneration

    def test_out_of_set_retries_then_abstains(self):
        bad = {"vysnovok": "v", "obgruntuvannya": [{"teza": "t", "citations": ["C9"]}],
               "abstain": False}
        res, ncalls = self._run([bad], max_retries=2)     # always cites C9 (out of set)
        self.assertTrue(res["abstained"])                 # forced honest abstain
        self.assertEqual(res["dovidka"]["abstain"], True)
        self.assertEqual(ncalls, 3)                        # initial + 2 retries, then abstain
        # PRODUCER pin: the user no longer sees the model's prose, so the abstain reason lives
        # ONLY in the result/trace → generate() must emit it. Without this pin, deleting
        # abstain_reason from the result left the suite green.
        self.assertEqual(res["abstain_reason"], "no valid citations after retries")

    def test_recovers_on_retry(self):
        bad = {"vysnovok": "v", "obgruntuvannya": [{"teza": "t", "citations": ["C9"]}],
               "abstain": False}
        good = {"vysnovok": "v", "obgruntuvannya": [{"teza": "t", "citations": ["C1"]}],
                "abstain": False}
        res, ncalls = self._run([bad, good])              # 1st out-of-set, 2nd valid
        self.assertFalse(res["abstained"])
        self.assertEqual(res["resolved"], {"C1": "Акт X, ст.1"})
        self.assertEqual(ncalls, 2)

    def test_model_abstain_short_circuits(self):
        res, ncalls = self._run([{"vysnovok": "Надані кандидати не дають підстав.",
                                  "obgruntuvannya": [], "abstain": True}])
        self.assertTrue(res["abstained"])
        self.assertEqual(ncalls, 1)                        # model abstain → no retry
        self.assertEqual(res["abstain_reason"], "model abstained")     # producer pin
        # and the model's own prose must still be IN the result, so write_trace can preserve it —
        # the user no longer sees it, so losing it here would make the abstain unexplainable.
        self.assertIn("кандидати", res["dovidka"]["vysnovok"])

    def test_zero_citation_slip_rejected(self):
        # abstain=false + NO citations must NOT pass the gate — a dovidka without any citation
        # is not a dovidka → retry → abstain. RED before the not-resolved guard.
        empty = {"vysnovok": "v", "obgruntuvannya": [{"teza": "t", "citations": []}],
                 "abstain": False}
        res, ncalls = self._run([empty], max_retries=2)
        self.assertTrue(res["abstained"])
        self.assertEqual(ncalls, 3)                        # initial + 2 retries, then abstain

    def test_adversarial_injection_rejected(self):
        # adversarial red path: a plausible out-of-set citation (C99) injected by the model is
        # REJECTED by the resolver — never resolved, never served. EXECUTED, not asserted.
        inj = {"vysnovok": "v", "obgruntuvannya": [{"teza": "t", "citations": ["C1", "C99"]}],
               "abstain": False}
        good = {"vysnovok": "v", "obgruntuvannya": [{"teza": "t", "citations": ["C1"]}],
                "abstain": False}
        res, ncalls = self._run([inj, good])          # 1st injects C99 → reject → retry → clean
        self.assertNotIn("C99", res["resolved"])           # injected id NEVER resolved
        self.assertEqual(set(res["resolved"]), {"C1"})
        self.assertFalse(res["abstained"])


class Dedup(unittest.TestCase):
    """kind-aware dedup: a container subsumes its leaves; a leaf outranking its container wins;
    leaves-only are all kept in natural order; articles by retrieval rank."""

    def _h(self, act, path):
        return {"act": act, "unit_path": path, "content_hash": f"{act}:{path}", "citation": "c"}

    def test_container_subsumes_leaves(self):
        hits = [self._h("A", "ст.19"), self._h("A", "ст.19/п.1"), self._h("A", "ст.19/п.2")]
        self.assertEqual([h["unit_path"] for h in G.dedup_candidates(hits)], ["ст.19"])

    def test_leaf_outranking_container_wins(self):
        hits = [self._h("A", "ст.19/п.2"), self._h("A", "ст.19")]   # leaf ranked above container
        self.assertEqual([h["unit_path"] for h in G.dedup_candidates(hits)], ["ст.19/п.2"])

    def test_leaves_only_kept_all_natural_order(self):
        hits = [self._h("A", "ст.5/п.10"), self._h("A", "ст.5/п.2")]   # lexicographic would flip
        self.assertEqual([h["unit_path"] for h in G.dedup_candidates(hits)],
                         ["ст.5/п.2", "ст.5/п.10"])

    def test_articles_ordered_by_rank(self):
        hits = [self._h("A", "ст.9"), self._h("A", "ст.1")]           # ст.9 retrieved first
        self.assertEqual([h["unit_path"] for h in G.dedup_candidates(hits)], ["ст.9", "ст.1"])


class Budget(unittest.TestCase):
    def _c(self, cid, nt):
        return {"id": cid, "n_tokens": nt, "text": "t"}

    def test_tail_drop_whole_candidates(self):
        cands = [self._c("C1", 4000), self._c("C2", 4000), self._c("C3", 4000)]
        kept = [c["id"] for c in G._apply_budget(cands, 10000)]
        self.assertEqual(kept, ["C1", "C2"])              # C3 dropped whole, never truncated

    def test_keeps_at_least_one_never_truncates(self):
        self.assertEqual([c["id"] for c in G._apply_budget([self._c("C1", 99999)], 10000)], ["C1"])


class Render(unittest.TestCase):
    def test_two_layers_with_resolved_chips(self):
        res = {"dovidka": {"vysnovok": "Строк 10 днів.", "diyi": ["Крок 1"],
               "obgruntuvannya": [{"teza": "Теза", "citations": ["C1"]}], "abstain": False},
               "resolved": {"C1": "Кодекс А, ст.288"}, "abstained": False}
        h = G.render_dovidka(res, "Питання?")
        for frag in ("Висновок", "Строк 10 днів", "Що робити", "Крок 1",
                     "Правове обґрунтування", "Кодекс А, ст.288"):
            self.assertIn(frag, h)
        self.assertNotIn(">C1<", h)                   # chip shows the resolved string, not the id

    def test_abstain_renders_fixed_copy_and_zero_model_prose(self):
        # Finding from a live run: the model's abstain prose reached the screen and leaked
        # retrieval plumbing — «Надані кандидати (–) не містять норм…»: «кандидати» means nothing
        # to a citizen, and the C-ID filter had cut C1/C9 leaving a mutilated bracket. The abstain
        # render is now DETERMINISTIC: fixed copy, and NOT ONE WORD of the model.
        # MUTATION pin: put the model's prose back into the render → this goes red.
        # The fixture MUST carry obgruntuvannya + resolved. A real abstain ALWAYS carries them
        # (generate() resolves citations BEFORE checking abstain); with empty fields the pin did
        # not cover the teza layer — a mutant that silenced vysnovok/diyi but forgot
        # obgruntuvannya passed all 517 tests.
        res = {"dovidka": {"vysnovok": "Надані кандидати (C1, C9) не містять норм щодо промпту.",
                           "diyi": ["Модельний крок про candidate"],
                           "obgruntuvannya": [{"teza": "Теза про кандидатів C1",
                                               "citations": ["C1"]}],
                           "abstain": True},
               "resolved": {"C1": "КУпАП, ст.288"}, "abstained": True}
        h = G.render_dovidka(res, "Питання?")
        self.assertIn('class="abstain"', h)
        # copy is rendered ESCAPED — compare the escaped form, else an apostrophe in the fixed
        # copy («військовозобов'язаних») would false-red a correct render.
        self.assertIn(_html.escape(G.ABSTAIN_VYSNOVOK), h)         # fixed copy, verbatim
        for step in G.ABSTAIN_DIYI:
            self.assertIn(_html.escape(step), h)
        for model_word in ("кандидат", "Модельний крок", "промпт", "candidate", "C1", "C9",
                           "Теза"):
            self.assertNotIn(model_word, h)                        # zero model words on screen
        # the obgruntuvannya layer is not rendered on abstain AT ALL: no tezy, no chips, no
        # resolved strings
        for structural in ("teza", "cite-chip", "КУпАП"):
            self.assertNotIn(structural, h)

    def test_abstain_copy_is_verbatim_fixed_text(self):
        # the copy is fixed and must not drift — pin the exact strings.
        self.assertEqual(
            G.ABSTAIN_VYSNOVOK,
            "На це запитання ми не можемо дати обґрунтовану відповідь: у чинних нормах, "
            "доступних системі, ми не знайшли підстав, на які можна прямо послатися.")
        self.assertEqual(G.ABSTAIN_DIYI, (
            "Спробуйте сформулювати запитання конкретніше — назвіть орган, рішення та дату.",
            "Можливо, ваше питання регулюють норми, яких поки немає в нашій базі, — "
            "це не означає, що відповіді не існує.",
            "У такій ситуації варто звернутися до адвоката: довідка не замінює правову допомогу."))

    def test_abstain_reason_survives_in_trace(self):
        # the user no longer sees the model's reason → it MUST land in the trace, else an
        # abstain becomes unexplainable.
        import json as _json
        import tempfile
        res = {"dovidka": {"vysnovok": "Надані кандидати не містять норм.", "abstain": True},
               "resolved": {}, "candidates": [], "abstained": True, "attempts": [],
               "abstain_reason": "no valid citations after retries", "lint": {}, "dropped": {},
               "route": "channels"}
        with mock.patch.dict("os.environ", {"DATA_DIR": tempfile.mkdtemp()}):
            path = G.write_trace(res, "питання?", subdir="t15test")
        rec = _json.loads(path.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(rec["abstain_reason"], "no valid citations after retries")
        self.assertIn("кандидати", rec["model_vysnovok"])     # model prose preserved for triage

    def test_escapes_untrusted_text_everywhere(self):
        # mutation survivor: teza + diyi + vysnovok all escaped, not just vysnovok.
        res = {"dovidka": {"vysnovok": "<b>v</b>", "diyi": ["<i>d</i>"],
               "obgruntuvannya": [{"teza": "<script>t</script>", "citations": ["C1"]}],
               "abstain": False}, "resolved": {"C1": "Акт, ст.1"}, "abstained": False}
        h = G.render_dovidka(res)
        for raw in ("<b>", "<i>", "<script>"):
            self.assertNotIn(raw, h)
        self.assertIn("&lt;script&gt;", h)

    def test_strips_leaked_internal_cids(self):
        # internal IDs «C1..Ck» leaking into prose must NOT reach the user HTML.
        res = {"dovidka": {"vysnovok": "Згідно C1 та C3 строк 10 днів.", "diyi": ["Подайте за C1."],
               "obgruntuvannya": [], "abstain": False}, "resolved": {}, "abstained": False}
        h = G.render_dovidka(res)
        self.assertNotIn("C1", h)
        self.assertNotIn("C3", h)
        self.assertIn("строк 10 днів", h)


class Build(unittest.TestCase):
    """build_candidates: empty-text (hash-miss) rows are dropped and the C-ids stay contiguous."""

    class _Cur:
        def __init__(self, rows):
            self.rows = rows

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, sql, params):
            pass

        def fetchall(self):
            return self.rows

    class _Conn:
        def __init__(self, rows):
            self.rows = rows

        def cursor(self):
            return Build._Cur(self.rows)

    def test_empty_text_dropped_cids_contiguous(self):
        hits = [{"act": "A", "unit_path": "ст.1", "content_hash": "h1", "citation": "ст.1"},
                {"act": "A", "unit_path": "ст.2", "content_hash": "h2", "citation": "ст.2"},
                {"act": "A", "unit_path": "ст.3", "content_hash": "h3", "citation": "ст.3"}]
        rows = [("h1", "text1", "Акт A", 10), ("h3", "text3", "Акт A", 10)]   # h2 missing → empty
        cands, dropped = G.build_candidates(Build._Conn(rows), hits)
        self.assertEqual([c["id"] for c in cands], ["C1", "C2"])              # contiguous, no gap
        self.assertEqual([c["unit_path"] for c in cands], ["ст.1", "ст.3"])
        self.assertIn("ст.2", dropped["empty_text"])


class Lint(unittest.TestCase):
    """prose lint (FLAG, not reject): unbacked «ст.N» in prose + leaked C-IDs."""

    def test_flags_unbacked_prose_article_ref(self):
        dov = {"vysnovok": "Це регулює стаття 47 та стаття 288.", "diyi": [],
               "obgruntuvannya": [{"teza": "t", "citations": ["C1"]}]}
        lint = G.prose_lint(dov, {"C1": "Акт, ст. 288 · ред."})   # only 288 is backed
        self.assertIn("47", lint["prose_refs_unbacked"])
        self.assertNotIn("288", lint["prose_refs_unbacked"])

    def test_flags_leaked_cids(self):
        lint = G.prose_lint({"vysnovok": "див. C1 і C5", "diyi": [], "obgruntuvannya": []}, {})
        self.assertEqual(lint["leaked_cids"], ["C1", "C5"])

    def test_diyi_lint_isolates_unbacked_ref_in_action_layer(self):
        # diyi lint: an unbacked «ст.N» named in the diyi (action) layer is flagged SEPARATELY —
        # users act on diyi, so it is a higher-risk subset than the same ref in obgruntuvannya.
        dov = {"vysnovok": "Коротко.", "diyi": ["Подайте скаргу згідно ст.294 у строк."],
               "obgruntuvannya": [{"teza": "t", "citations": ["C1"]}]}
        lint = G.prose_lint(dov, {"C1": "Акт, ст. 288"},
                            [{"id": "C1", "act": "2747-15", "unit_path": "ст.288"}])
        self.assertEqual(lint["diyi_refs_unbacked"], ["294"])       # unbacked ref, and in diyi
        self.assertIn("294", lint["prose_refs_unbacked"])           # also in the general flag

    def test_act_scoped_flags_cross_act_number_collision(self):
        # act-scoped: «ст.5» is 'backed' by a bare-number check, but it is resolved for TWO
        # different acts — the prose reference is act-ambiguous (the 78 cross-act «ст.5»
        # collision class).
        dov = {"vysnovok": "Застосовується стаття 5.", "diyi": [],
               "obgruntuvannya": [{"teza": "t", "citations": ["C1", "C2"]}]}
        cands = [{"id": "C1", "act": "2747-15", "unit_path": "ст.5"},
                 {"id": "C2", "act": "3543-12", "unit_path": "ст.5"}]
        lint = G.prose_lint(dov, {"C1": "КАС, ст.5", "C2": "ЦПК, ст.5"}, cands)
        self.assertEqual(lint["prose_refs_ambiguous_act"], ["5"])   # backed by 2 acts → ambiguous
        self.assertNotIn("5", lint["prose_refs_unbacked"])          # it IS backed — not unbacked

    def _vocab(self, **dov):
        base = {"vysnovok": "", "diyi": [], "obgruntuvannya": []}
        base.update(dov)
        return G.prose_lint(base, {})["prose_internal_vocab"]

    def test_internal_vocab_flags_each_class(self):
        # pin EVERY class of internal vocabulary, in any layer of user-facing prose.
        self.assertEqual(self._vocab(vysnovok="Згідно C1 строк."), ["cid"])
        self.assertEqual(self._vocab(vysnovok="Надані кандидати не містять норм."), ["кандидат"])
        self.assertEqual(self._vocab(diyi=["Уточніть кандидатів у наборі."]), ["кандидат"])
        self.assertEqual(self._vocab(vysnovok="Проблема з промптом."), ["промпт"])
        self.assertEqual(self._vocab(vysnovok="Наш retrieval не знайшов."), ["retrieval"])
        self.assertEqual(self._vocab(vysnovok="No candidate matched."), ["candidate"])
        self.assertEqual(self._vocab(obgruntuvannya=[{"teza": "Теза про кандидата C2",
                                                      "citations": []}]),
                         ["cid", "кандидат"])                    # the teza layer is linted too
        # IGNORECASE is load-bearing: the sentence-initial form is the most likely leak
        # («Надані кандидати…» capitalised — exactly what showed up on screen in the live run).
        self.assertEqual(self._vocab(vysnovok="Кандидати не містять норм."), ["кандидат"])
        self.assertEqual(self._vocab(vysnovok="Промпт не спрацював."), ["промпт"])

    def test_internal_vocab_clean_prose_is_empty(self):
        self.assertEqual(self._vocab(vysnovok="Строк оскарження — 10 днів.",
                                     diyi=["Подайте скаргу до суду."],
                                     obgruntuvannya=[{"teza": "Норма встановлює строк.",
                                                      "citations": []}]),
                         [])                                # no false positives on normal prose

    def test_cid_filter_leaves_mutilated_text_known_limit(self):
        # The C-ID filter stays as is (defense in depth), but its residual defect is pinned:
        # cutting an id INSIDE brackets leaves syntactically mutilated text. On the abstain path
        # this no longer matters (the model's prose is not rendered at all); on the normal path
        # the text is rendered, and prose_internal_vocab is what makes the leak visible
        # (leaked_cids/«cid» flag it).
        self.assertEqual(G._clean("Згідно (C1) строк 10 днів."), "Згідно () строк 10 днів.")
        self.assertEqual(G._clean("Див. C1 та C3."), "Див. та .")
        self.assertEqual(self._vocab(vysnovok="Згідно (C1) строк 10 днів."), ["cid"])   # not silent

    def test_act_scoped_single_act_not_ambiguous(self):
        dov = {"vysnovok": "Стаття 5.", "diyi": [],
               "obgruntuvannya": [{"teza": "t", "citations": ["C1"]}]}
        lint = G.prose_lint(dov, {"C1": "КАС, ст.5"},
                            [{"id": "C1", "act": "2747-15", "unit_path": "ст.5"}])
        self.assertEqual(lint["prose_refs_ambiguous_act"], [])      # one act backs it → clean


class Trace(unittest.TestCase):
    def test_trace_line_has_request_id_and_sha1(self):
        import json
        import tempfile
        d = tempfile.mkdtemp()
        res = {"route": "channels", "abstained": False, "candidates": [{"id": "C1"}],
               "resolved": {"C1": "Акт, ст.1"}, "lint": {}, "dropped": {},
               "attempts": [{"request_id": "abc-123", "invalid_ids": []}]}
        with mock.patch.dict("os.environ", {"DATA_DIR": d}):
            path = G.write_trace(res, "питання?", ts="2026-07-18T00:00:00Z")
        line = json.loads(Path(path).read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(line["attempts"][0]["request_id"], "abc-123")
        self.assertEqual(len(line["sha1_sys"]), 40)
        self.assertEqual(line["question"], "питання?")


if __name__ == "__main__":
    unittest.main(verbosity=2)
