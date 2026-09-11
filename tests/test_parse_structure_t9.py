"""Parser branches that close the structural defects left by the first (v0) unit parser.

Every case below is RED on the previous parser and GREEN on this one; each test names the
exact defect it pins and the corpus evidence it was derived from. Fixtures are minimal but
copied verbatim from the real Rada TXT shapes, so a regression in a regex reproduces the
original corpus damage rather than a toy failure.

NB the corpus TXT terminates lines with \\r\\r\\n; Python's universal-newline read turns that
into "\\n\\n", so the parser always sees a blank line between content lines. The fixtures
reproduce that spacing where it matters.

    uv run python -m unittest discover -s tests -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.rada.parse_structure import (  # noqa: E402
    GLAVA_RE, ROMAN_SECTION_RE, Unit, _clean, _dedupe, _markers, _norm_section, _quote_depths,
    _quote_eof_warn, _roman_sections, parse_edition, reconcile_runs)


def _paths(units, kind=None):
    return [u.path for u in units if kind is None or u.kind == kind]


def _by_path(units, path):
    return next((u for u in units if u.path == path), None)


class QuotedAmendmentGuard(unittest.TestCase):
    """v0 defect: a «Стаття N.» QUOTED inside an amendment block became a real article.

    RED on the old parser: 1404-19 line 2511 «Стаття 1214.» (a Господарський ПК article
    quoted by «є) доповнити статтями 1213 і 1214 такого змісту:») was parsed as an article
    OF 1404-19 and, being the last one in the file, swallowed 612 lines / 59 556 chars of
    Прикінцеві та перехідні положення. Only the FIRST heading of a multi-heading quote
    carries the leading '"', which is why 121-3 was skipped and 121-4 leaked.
    The same shape produced 3633-IX ст.27 (141 902 chars); a corpus sweep found exactly 74
    such headings and 0 false positives.
    """

    FIXTURE = "\n".join([
        "ЗАКОН УКРАЇНИ",
        "Про виконавче провадження",
        "",
        "Розділ I",
        "",
        "ЗАГАЛЬНІ ПОЛОЖЕННЯ",
        "",
        "Стаття 1. Виконавче провадження",
        "",
        "1. Виконавче провадження є завершальною стадією судового провадження.",
        "",
        "Розділ XIII",
        "",
        "ПРИКІНЦЕВІ ТА ПЕРЕХІДНІ ПОЛОЖЕННЯ",
        "",
        "1. Цей Закон набирає чинності з дня його опублікування.",
        "",
        "2. Внести зміни до таких законодавчих актів України:",
        "",
        "є) доповнити статтями 121-3 і 121-4 такого змісту:",
        "",
        '"Стаття 121-3. Вирішення питання про звернення стягнення',
        "",
        "Питання про звернення стягнення розглядає господарський суд.",
        "",
        "Стаття 121-4. Заміна сторони виконавчого провадження",
        "",
        "У разі вибуття однієї із сторін виконавчого провадження суд вирішує питання.",
        "",
        'Ухвала надсилається особам, які брали участь у справі";',
        "",
        "3. Кабінету Міністрів України привести акти у відповідність.",
        "",
    ])

    def test_quoted_article_is_not_an_article_of_this_act(self):
        units = parse_edition(self.FIXTURE)
        # RED before: ['ст.1', 'ст.121-4']  (ст.121-3 was already skipped by its quote)
        self.assertEqual(_paths(units, "article"), ["ст.1"])

    def test_rozdil_keeps_the_span_the_phantom_used_to_swallow(self):
        units = parse_edition(self.FIXTURE)
        rozd = _by_path(units, "розд.XIII")
        self.assertIsNotNone(rozd)
        # RED before: text == title (33 chars for the real act) — the body was discarded.
        self.assertIn("Цей Закон набирає чинності", rozd.text)
        self.assertIn("Кабінету Міністрів України привести акти", rozd.text)

    def test_quoted_parts_do_not_become_points_of_this_act(self):
        """The quoted article's own частини must not surface as our points."""
        units = parse_edition(self.FIXTURE)
        # RED before: ст.121-4/п.1 … — the quoted ГПК article's частини surfaced as ours.
        self.assertEqual(_paths(units, "point"),
                         ["ст.1/п.1", "розд.XIII/п.1", "розд.XIII/п.2", "розд.XIII/п.3"])

    def test_amendment_block_stays_inside_its_own_point(self):
        units = parse_edition(self.FIXTURE)
        p2 = _by_path(units, "розд.XIII/п.2")
        self.assertIn("Стаття 121-4", p2.text)   # kept verbatim, as legal text
        self.assertIn("доповнити статтями", p2.text)


