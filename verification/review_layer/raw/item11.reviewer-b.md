BLOCK
[
  {
    "file": "pipelines/rada/parse_structure.py",
    "line": 841,
    "severity": "major",
    "invariant": "5",
    "defect": "The unclosed-quote branch no longer returns 1: a run that the code itself reports as untrustworthy ('Their structural tail is suppressed — parse is NOT trustworthy for them', lines 838-840) now falls through to `_summary.emit(ok=grand_eds, failed=0, nbytes=0)` and `return 0` (lines 844-845), while the unchanged comment on lines 836-837 still says 'RED, not a warning ... the only honest signal is a failed run'.",
    "consequence": "Cron and the orchestrator see a green A-03b run (exit 0, COLLECT-SUMMARY failed=0, the broken editions counted as ok), so nobody is alerted that those editions' units are wrong: every article after the unclosed quote is missing and its text sits inside the preceding unit, and those units go on into chunks and are served for as_of dates inside that edition's window. The only trace left is free-form stdout text, not the exit code or the counters that cron and the journal act on.",
    "evidence": "[LIVE]",
    "proof": "Drove main() inside the tree with the database and files faked (connect, DATA_DIR and _editions patched; the pre-change module rebuilt in memory from the diff's removed lines, no file written) on one edition X-1@2001-01-01: 'Стаття 1. A', then '\"Стаття 5. …' opening an amendment quote that never closes, then real 'Стаття 6.' and 'Стаття 7.'. BEFORE: exit=1, 'COLLECT-SUMMARY ok=0 failed=1 bytes=0 marked=0'. AFTER: exit=0, 'COLLECT-SUMMARY ok=1 failed=0 bytes=0 marked=0'. In both runs the only article path written was 'ст.1' (ст.6 and ст.7 lost) and stdout printed 'parse is NOT trustworthy for them'. Nothing catches it: `python -m unittest discover -s tests -p test_parse_structure_t9.py` on the changed tree gives 'Ran 49 tests ... OK'; QuoteEofGate tests only _quote_eof_warn, no test calls parse_structure.main(), and tests/test_rada_exit_codes.py covers only reachability, fetch_cards and the retrieval baseline. pipelines/exitcodes.py defines exit 1 as 'any errors or an undercount (... missing data)'; AGENTS.md invariant 5: 'a run in which something failed never exits 0'."
  }
]
