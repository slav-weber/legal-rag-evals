BLOCK
[
  {
    "file": "pipelines/freshness/probe.py",
    "line": 208,
    "severity": "major",
    "invariant": null,
    "defect": "Dropping `AND signal_value IS NOT NULL` makes `_last_signal` return the newest source_checks row even when it is a failed-probe row with signal_value NULL, so after any probe failure the next real signal is compared against None and a real source change is stored as changed=False; the comment left in place at lines 203-205 names exactly this masking as the reason the filter existed.",
    "consequence": "One transient probe failure (HTTP 403 or 302, timeout, junk body, or a row NULLed by `cleanup_poisoned --apply`) followed by a real move of the source makes the next daily run report that source as `🟢 ok` with changed=false and adopt the new signal as the baseline, so the move is never flagged: reports/freshness.md and source_checks say the source is unchanged while dependent artifacts silently go stale; for `rada` the change-triggered backstop does not fire either (rada_changed=False, leaving only its 7-day timer), and the ckan, hf and supreme-court sources have no second check at all.",
    "evidence": "[LIVE]",
    "proof": "Ran the real probe.main() from the tree four times for the `rada` source against an in-memory SQL table that executes the same query text (psycopg %s mapped to ?), with probe() scripted to return `aaaa1111`, then None with note `HTTP 403`, then `bbbb2222` twice, and run_migrations, connect, _upsert_sources, seed_alias_map, _write_report and rada_backstop stubbed (no DB, network or file writes). Changed tree: day3 probe=bbbb2222 changed=False status=🟢 ok backstop(rada_changed=False); stored rows (1, aaaa1111, False), (2, None, False), (3, bbbb2222, False), (4, bbbb2222, False), so the move from aaaa1111 to bbbb2222 is never flagged. Same run with the pre-change query (AND signal_value IS NOT NULL restored from the diff): day3 changed=True status=🟡 changed backstop(rada_changed=True). Why nothing catches it: line 248 `changed = bool(prev is not None and sig is not None and sig != prev)` is what turns prev=None into changed=False; every probe() failure path returns None (lines 122, 128, 149, 152, 162, 175) and lines 250-251 insert it as a row; the sibling readers rada_backstop._last_signal (lines 85-86) and rada/reachability.persist (lines 77-78) keep the IS NOT NULL filter; no test calls probe._last_signal or probe.main(), and tests.test_freshness_probe_errors plus tests.test_freshness_rada_matcher (20 tests) pass on the changed tree."
  }
]