class QuoteDepth(unittest.TestCase):
    """Directional quote-span tracking. Plain parity is NOT usable: a line may close a
    quote it never opened (1404-19 line 2499 ends with '";' and desynchronises the count,
    leaving depth 0 exactly at the phantom), and 8/14 acts have an odd total '"' count —
    2747-15 has a genuinely unclosed quote in the official source."""

    def test_open_at_line_start_close_at_line_end(self):
        lines = ['текст', '"Стаття 5. Назва', 'тіло статті', 'кінець цитати";', 'далі']
        self.assertEqual(_quote_depths(lines), [0, 0, 1, 1, 0])

    def test_self_contained_quote_does_not_open(self):
        lines = ['слова "на службу" замінити словами "на органи";', 'Стаття 7. Назва']
        self.assertEqual(_quote_depths(lines), [0, 0])

    def test_law_name_in_quotes_on_its_own_line_is_self_contained(self):
        # 1404-19 annex header carries a bare quoted act name — must not open a span.
        lines = ['Додаток', 'до Закону України', '"Про виконавче провадження"', 'ПЕРЕЛІК']
        self.assertEqual(_quote_depths(lines), [0, 0, 0, 0])

    def test_closing_line_resets_even_without_a_matching_open(self):
        """Self-healing: an unbalanced close cannot leave the file stuck open."""
        lines = ['кінець чогось";', 'Стаття 1. Назва']
        self.assertEqual(_quote_depths(lines), [0, 0])

    def test_blank_form_date_field_does_not_open_a_span(self):
        """RED in the first cut of this fix: opening a span on ANY leading quote made
        z1109-08's blank-form date convention «"___"_________ 20___ року» open one that closed
        ~1 700 lines later at a line ending in a quote — flagging 2 466/10 167 lines (24 %) of
        9 editions as "quoted foreign act" and cutting them from ~250 units to 48. The opener
        now requires a quoted STRUCTURAL heading, which z1109-08 does not contain even once."""
        lines = ['"___"_________ 20___ року одержав(ла) __________',
                 'I. Відношення, лист, скаргу, заяву (N і дата документа): ____',
                 'Придатний за графами ТДВ "А"',
                 'III. Прізвище, ім\'я, по батькові ______ рік народження']
        self.assertEqual(_quote_depths(lines), [0, 0, 0, 0])

    def test_only_a_quoted_structural_heading_opens_a_span(self):
        for opener, opens in [('"Стаття 121-3. Назва', True),
                              ('"Розділ VI1.', True),
                              ('"Глава 2', True),
                              ('"Додаток 5', True),
                              ('"На підставі посвідчення, пред\'явленого не пізніше', False),
                              ('"____" _____________ 20___ року', False)]:
            got = _quote_depths([opener, 'наступний рядок'])[1]
            self.assertEqual(bool(got), opens, opener)


class RomanChapter(unittest.TestCase):
    """v0 defect: GLAVA_RE accepted only arabic numbers, so 2232-12 (військовий обов'язок)
    — whose 15 chapters are ALL Roman — had 0 chapter units, and «Глава XII ПРИКІНЦЕВІ
    ПОЛОЖЕННЯ» leaked into ст.45's body (live: 185 ~N dup paths, now 0)."""

    def test_roman_chapter_matches(self):
        for raw, want in [("Глава XII", "XII"), ("Глава I", "I"),
                          ("Глава III1.", "III1"), ("ГЛАВА X1. ІНТЕЛЕКТУАЛЬНА", "X1")]:
            m = GLAVA_RE.match(raw)
            self.assertIsNotNone(m, raw)      # RED before: None for every one of these
            self.assertEqual(m.group(1), want, raw)

    def test_arabic_chapter_still_matches(self):
        for raw, want in [("Глава 1", "1"), ("Глава 13-А", "13-А")]:
            self.assertEqual(GLAVA_RE.match(raw).group(1), want, raw)

    def test_collapsed_superscript_chapter_is_a_KNOWN_LIMIT_not_a_target(self):
        """«Глава 241.» is Глава 24¹ collapsed by the TXT export, and the SAME chapter renders
        «Глава 24-1» in other editions → one chapter, two paths across editions.

        This asserts the CURRENT (defective) behaviour deliberately, so the pin is visible:
        chapter-level superscript collapse (the 4695-20 ст.55/п.181 class) was deferred and is
        NOT disambiguated here. Do NOT read this test as "гл.241 is correct" — it is a known,
        documented residual. The hyphen fix below is a different defect (a real PK collision)
        and IS fixed."""
        self.assertEqual(GLAVA_RE.match("Глава 241.").group(1), "241")   # true form: 24-1
        self.assertEqual(GLAVA_RE.match("Глава 24-1").group(1), "24-1")  # other editions

    def test_hyphenated_chapter_number_kept_whole(self):
        """RED before: «Глава 24-1» captured only «24» → collided with the real Глава 24
        and was dedupe-suffixed as розд.IV/гл.24~2 in 117 editions of 8073-10 + 74 of
        80732-10 — the same collapse trap one structural level down."""
        self.assertEqual(GLAVA_RE.match("Глава 24-1").group(1), "24-1")

    def test_roman_superscript_chapter_normalised(self):
        self.assertEqual(_norm_section("III1"), "III-1")
        self.assertEqual(_norm_section("X1"), "X-1")
        self.assertEqual(_norm_section("XII"), "XII")

    def test_cyrillic_letter_suffix_is_not_folded_to_latin(self):
        """«13-А» carries a genuinely Cyrillic А — homoglyph folding must not touch it."""
        self.assertEqual(_norm_section("13-А"), "13-А")


