"""Chunker unit tests.

Pure logic only: no DB, no network, no tokenizer download. The live numbers (4 706 chunks,
5 hard-fail leaves, 99.87 % denominator coverage) come from `pipelines.rada.chunk
--build/--verify`; CHUNKS_FLOOR pins the accepted count.

    uv run python -m unittest discover -s tests -q
"""

from __future__ import annotations

import datetime as dt
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.rada.chunk import (  # noqa: E402
    BGE_M3_REVISION, BGE_M3_TOKENIZER_SHA256, CHUNKS_FLOOR, PERIMETER, WINDOW, eligible,
    load_tokenizer, render_citation)

ED = dt.date(2026, 4, 12)


class Perimeter(unittest.TestCase):
    """Eleven nreg. SEED_ACTS is NOT this list — it carries the archive volumes and lacks
    4695-20 — so the perimeter is pinned here, not read from the collector."""

    def test_exactly_the_eleven(self):
        self.assertEqual(len(PERIMETER), 11)
        self.assertEqual(set(PERIMETER), {
            "3543-12", "2232-12", "8073-10", "2747-15", "3674-17", "3633-IX",
            "1404-19", "4695-20", "560-2024-п", "z1109-08", "76-2023-п"})

    def test_archive_volumes_and_provenance_are_out(self):
        for excluded in ("80731-10", "80732-10", "76-2024-п"):
            self.assertNotIn(excluded, PERIMETER, excluded)


class EligibilityIsNullSafe(unittest.TestCase):
    """Acceptance finding: the literal `NOT (text = title)` evaluates to NULL for every point
    unit (title IS NULL) → SQL drops all 3 288 of them and the denominator reads 1 325 instead
    of 4 613. Eligibility must be NULL-safe (`IS DISTINCT FROM`) — pinned here."""

    def test_point_with_null_title_is_eligible(self):
        # RED under the literal formula: NULL → falsy → the whole point kind vanishes.
        self.assertTrue(eligible("point", 120, "1. Текст частини.", None))

    def test_empty_vykliucheno_husk_is_not_eligible(self):
        """«Стаття 163. {Статтю 163 виключено …}» — body is entirely a marker → char_len 0."""
        self.assertFalse(eligible("article", 0, "", None))

    def test_bare_heading_is_not_eligible(self):
        """A section (розділ) made of articles: its span ends at the first one → text == title."""
        self.assertFalse(eligible("section", 18, "ЗАГАЛЬНІ ПОЛОЖЕННЯ", "ЗАГАЛЬНІ ПОЛОЖЕННЯ"))

    def test_body_bearing_section_is_eligible(self):
        self.assertTrue(eligible("section", 70685, "ПРИКІНЦЕВІ…\n1. Цей Закон…", "ПРИКІНЦЕВІ…"))


class CitationRender(unittest.TestCase):
    """Derived ONLY from the canonical unit_path, never from the text.

    The load-bearing case: «п.» means DIFFERENT things by parent — under an article (стаття)
    the «N.» level is a part (частина), under a section/annex (розділ/додаток) it is a point
    (пункт). Evidence from the corpus: 3543-12 ст.23/п.1 reads «1. Не підлягають призову … 1)
    заброньовані …», and 560-2024-п's Додаток 5 cites that same unit as «1. Частина перша
    статті 23 Закону»; the agreed rendering is «ст. 23 ч. 1 · ред. від DD.MM.YYYY»."""

    def test_article_child_renders_as_chastyna(self):
        self.assertEqual(render_citation("ст.23/п.1", ED, "point"),
                         "ст. 23 ч. 1 · ред. від 12.04.2026")

    def test_section_child_renders_as_punkt(self):
        self.assertEqual(render_citation("розд.XIII/п.1-4", ED, "point"),
                         "розд. XIII п. 1-4 · ред. від 12.04.2026")

    def test_annex_child_renders_as_punkt(self):
        self.assertEqual(render_citation("дод.5/п.1", ED, "point"),
                         "додаток 5 п. 1 · ред. від 12.04.2026")

    def test_plain_article(self):
        self.assertEqual(render_citation("ст.23", ED, "article"),
                         "ст. 23 · ред. від 12.04.2026")

    def test_hyphenated_form_comes_from_the_path_not_the_text(self):
        """The moratorium sits on п.1-4; the citation must show the canonical dashed form even
        though the source TEXT still renders it collapsed as «14.» (the legal text itself is
        never edited)."""
        self.assertEqual(render_citation("розд.XIII/п.1-4", ED, "point"),
                         "розд. XIII п. 1-4 · ред. від 12.04.2026")

    def test_chapter_scoped_to_its_section(self):
        self.assertEqual(render_citation("розд.II/гл.5", ED, "chapter"),
                         "розд. II гл. 5 · ред. від 12.04.2026")

    def test_unnumbered_annex(self):
        self.assertEqual(render_citation("додаток", ED, "annex"),
                         "додаток · ред. від 12.04.2026")

    def test_approved_block_uses_its_title(self):
        self.assertEqual(render_citation("затв.1/п.4", ED, "point", block_title="ПОРЯДОК"),
                         "ПОРЯДОК (затв. 1) п. 4 · ред. від 12.04.2026")

    def test_preamble_point(self):
        self.assertEqual(render_citation("преамбула/п.1", ED, "point"),
                         "преамбула п. 1 · ред. від 12.04.2026")


