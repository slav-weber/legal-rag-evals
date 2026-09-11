BLOCK
[
  {
    "file": "pipelines/rag/generate.py",
    "line": 305,
    "severity": "major",
    "invariant": "4",
    "defect": "`except Exception: break` turns a failed DeepSeek call into an ordinary abstain result, so provider errors no longer reach the API seam's documented `except openai.OpenAIError` -> 503 generation_unavailable branch (api/main.py:118-121, docs/ARCHITECTURE.md:93): the caller is left behind and the generation layer pretends to have run (docs/ARCHITECTURE.md:130).",
    "consequence": "During a DeepSeek outage every user gets HTTP 200 with the fixed abstain copy saying the norms available to the system contain no grounds and advising them to rephrase, a false answer instead of 'service temporarily unavailable'; meta.abstained=true with meta.degraded=[] passes the outage off as a whole result, so clients and monitoring keyed on 503 see nothing. The suite stays green because tests/test_api.py:150 injects a stub generate_fn that raises by itself and no test in tests/test_generate.py makes call_tool_deepseek raise.",
    "evidence": "[LIVE]",
    "proof": "TestClient(create_app(verify_pin=stub)) on the real _default_generate path: pipelines.db faked to a nullcontext, pipelines.rag.retrieval.search and build_candidates mocked to one candidate C1, ml.llm_client.call_tool_deepseek raising openai.APIConnectionError, write_trace mocked; the pre-change generate() rebuilt in memory by reverting the hunk from the source text. POST /api/generate {'question': 'q?'}: before -> HTTP 503 {'error': 'generation_unavailable', 'message': 'Сервіс генерації тимчасово недоступний.'}; after -> HTTP 200, meta.abstained=True, meta.degraded=[], trace_ref=None, html contains ABSTAIN_VYSNOVOK."
  },
  {
    "file": "pipelines/rag/generate.py",
    "line": 305,
    "severity": "major",
    "invariant": "5",
    "defect": "Because generate() no longer raises when the LLM call fails, the eval harness's error channel (_run_safe, eval/harness.py:134-141, and the unguarded run_golden) never sees provider failures: they are scored as model abstains, and a live run in which every generation failed exits 0.",
    "consequence": "`python -m eval.harness --backend live` in its default score mode during an outage (or with no API key) reports 'abstain 29', prints no errors line and exits 0, so a fully failed run reports success. In gate mode the RED is blamed on golden case 21.4-03 instead of the provider. In noise mode one connection error on one pass is persisted as a hard GOLD-flip incident with 0 pass-errors, which pollutes the measured noise floor that NOISE_FLIP_THRESHOLD is set from.",
    "evidence": "[LIVE]",
    "proof": "Same in-memory before/after; pipelines.db faked, write_run mocked (no file written), --etalons eval/data/retrieval_gold_v0.jsonl, call_tool_deepseek always raising APIConnectionError. --mode score: before -> main() raises APIConnectionError (CLI exit 1); after -> main() returns 0, output 'correct 0/29 · null 0 · wrong_pick-cand 0 · abstain 29 · drift-signal 0 · hallucination 0', no 'errors:' line. --mode gate: after -> returns 1 with 'GATE [RED]: hallucination=0 golden-mechanical-RED=['21.4-03']'. measure_noise(passes=2) on one row whose first call raises APIConnectionError and whose second returns a valid C1 answer: before -> pass-errors=1 set_flips=0 GOLD-flips=0, REPLAY GREEN; after -> pass-errors=0 set_flips=1 GOLD-flips=1, REPLAY RED."
  },
  {
    "file": "pipelines/rag/generate.py",
    "line": 306,
    "severity": "major",
    "invariant": "2",
    "defect": "The bare `except Exception` is not limited to transient provider errors: it also swallows the USER_DATA tripwire refusal (ValueError from _guard_deepseek), the missing-key RuntimeError and the 'tool-args JSON truncated, raise max_tokens' RuntimeError. It discards the exception without logging or recording it, and `break` routes every one of them to the post-loop abstain labelled 'no valid citations after retries' with zero attempts (lines 332-334).",
    "consequence": "No data leaves, because the guard still refuses before sending. But a red-line event (user data routed toward the external model) and a deployment without DEEPSEEK_API_KEY (HTTP 500 before, 200 after) both become routine abstains, and their only record, abstain_reason in the trace (the UI shows fixed copy), is false. The finish=length truncation that lines 301-302 say was found by the replay-noise run would now be hidden the same way. An operator can no longer tell a misconfiguration, a tripwire firing or a max_tokens cap from a genuine model abstain.",
    "evidence": "[LIVE]",
    "proof": "generate(None, q) with search and build_candidates mocked, before (hunk reverted in memory) vs after. (1) real call_tool_deepseek, _DEEPSEEK_API_KEY='test-key', q=mark_user_data('client facts'): before raises ValueError 'DeepSeek: payload carries a USER_DATA marker...'; after returns abstained=True, abstain_reason='no valid citations after retries', attempts=[]. (2) real call_tool_deepseek, key '': before raises RuntimeError 'DEEPSEEK_API_KEY not set (DeepSeek is opt-in).'; after returns the same abstain. Through POST /api/generate the same case is HTTP 500 internal_error before and HTTP 200 abstain after, with the trace record abstain_reason='no valid citations after retries', attempts=[]. (3) call_tool_deepseek raising RuntimeError('DeepSeek tool-args JSON truncated (finish_reason=length) - raise max_tokens'): before raises, after returns the same abstain."
  }
]