class CyrillicHomoglyphRoman(unittest.TestCase):
    """Rada mixes Cyrillic look-alikes INTO Roman numerals: z1109-08 writes «ХV» as
    Cyrillic Х (U+0425) + LATIN V and «ХІ» as Cyrillic Х + Cyrillic І (U+0406). 8 of its
    38 Roman headings were invisible → дод.2/розд.IX swallowed розд.X–XIII (95 184 chars).
    Verified corpus-wide: no Розділ/Глава heading uses homoglyphs, only bare-Roman ones."""

    def test_homoglyph_numerals_match_and_fold(self):
        for raw, want in [("ХV", "XV"), ("ХІ", "XI"), ("І", "I"), ("ХIII", "XIII")]:
            m = ROMAN_SECTION_RE.match(f"{raw}. Хвороби системи кровообігу")
            self.assertIsNotNone(m, raw)        # RED before: None
            self.assertEqual(_norm_section(m.group(1)), want, raw)

    def test_latin_numerals_unaffected(self):
        m = ROMAN_SECTION_RE.match("XVIII. Інші хворобливі прояви")
        self.assertEqual(_norm_section(m.group(1)), "XVIII")


class RomanSectionGuard(unittest.TestCase):
    """Bare «I.»/«II.» is the section level ONLY for acts with no «Розділ» heading.
    КУпАП has BOTH: its «I. ЗАГАЛЬНА ЧАСТИНА» is a sub-heading inside Розділ II, so
    honouring it there would duplicate розд.I and re-parent all 39 chapters."""

    def test_guard_off_when_act_has_rozdil(self):
        self.assertFalse(_roman_sections(["Розділ I. ЗАГАЛЬНІ ПОЛОЖЕННЯ",
                                          "I. ЗАГАЛЬНА ЧАСТИНА", "Глава 2"]))

    def test_guard_on_for_rozdil_less_act(self):
        self.assertTrue(_roman_sections(["I. Внести зміни", "II. Прикінцеві положення"]))

    def test_kupap_shape_keeps_chapters_under_the_real_section(self):
        text = "\n".join([
            "Кодекс України про адміністративні правопорушення",
            "",
            "Розділ II. АДМІНІСТРАТИВНЕ ПРАВОПОРУШЕННЯ",
            "",
            "I. ЗАГАЛЬНА ЧАСТИНА",
            "",
            "Глава 2",
            "",
            "Адміністративне правопорушення",
            "",
            "Стаття 9. Поняття",
            "",
            "1. Адміністративним правопорушенням визнається діяння.",
            "",
        ])
        units = parse_edition(text)
        self.assertEqual(_paths(units, "section"), ["розд.II"])   # not розд.I as well
        self.assertEqual(_paths(units, "chapter"), ["розд.II/гл.2"])


