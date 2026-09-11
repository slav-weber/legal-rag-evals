BLOCK
[
  {
    "file": "pipelines/rada/parse_structure.py",
    "line": 841,
    "severity": "major",
    "invariant": "5",
    "defect": "When an unclosed amendment quote is detected (quote_eof_bad is non-empty), main() no longer reports those editions as failed and returns 1; it falls through to _summary.emit(ok=grand_eds, failed=0) and return 0 at lines 844-845, so a run that prints 'parse is NOT trustworthy' for those editions exits 0 with zero failures.",
    "consequence": "An edition whose structural tail was silently swallowed is still written to units, and the chunk stage builds citable chunks from them. Meanwhile the exit code read by the orchestrator and cron, and the journal's items_failed, both show a clean run. The only trace is one stdout line, and the file's own comment at lines 836-837 says no counter can see this failure. The downgrade has no age condition: it covers the current in-force edition too, not only the 'one old edition' in the description.",
    "evidence": "[LIVE]",
    "proof": "Command: from the tree root, PYTHONDONTWRITEBYTECODE=1 python -c, with dotenv, connect and DATA_DIR replaced in memory (PRAVO8_ORCHESTRATED=1, no file written). Input: main() on act 0000-00, one edition shaped like the QuoteEofGate fixture: 'Стаття 1. Перша стаття', then the lead-in 'є) доповнити статтею 5 такого змісту:', then a heading that opens with a straight double quote before 'Стаття 5. Назва процитованої статті' and never closes, then 'Стаття 6. ...' and 'Стаття 7. ...'. _quote_eof_warn fires on it. Result with the tree as changed, edition 2001-01-01: rc=0, 'COLLECT-SUMMARY ok=1 failed=0 bytes=0 marked=0', the NOT-trustworthy message printed, units written ['преамбула', 'ст.1', 'ст.1/п.1'], so ст.6 and ст.7 are missing. Same run with the diff reversed in memory: rc=1, 'COLLECT-SUMMARY ok=0 failed=1 bytes=0 marked=0'. Tree as changed with --current and edition_date = today: rc=0, failed=0. pipelines/exitcodes.py defines 0 as 'everything that should have happened, happened' and 1 as FAIL for any errors. Tests: tests.test_parse_structure_t9 plus tests.test_article_num ran 72 tests, OK with the change. No file in tests/ calls parse_structure.main(), so the test gate does not see the regression."
  }
]