class ApprovedBlockCitationCollision(unittest.TestCase):
    """Defect found at acceptance (2026-07-17): the затв.-scope renderer dropped the block INDEX
    — the only branch that did not use the already-captured `num`. In `560-2024-п` both затв.1
    and затв.2 are titled «ПОРЯДОК» (the same in `76-2023-п`), so 23 citation strings were
    shared by 46 chunks (15 + 8). One citation for two DIFFERENT chunks contradicts the
    one-citation-one-atom principle and undermines the structural citation gate: the citation
    no longer addresses exactly one atom_id.

    Decision: the block number goes into the citation — «ПОРЯДОК (затв. 1) п. 4» — ALWAYS, even
    for a lone block (a stable form). The live numbers of the fix were measured on the rebuilt
    chunk layer."""

    def test_two_blocks_with_the_same_title_do_not_collide(self):
        """RED before the fix: both rendered as «ПОРЯДОК (затв.) п. 4» — one string for two
        chunks. These are exactly the 15 collisions in 560-2024-п found at acceptance."""
        first = render_citation("затв.1/п.4", ED, "point", block_title="ПОРЯДОК")
        second = render_citation("затв.2/п.4", ED, "point", block_title="ПОРЯДОК")
        self.assertEqual(first, "ПОРЯДОК (затв. 1) п. 4 · ред. від 12.04.2026")
        self.assertEqual(second, "ПОРЯДОК (затв. 2) п. 4 · ред. від 12.04.2026")
        self.assertNotEqual(first, second)

    def test_number_is_rendered_even_for_a_lone_block(self):
        """Stable form: the number is included ALWAYS, even when the затв. block is the only one
        in the act — `z1109-08 затв.1` («Наказ»), 29 chunks."""
        self.assertEqual(render_citation("затв.1", ED, "approved", block_title="Наказ"),
                         "Наказ (затв. 1) · ред. від 12.04.2026")

    def test_block_without_a_title_still_carries_the_number(self):
        """Without `block_title` the form degrades to «затв. N» — but it still carries the
        number, otherwise two unnamed blocks would collide again.

        `block_title` is None in TWO cases, not one: (a) the `затв.N` unit is absent from the
        perimeter's latest edition, or (b) the unit exists but its `title IS NULL` — `titles`
        in `build()` stores the title value, not the fact that the unit exists, so `.get()`
        cannot tell the cases apart. Neither occurs in the perimeter: all 7 затв. blocks have
        a non-empty title (measured after the fix).

        The old fallback `block_title or 'Порядок'` was dead by LOGIC, not by data: the ternary
        evaluated its first branch only for a truthy `block_title`, so `or 'Порядок'` could
        never fire — on any corpus. Removed together with the fix."""
        self.assertEqual(render_citation("затв.2/п.1", ED, "point"),
                         "затв. 2 п. 1 · ред. від 12.04.2026")


class TokenizerPin(unittest.TestCase):
    """The 8192 gate is only as good as the artefact behind it: pin the FILE (revision +
    sha256), not the model name — the pin must hold the artefact ITSELF, not a copy. A silent
    revision bump on the Hub would move the gate under us with no signal."""

    def test_pin_is_a_full_commit_sha_and_file_digest(self):
        self.assertRegex(BGE_M3_REVISION, r"^[0-9a-f]{40}$")
        self.assertRegex(BGE_M3_TOKENIZER_SHA256, r"^[0-9a-f]{64}$")

    def test_window_is_the_bge_m3_context(self):
        self.assertEqual(WINDOW, 8192)

    def test_tampered_artefact_refuses_to_build(self):
        """Tampering with the pinned artefact → SystemExit, NOT a silent shift of the 8192 gate.

        This is half of the requirement «a missing/substituted pin → a red run in the journal»:
        here it is pinned that the chunker REFUSES to build; the other half (the orchestrator
        journals such a refusal as failed) lives with the orchestrator, which is not part of
        this extract. SystemExit is a BaseException, so `except Exception` in main() does NOT
        swallow it and the message goes to stderr → `ingest_errors`."""
        d = Path(tempfile.mkdtemp())
        try:
            fake = d / "tokenizer.json"
            fake.write_bytes(b'{"version":"1.0","model":{"vocab":{}}}')   # not the pinned bytes
            with mock.patch("huggingface_hub.hf_hub_download", return_value=str(fake)), \
                 self.assertRaises(SystemExit) as cm:
                load_tokenizer()
            self.assertIn("sha256 mismatch", str(cm.exception))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class ChunksFloor(unittest.TestCase):
    """The rebuild validator holds the rebuilt layer to a floor. The number lives in the
    chunker (next to the PERIMETER that determines it), so the orchestrator reads it instead of
    keeping a copy — one writer per fact."""

    def test_floor_is_the_accepted_count(self):
        self.assertEqual(CHUNKS_FLOOR, 4706)   # 4 927 units − 205 ineligible − 16 oversize


if __name__ == "__main__":
    unittest.main(verbosity=2)