class SectionBodyAndPoints(unittest.TestCase):
    """v0 limitation: section/chapter units stored ONLY their title, so a розділ carrying
    points instead of articles (Прикінцеві/Перехідні положення — the виконавче-провадження
    moratoria) was dropped whole. A section that DOES contain articles must be unchanged."""

    def test_section_with_articles_still_stores_just_its_title(self):
        text = "\n".join([
            "ЗАКОН УКРАЇНИ", "Про щось", "",
            "Розділ I", "", "ЗАГАЛЬНІ ПОЛОЖЕННЯ", "",
            "Стаття 1. Назва", "", "1. Текст статті.", "",
        ])
        units = parse_edition(text)
        sec = _by_path(units, "розд.I")
        self.assertEqual(sec.text, "ЗАГАЛЬНІ ПОЛОЖЕННЯ")   # no article text pulled in
        self.assertEqual(_paths(units, "point"), ["ст.1/п.1"])

    def test_transitional_section_gets_body_and_points(self):
        text = "\n".join([
            "ЗАКОН УКРАЇНИ", "Про щось", "",
            "Розділ XIII", "", "ПРИКІНЦЕВІ ТА ПЕРЕХІДНІ ПОЛОЖЕННЯ", "",
            "1. Цей Закон набирає чинності з дня опублікування.", "",
            "2. Установити, що до 1 січня 2028 року:", "",
            "зупиняється вчинення виконавчих дій та заходів примусового виконання рішень.", "",
        ])
        units = parse_edition(text)
        # RED before: розд.XIII text == title, and NO points at all.
        self.assertEqual(_paths(units, "point"), ["розд.XIII/п.1", "розд.XIII/п.2"])
        self.assertIn("зупиняється вчинення виконавчих дій",
                      _by_path(units, "розд.XIII/п.2").text)
        self.assertIn("зупиняється вчинення виконавчих дій",
                      _by_path(units, "розд.XIII").text)


class PostanovaPointFirst(unittest.TestCase):
    """v0 limitation: a постанова has no «Стаття», so the whole act collapsed into ONE
    preamble blob (560-2024-п = 202 869 chars, 1 unit). Its real shape is: the постанова's
    own пункти, then ЗАТВЕРДЖЕНО blocks (each approving a ПОРЯДОК) and Додатки — every one
    of them restarting «N.» at 1, which is why they must each be their own scope."""

    FIXTURE = "\n".join([
        "КАБІНЕТ МІНІСТРІВ УКРАЇНИ", "ПОСТАНОВА",
        "від 16 травня 2024 р. № 560", "Київ",
        "Питання проведення призову громадян на військову службу",
        "",
        "1. Затвердити такі, що додаються:", "",
        "Порядок проведення призову громадян на військову службу;", "",
        "2. Ця постанова набирає чинності з дня опублікування.", "",
        "ЗАТВЕРДЖЕНО", "постановою Кабінету Міністрів України",
        "від 16 травня 2024 р. № 560", "",
        "ПОРЯДОК", "проведення призову громадян на військову службу", "",
        "1. Цей Порядок визначає механізм призову.", "",
        "2. На військову службу призиваються резервісти.", "",
        "Додаток 1", "до Порядку", "", "ЗРАЗКИ", "повісток", "",
        "Додаток 4", "до Порядку",
        "(в редакції постанови Кабінету Міністрів України", "від 24 жовтня 2025 р. № 1364)",
        "", "ЗАЯВА", "",
        "Додаток 5", "до Порядку", "", "ПЕРЕЛІК",
        "документів, що подаються військовозобов'язаним", "",
        "1. Частина перша статті 23 Закону", "",
        "2. Частина третя статті 23 Закону", "",
    ])

    def test_postanova_is_no_longer_one_blob(self):
        units = parse_edition(self.FIXTURE)
        # RED before: exactly one unit, kind=preamble, holding the whole act.
        self.assertGreater(len(units), 1)
        kinds = {u.kind for u in units}
        self.assertEqual(kinds, {"preamble", "point", "approved", "annex"})

    def test_each_block_is_its_own_numbering_scope(self):
        units = parse_edition(self.FIXTURE)
        # RED before: nothing; a naive file-wide point parser would collide these
        # three separate «1.» runs onto one path and dedupe-suffix them ~2/~3.
        self.assertEqual(_paths(units, "point"), [
            "преамбула/п.1", "преамбула/п.2",
            "затв.1/п.1", "затв.1/п.2",
            "дод.5/п.1", "дод.5/п.2",
        ])
        self.assertEqual(_dedupe(units), 0)

    def test_hero_annex_zaiava_is_present_with_its_title(self):
        """Додаток 4 «ЗАЯВА» is the official відстрочка application form — a headline query."""
        units = parse_edition(self.FIXTURE)
        self.assertEqual(_paths(units, "annex"), ["дод.1", "дод.4", "дод.5"])
        self.assertEqual(_by_path(units, "дод.4").title, "ЗАЯВА")
        self.assertEqual(_by_path(units, "дод.1").title, "ЗРАЗКИ")

    def test_approved_document_title_is_the_caption_not_the_provenance(self):
        units = parse_edition(self.FIXTURE)
        self.assertEqual(_by_path(units, "затв.1").title, "ПОРЯДОК")


class AnnexScoping(unittest.TestCase):
    """An annex restarts every numbering it contains. z1109-08 carries TWO Розклад-хвороб
    annexes that each run «I.»…«XVIII.», so unscoped розд.I meant three different things
    (live: 1 558 ~N dups before scoping)."""

    FIXTURE = "\n".join([
        "МІНІСТЕРСТВО ОБОРОНИ УКРАЇНИ", "НАКАЗ", "14.08.2008 № 402",
        "Про затвердження Положення про військово-лікарську експертизу", "",
        "ЗАТВЕРДЖЕНО", "Наказ Міністерства оборони України", "", "ПОЛОЖЕННЯ", "",
        "I. Основи організації військово-лікарської експертизи", "",
        "1. Військово-лікарська експертиза проводиться комісіями.", "",
        "Додаток 1", "до Положення", "", "РОЗКЛАД", "хвороб", "",
        "I. Деякі інфекційні та паразитарні хвороби", "",
        "1. Хвороба у стадії загострення.", "",
        "Додаток 2", "до Положення", "", "ПОЯСНЕННЯ", "",
        "I. Деякі інфекційні та паразитарні хвороби", "",
        "1. Наслідки перенесених хвороб.", "",
    ])

    def test_same_roman_section_under_different_annexes_does_not_collide(self):
        units = parse_edition(self.FIXTURE)
        self.assertEqual(_paths(units, "section"),
                         ["затв.1/розд.I", "дод.1/розд.I", "дод.2/розд.I"])
        self.assertEqual(_dedupe(units), 0)   # RED before scoping: розд.I ~2 and ~3

    def test_points_are_scoped_to_their_annex(self):
        units = parse_edition(self.FIXTURE)
        self.assertEqual(_paths(units, "point"), [
            "затв.1/розд.I/п.1", "дод.1/розд.I/п.1", "дод.2/розд.I/п.1"])

    def test_unnumbered_annex_gets_a_stable_path(self):
        """1404-19 ends with a bare, UNNUMBERED «Додаток» (its Перелік майна, 1.–13.) —
        RED before: that list collided with розд.XIII's own points 1.–13. (~2 suffixes)."""
        text = "\n".join([
            "ЗАКОН УКРАЇНИ", "Про виконавче провадження", "",
            "Розділ XIII", "", "ПРИКІНЦЕВІ ТА ПЕРЕХІДНІ ПОЛОЖЕННЯ", "",
            "1. Цей Закон набирає чинності з дня опублікування.", "",
            "Додаток", "до Закону України", '"Про виконавче провадження"', "",
            "ПЕРЕЛІК", "майна, на яке не може бути звернено стягнення", "",
            "1. Предмети щоденного побутового особистого вжитку.", "",
        ])
        units = parse_edition(text)
        self.assertEqual(_paths(units, "annex"), ["додаток"])
        self.assertEqual(_paths(units, "point"), ["розд.XIII/п.1", "додаток/п.1"])
        self.assertEqual(_dedupe(units), 0)


class CollapsedPointSuperscripts(unittest.TestCase):
    """Collapsed superscript POINT numbers are resolved by walking the run in document order
    and tracking the base — the same canonical mechanic `_article_num` already applies to
    articles.

    RED before: 1404-19 розд.XIII latest stored п.11…п.16 (really п.1¹…п.1⁶) and п.101…п.108
    (really п.10-1…п.10-8), while 69/58/29/16/16/12 OTHER editions carry the hyphenated form —
    one point under two paths across editions (the core defect class), and 5 of the 7
    виконавче-провадження moratoria sat on collapsed paths.
    """

    # the real 1404-19 розд.XIII run: 1, 1¹…1⁶, 2, 3 … 10, 10¹…10³, then the GENUINE п.11
    FIXTURE = "\n".join([
        "ЗАКОН УКРАЇНИ", "Про виконавче провадження", "",
        "Розділ XIII", "", "ПРИКІНЦЕВІ ТА ПЕРЕХІДНІ ПОЛОЖЕННЯ", "",
        "1. Цей Закон набирає чинності з дня опублікування.", "",
        "11. До 1 січня 2018 року приватний виконавець не може здійснювати виконання.", "",
        "14. Установити, що до 1 січня 2028 року: зупиняється вчинення виконавчих дій.", "",
        "2. Визнати такими, що втратили чинність:", "",
        "3. Внести зміни до таких законодавчих актів України:", "",
        "10. Скарги на рішення органів державної виконавчої служби розглядаються судом.", "",
        "101. На період дії мораторію зупиняється вчинення виконавчих дій.", "",
        "102. До набрання чинності законом щодо осіб, пов'язаних з державою-агресором.", "",
        "11. Кабінету Міністрів України привести акти у відповідність із цим Законом.", "",
    ])

    def test_superscripts_hyphenated_and_genuine_point_kept(self):
        units = parse_edition(self.FIXTURE)
        self.assertEqual(_paths(units, "point"), [
            "розд.XIII/п.1", "розд.XIII/п.1-1", "розд.XIII/п.1-4",
            "розд.XIII/п.2", "розд.XIII/п.3", "розд.XIII/п.10",
            "розд.XIII/п.10-1", "розд.XIII/п.10-2",
            "розд.XIII/п.11",          # GENUINE — follows base 10, which «11» does not extend
        ])

    def test_the_collision_that_produced_the_last_1404_19_dup_is_gone(self):
        """п.1¹ and the genuine п.11 both rendered «11.» → dedupe suffix п.11~2. Now distinct."""
        units = parse_edition(self.FIXTURE)
        self.assertEqual(_dedupe(units), 0)

    def test_moratorium_lands_on_the_canonical_path(self):
        units = parse_edition(self.FIXTURE)
        self.assertIn("зупиняється вчинення виконавчих дій",
                      _by_path(units, "розд.XIII/п.1-4").text)

    def test_number_without_a_base_in_front_is_left_alone(self):
        """No evidence → no rename: a number is never rewritten without corroboration."""
        text = "\n".join(["ЗАКОН УКРАЇНИ", "Про щось", "", "Розділ I", "", "ЗАГАЛЬНІ", "",
                          "181. Пункт без попереднього базового номера.", ""])
        self.assertEqual(_paths(parse_edition(text), "point"), ["розд.I/п.181"])


class PositionalCorroborationGuard(unittest.TestCase):
    """Follow-up fix found at acceptance: base tracking fires on ONE adjacency to the base, so a
    dangling «1., 11.» — with п.2–п.10 absent or living entirely inside {…} markers, hence
    invisible as bare «N.» — would turn a GENUINE п.11 into a FALSE п.1-1. A collapsed reading
    is accepted only if the suffix series is BRACKETED: the run resumes with a plain number.

    Measured: all 59 real renames in the corpus are corroborated (56 twin + 3 positional), so
    the guard costs nothing today — it closes the edge, not a live finding."""

    def _points(self, *lines):
        text = "\n".join(["ЗАКОН УКРАЇНИ", "Про щось", "", "Розділ I", "", "ЗАГАЛЬНІ", "",
                          *[x for ln in lines for x in (ln, "")]])
        return _paths(parse_edition(text), "point")

    def test_dangling_run_is_NOT_renamed(self):
        """RED before the guard: «1., 11.» at the end of a run → false п.1-1."""
        self.assertEqual(
            self._points("1. Цей Закон набирає чинності.",
                         "11. Кабінету Міністрів привести акти у відповідність."),
            ["розд.I/п.1", "розд.I/п.11"])          # п.11 stays GENUINE — no continuation

    def test_dangling_series_is_NOT_renamed(self):
        self.assertEqual(
            self._points("1. Перший.", "11. Одинадцятий.", "12. Дванадцятий."),
            ["розд.I/п.1", "розд.I/п.11", "розд.I/п.12"])

    def test_bracketed_run_IS_renamed(self):
        """The run resumes with a plain «2.» → the series is bracketed → superscripts."""
        self.assertEqual(
            self._points("1. Перший.", "11. Один-один.", "12. Один-два.", "2. Другий."),
            ["розд.I/п.1", "розд.I/п.1-1", "розд.I/п.1-2", "розд.I/п.2"])

    def test_the_three_position_only_corpus_shapes(self):
        """The exact runs behind the corpus's 3 position-only renames (4695-20 «18,181,19»;
        560-2024-п «66,661,67»; 1404-19 «…1012,1013,1014, 11»)."""
        self.assertEqual(self._points("18. Вісімнадцятий.", "181. Вісімнадцять-один.",
                                      "19. Дев'ятнадцятий."),
                         ["розд.I/п.18", "розд.I/п.18-1", "розд.I/п.19"])
        self.assertEqual(self._points("66. Шістдесят шостий.", "661. Шістдесят шість-один.",
                                      "67. Шістдесят сьомий."),
                         ["розд.I/п.66", "розд.I/п.66-1", "розд.I/п.67"])

    def test_hint_is_recorded_when_the_guard_declines(self):
        """A declined rename must remain rescuable by a cross-edition twin."""
        text = "\n".join(["ЗАКОН УКРАЇНИ", "Про щось", "", "Розділ I", "", "ЗАГАЛЬНІ", "",
                          "1. Перший.", "", "11. Спірний.", ""])
        u = _by_path(parse_edition(text), "розд.I/п.11")
        self.assertEqual(u.hint, "1-1")


class TwinRescue(unittest.TestCase):
    """The positional guard declines a dangling series; a cross-edition twin may still
    corroborate it — a розділ whose tail reads «… 10, 101, 102» (EOF) while the act's other
    editions render 10-1 / 10-2. `reconcile_runs` acts ONLY on base-tracking candidates
    (`hint`): `known` legitimately contains п.1-1, so an unscoped twin check would rename the
    GENUINE п.11 of 1404-19 and recreate the collision base tracking removed."""

    DANGLING = "\n".join(["ЗАКОН УКРАЇНИ", "Про щось", "", "Розділ I", "", "ЗАГАЛЬНІ", "",
                          "10. Десятий.", "", "101. Десять-один.", ""])

    def test_twin_rescues_a_declined_rename(self):
        units = parse_edition(self.DANGLING)
        self.assertEqual(_paths(units, "point"), ["розд.I/п.10", "розд.I/п.101"])  # guard held
        n = reconcile_runs([("ed", units)], known={"розд.I/п.10-1"})               # twin exists
        self.assertEqual(n, 1)
        self.assertEqual(_paths(units, "point"), ["розд.I/п.10", "розд.I/п.10-1"])

    def test_no_twin_no_rescue(self):
        units = parse_edition(self.DANGLING)
        self.assertEqual(reconcile_runs([("ed", units)], known=set()), 0)
        self.assertEqual(_paths(units, "point"), ["розд.I/п.10", "розд.I/п.101"])

    def test_genuine_number_is_never_touched_even_when_its_twin_exists(self):
        """The load-bearing scoping test: a genuine п.11 (base 10 does not extend to 11) has no
        hint, so the twin п.1-1 in `known` must not drag it anywhere."""
        text = "\n".join(["ЗАКОН УКРАЇНИ", "Про щось", "", "Розділ I", "", "ЗАГАЛЬНІ", "",
                          "1. Перший.", "", "11. Один-один.", "", "2. Другий.", "",
                          "10. Десятий.", "", "11. СПРАВЖНІЙ одинадцятий.", ""])
        units = parse_edition(text)
        self.assertEqual(_paths(units, "point"),
                         ["розд.I/п.1", "розд.I/п.1-1", "розд.I/п.2",
                          "розд.I/п.10", "розд.I/п.11"])
        self.assertEqual(reconcile_runs([("ed", units)], known={"розд.I/п.1-1"}), 0)
        self.assertEqual(_by_path(units, "розд.I/п.11").text.split(".")[1].strip(),
                         "СПРАВЖНІЙ одинадцятий")


class CollapsedAnnexSuperscript(unittest.TestCase):
    """The same trap one level up. 560-2024-п runs Додаток 1, 1¹, 2 … 10, 11 … and the
    TXT renders 1¹ as «Додаток 11» — a PK collision between two DIFFERENT annexes
    (СЛУЖБОВЕ ПОСВІДЧЕННЯ vs НАПРАВЛЕННЯ), previously survived only by a ~N suffix."""

    FIXTURE = "\n".join([
        "КАБІНЕТ МІНІСТРІВ УКРАЇНИ", "ПОСТАНОВА", "від 16 травня 2024 р. № 560", "",
        "Додаток 1", "до Порядку", "", "ЗРАЗКИ", "повісток", "",
        "Додаток 11", "до Порядку", "", "СЛУЖБОВЕ ПОСВІДЧЕННЯ", "",
        "Додаток 2", "до Порядку", "", "АКТ", "",
        "Додаток 10", "до Порядку", "", "ПОВІДОМЛЕННЯ", "",
        "Додаток 11", "до Порядку", "", "НАПРАВЛЕННЯ", "",
        "Додаток 12", "до Порядку", "", "ЖУРНАЛ", "",
    ])

    def test_superscript_annex_separated_from_the_genuine_one(self):
        units = parse_edition(self.FIXTURE)
        self.assertEqual(_paths(units, "annex"),
                         ["дод.1", "дод.1-1", "дод.2", "дод.10", "дод.11", "дод.12"])
        self.assertEqual(_by_path(units, "дод.1-1").title, "СЛУЖБОВЕ ПОСВІДЧЕННЯ")
        self.assertEqual(_by_path(units, "дод.11").title, "НАПРАВЛЕННЯ")   # genuine
        self.assertEqual(_dedupe(units), 0)                                 # RED before: дод.11~2


class DedupePrefersSubstantive(unittest.TestCase):
    """On a collision the canonical path goes to the NON-EMPTY unit.

    RED before: КУпАП renders a repeal as «Стаття 163. {Статтю 163 виключено …}» whose whole
    body is a marker; stripped, it is empty — and, being first in document order, it kept
    `ст.163` while the live re-issued article (694 chars) was pushed to `ст.163~2`."""

    def _u(self, path, text, ordinal):
        return Unit(path, "article", ordinal, None, text, [])

    def test_empty_husk_yields_the_canonical_path_to_the_live_article(self):
        units = [self._u("ст.163", "", 1), self._u("ст.163", "Розміщення цінних паперів", 2)]
        self.assertEqual(_dedupe(units), 1)
        live = next(u for u in units if u.text)
        husk = next(u for u in units if not u.text)
        self.assertEqual(live.path, "ст.163")      # RED before: ст.163~2
        self.assertEqual(husk.path, "ст.163~2")

    def test_no_unit_is_dropped(self):
        units = [self._u("ст.163", "", 1), self._u("ст.163", "жива стаття", 2)]
        _dedupe(units)
        self.assertEqual(len(units), 2)
        self.assertEqual(len({u.path for u in units}), 2)

    def test_substantive_tie_keeps_document_order(self):
        """Two REAL twins (2747-15 ст.183-7) — order must stay deterministic, first wins."""
        units = [self._u("ст.183-7", "перша справжня стаття", 1),
                 self._u("ст.183-7", "друга справжня стаття", 2)]
        _dedupe(units)
        self.assertEqual([u.path for u in units], ["ст.183-7", "ст.183-7~2"])


class QuoteEofGate(unittest.TestCase):
    """An amendment-quote block that never closes eats the act's tail SILENTLY — every later
    heading is suppressed and no counter notices. Depth at EOF must therefore be 0."""

    def test_unclosed_quote_is_reported(self):
        lines = ['ЗАКОН УКРАЇНИ', 'Про щось', '',
                 'є) доповнити статтею 5 такого змісту:', '',
                 '"Стаття 5. Назва процитованої статті', '',
                 'Текст процитованої статті без закриваючої лапки.', '',
                 'Стаття 6. Ця стаття буде ПРИДУШЕНА мовчки', '']
        w = _quote_eof_warn(lines)
        self.assertIsNotNone(w)
        self.assertIn("UNCLOSED", w)

    def test_closed_quote_is_silent(self):
        lines = ['є) доповнити статтею 5 такого змісту:', '',
                 '"Стаття 5. Назва', '', 'Текст статті";', '',
                 'Стаття 6. Справжня стаття', '']
        self.assertIsNone(_quote_eof_warn(lines))

    def test_corpus_shape_without_quotes_is_silent(self):
        self.assertIsNone(_quote_eof_warn(['Стаття 1. Назва', '', '1. Текст.', '']))


class AmendmentNotes(unittest.TestCase):
    """Amendment notes {…} leave the clean text as provenance, and only the notes leave it. An
    article amended twice carries two separate notes; a pattern that ran from the first «{» to
    the last «}» would delete the legal text between them without a trace and store the norm
    inside one giant marker. Two shapes: notes on their own lines, and two inline notes in one
    sentence."""

    SPANS = {
        "notes on their own lines": ("\n".join([
            "Стаття 7. Строк звернення",
            "",
            "1. Скарга подається протягом десяти днів.",
            "",
            "{Частина перша із змінами, внесеними згідно із Законом № 1234-IX від 01.01.2024}",
            "",
            "2. Строк не поширюється на військовослужбовців у районах бойових дій.",
            "",
            "{Статтю 7 доповнено частиною другою згідно із Законом № 5678-IX від 02.02.2025}",
            "",
        ]), "2. Строк не поширюється на військовослужбовців у районах бойових дій."),
        "two notes in one sentence": (
            "3. Рішення оскаржується до суду {Із змінами, внесеними згідно із Законом № 1234-IX} "
            "або до вищого органу {Із змінами, внесеними згідно із Законом № 5678-IX}.",
            "або до вищого органу"),
    }

    def test_text_between_two_notes_is_kept(self):
        for shape, (span, between) in self.SPANS.items():
            with self.subTest(shape):
                clean = _clean(span)
                self.assertIn(between, clean)              # RED under a greedy pattern
                self.assertNotIn("{", clean)
                self.assertNotIn("Законом", clean)         # the notes themselves are gone

    def test_both_notes_become_markers(self):
        for shape, (span, between) in self.SPANS.items():
            with self.subTest(shape):
                markers = _markers(span)
                self.assertEqual(len(markers), 2)          # a greedy pattern finds one
                self.assertTrue(all(m.startswith("{") and m.endswith("}") and "Законом" in m
                                    for m in markers))
                self.assertFalse(any(between in m for m in markers))   # no norm in a marker


if __name__ == "__main__":
    unittest.main(verbosity=2)
