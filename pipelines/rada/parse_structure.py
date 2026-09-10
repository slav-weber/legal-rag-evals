"""Parse a Rada edition TXT into structural units (parser v0).

Splits a legislation edition into units: the preamble, sections (Розділ),
articles (Стаття N.) and their numbered parts/points (N.). Amendment markers
``{...}`` are pulled out as provenance into ``inline_markers`` and stripped from
the clean ``text`` so that a text diff reflects substantive changes, not churn in
the change-history notes. Units land in the ``units`` table keyed by a stable,
article-number-based ``unit_path`` (ст.4, ст.13-1, ст.4/п.4, розд.VI-1) so the
same article diffs cleanly across editions.

This is v0: good enough to see articles as units and diff editions, NOT a perfect
structural model. The TXT export collapses the superscript in article 13¹ to "131"
(and 163¹⁰ to "16310"); ``_article_num`` disambiguates these back to ст.13-1 /
ст.163-10 by structural position. Known remaining v0 limits are called out inline
at the code that carries them.

Run:
  uv run python -m pipelines.rada.parse_structure 3543-12          # all editions
  uv run python -m pipelines.rada.parse_structure 2747-15 --current
  uv run python -m pipelines.rada.parse_structure --all            # every act w/ txt
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Windows consoles default to cp1251 and choke on Cyrillic / arrows in output.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pipelines import summary as _summary  # noqa: E402
from pipelines.db import connect  # noqa: E402
from pipelines.paths import DATA_DIR  # noqa: E402

# A structural line is only recognised at brace-depth 0 (never inside a {...}
# marker), so "{Статтю 15 виключено ...}" or a multi-line header block cannot be
# mistaken for a real article/section start.
ARTICLE_RE = re.compile(r"^Стаття\s+(\d+(?:-\d+)?)\.\s*(.*)$")
# Roman (optionally hyphen/superscript-suffixed: VI-1 or VI1) or arabic. IGNORECASE:
# 1993-era editions write the header in caps (РОЗДІЛ) — case-sensitive matching
# missed them and slid the articles together.
SECTION_RE = re.compile(r"^Розділ\s+([IVXLCDM]+(?:-?\d+)?|\d+(?:-\d+)?)\.?\s*(.*)$",
                        re.IGNORECASE)
# Глава N — the primary structural unit of the codes (КУпАП, КК). Arabic with an optional
# Cyrillic-letter suffix (Глава 13-А), a HYPHENATED number (Глава 24-1), or ROMAN.
# Two fixes here, both measured:
#  · Roman — 2232-12 (військовий обов'язок) numbers all 15 of its chapters in Roman
#    («Глава XII», «Глава III1» = III¹, «ГЛАВА X1.»), so the arabic-only pattern matched
#    NONE of them: the act had 0 chapter units and its «Глава XII ПРИКІНЦЕВІ ПОЛОЖЕННЯ»
#    leaked into ст.45's body. Roman digits in Rada headings are LATIN (U+0049/U+0058/
#    U+0056) while the surrounding text is Cyrillic, so [IVXLCDM] is the right class.
#  · Hyphen — «Глава 24-1» used to capture only «24» (the suffix alternative accepted a
#    letter but not a digit), so it collided with the real Глава 24 and both КУпАП volumes
#    dedupe-suffixed it: розд.IV/гл.24~2 in 117 editions of 8073-10 + 74 of 80732-10.
#    The same trap as Розділ VI-1 vs VI1, repeating one level down.
GLAVA_RE = re.compile(
    r"^Глава\s+([IVXLCDM]+(?:-?\d+)?|\d+(?:-\d+|-?[А-ЯІЇЄҐ])?)\.?\s*(.*)$", re.IGNORECASE)
# A section written as a bare Roman ordinal — «I. Внести зміни…», «II. Прикінцеві та
# перехідні положення» (3633-IX, z1109-08). ONLY consulted for editions that carry no
# «Розділ» heading at all (see `_roman_sections`): in КУпАП «I. ЗАГАЛЬНА ЧАСТИНА» is a
# sub-heading INSIDE Розділ II, and treating it as a section would collide with the real
# розд.I and re-scope every chapter under it.
ROMAN_SECTION_RE = re.compile(r"^([IVXLCDMІХСМ]+(?:-?\d+)?)\.\s+(\S.*)$")
ROZDIL_ANY_RE = re.compile(r"^Розділ\s", re.IGNORECASE)
# A постанова КМУ carries no «Стаття»: it is its own numbered пункти, plus the documents
# it approves («ЗАТВЕРДЖЕНО … ПОРЯДОК …») and its annexes («Додаток N»). Each of those is a
# fresh «N.» numbering scope — 560-2024-п restarts at 1. three times over — so without them
# as stops the whole act collapsed into ONE preamble blob (a known v0 limit) and any point-first
# parse would have piled three separate «1.» runs onto one path. Laws use the same annex
# convention: 1404-19 ends with a bare, UNNUMBERED «Додаток» (its Перелік майна, 1.–13.),
# which is why that list collided with розд.XIII's own points.
ZATVERDZHENO_RE = re.compile(r"^ЗАТВЕРДЖЕН(?:О|А|І|ИЙ)\s*$", re.IGNORECASE)
DODATOK_RE = re.compile(r"^Додаток(?:\s+(\d+(?:-\d+)?))?\s*$", re.IGNORECASE)
POINT_RE = re.compile(r"^(\d+(?:-\d+)?)\.\s+(\S.*)$")
MARKER_RE = re.compile(r"\{[^{}]*\}", re.DOTALL)
DOCTYPE_RE = re.compile(r"^(ЗАКОН|КОДЕКС|КОНСТИТУЦІЯ|УКАЗ|ПОСТАНОВА|ДЕКРЕТ)\b", re.IGNORECASE)


# Cyrillic look-alikes of the Latin Roman digits. Rada mixes them INSIDE one numeral —
# z1109-08 renders «ХV» as Cyrillic Х (U+0425) + LATIN V, «ХІ» as Cyrillic Х + Cyrillic І
# (U+0406) — so 8 of its 38 Roman headings were invisible to [IVXLCDM] and their розділи
# merged into the previous one (дод.2/розд.IX swallowed X–XIII: 95 184 chars).
_ROMAN_HOMOGLYPH = str.maketrans({"І": "I", "Х": "X", "С": "C", "М": "M"})


def _norm_section(token: str) -> str:
    """Розділ 'VI1' or 'VI-1' -> 'VI-1' (superscript ¹ rendered as a trailing
    digit in TXT; some editions add the hyphen, some don't — unify them)."""
    # Fold Cyrillic homoglyphs ONLY when the whole token is a Roman numeral: a chapter
    # suffix like «13-А» carries a genuinely Cyrillic letter that must survive intact.
    if re.fullmatch(r"[IVXLCDMІХСМ]+(?:-?\d+)?", token):
        token = token.translate(_ROMAN_HOMOGLYPH)
    m = re.match(r"^([IVXLCDM]+)-?(\d+)$", token)
    return f"{m.group(1)}-{m.group(2)}" if m else token


def _article_num(raw: str, base: str | None) -> tuple[str, str | None]:
    """Disambiguate a collapsed superscript article by structural position, returning
    (display_number, new_base). Rada's TXT export drops the superscript: ст.15¹ → "151",
    ст.163¹⁰ → "16310". A purely-numeric number that extends the current plain base by
    1 OR 2 trailing digits (15→151, 163→16310) is that base's superscript → "15-1" /
    "163-10", base unchanged. Sequential legal numbering makes this unambiguous (a genuine
    art.151 follows 150, not 15). The old rule handled only a single superscript
    digit, so ст.163¹⁰…163¹⁸ (118 paths in the current КУпАП) were stored as ст.16310 AND
    reset the base to that long number, poisoning every article after them."""
    if "-" in raw:
        return raw, base                        # already hyphenated (ст.13-1); base kept
    if base and raw.startswith(base) and 1 <= len(raw) - len(base) <= 2:
        suffix = raw[len(base):]
        if suffix.isdigit() and suffix[0] != "0":  # superscript number, no leading zero
            return f"{base}-{int(suffix)}", base   # collapsed superscript; base unchanged
    # A plain article advances the base — UNLESS raw is implausibly long (≥4 digits): that
    # is an unattributed collapsed superscript (e.g. its base article was fully inside a
    # {…} marker). Store it verbatim but DON'T reset the base for the articles that follow.
    if len(raw) >= 4:
        return raw, base
    return raw, raw                             # plain article → advance the base


# Typographic variants that Rada's TXT export flips between editions (e.g. the
# apostrophe in обов'язок renders as U+2019 in one edition and U+0027 in the
# next). Canonicalising them keeps the stored text stable and stops a purely
# typographic swap from flagging every apostrophe-bearing unit as "changed".
_CANON = str.maketrans({
    "’": "'", "‘": "'", "ʼ": "'", "`": "'", "´": "'",
    "“": '"', "”": '"', "„": '"',
    " ": " ", " ": " ", " ": " ",
})


def _canon(s: str) -> str:
    return s.translate(_CANON)


def _markers(span: str) -> list[str]:
    """The {...} provenance spans in a text span, whitespace/typography-normalised."""
    return [_canon(re.sub(r"\s+", " ", m).strip()) for m in MARKER_RE.findall(span)]


def _clean(span: str) -> str:
    """Legal text: {...} markers removed, blank lines collapsed, typography canon."""
    no_markers = MARKER_RE.sub("", span)
    lines = [ln.rstrip() for ln in no_markers.split("\n")]
    return _canon("\n".join(ln for ln in lines if ln.strip()).strip())


def _start_depths(lines: list[str]) -> list[int]:
    """Brace-nesting depth at the START of each line (markers span newlines)."""
    depths, d = [], 0
    for ln in lines:
        depths.append(d)
        d = max(0, d + ln.count("{") - ln.count("}"))
    return depths


# An amendment that inserts articles INTO ANOTHER act is rendered as a quoted block:
#     є) доповнити статтями 121-3 і 121-4 такого змісту:
#     "Стаття 121-3. …      <- the leading " already keeps ARTICLE_RE from matching
#     Стаття 121-4. …       <- carries no quote of its own -> matched -> PHANTOM
# Only the FIRST heading of a multi-heading quote carries the quote, so every later one
# leaked in as a real article OF THE HOST ACT and — being the last "article" in the file —
# swallowed everything after it: 1404-19 ст.121-4 ate 59 556 chars of Прикінцеві положення
# (incl. the виконавче-провадження moratoria) and 3633-IX ст.27 ate 141 902.
# Quote PARITY cannot separate these: a line may close a quote it never opened, so the
# count desynchronises (measured: depth read 0 at the 1404-19 phantom). The span is tracked
# DIRECTIONALLY instead, and — critically — it opens ONLY on a quoted STRUCTURAL HEADING,
# never on any old line that happens to start with a quote.
#
# That narrowness is not fastidiousness, it is a measured bug fix. Opening on a bare leading
# quote wrecked z1109-08: its blank forms use the Ukrainian date convention
#     "___"_________ 20___ року одержав(ла) ______
# which opened a span that closed only ~1 700 lines later at some line ending in a quote
# (e.g. `Придатний за графами ТДВ "А"`). In 9 of its 24 editions that flagged 2 466 of 10 167
# lines (24 %) as "inside a quoted foreign act" and cut those editions to 48–49 units instead
# of ~250. z1109-08 contains no amendment quote at all. The opener below fires 0 times there,
# and exactly on the phantom-bearing blocks in 1404-19 (6/edition) and 3633-IX (22).
# A quoted block opens on a leading " in ONE of two situations, and never otherwise:
#  (a) the line is a quoted STRUCTURAL heading («"Стаття 121-3. …», «"Розділ VI1.») — the
#      phantom-generating shape itself;
#  (b) the PREVIOUS non-blank line is an amendment LEAD-IN — «… викласти в такій редакції:»,
#      «… доповнити статтями 121-3 і 121-4 такого змісту:» — i.e. Rada has just announced that
#      what follows is another act's text. This is what keeps the quoted частини («2. У разі
#      призначення штрафу…» of the КК) out of the host act's point list.
# The lead-in must be checked LOCALLY (previous line), not as a file-wide mode: z1109-08 does
# carry one such line, and a global switch would re-arm the loose opener across its forms.
_QUOTE_OPEN_RE = re.compile(r'^"(?:Стаття|Розділ|Глава|Додаток)\s', re.IGNORECASE)
_QUOTE_LEADIN_RE = re.compile(r"(такого змісту|такій редакції)\s*:$", re.IGNORECASE)
_QUOTE_CLOSE_RE = re.compile(r'"[;.,:]?$')


def _quote_depths(lines: list[str]) -> list[int]:
    """Amendment-quote depth (0 = act's own text, 1 = inside a quoted foreign act).

    A flag, not a counter: Rada does not nest these blocks."""
    depths, d = [], 0
    prev = ""                       # last non-blank, marker-stripped line
    for ln in lines:
        depths.append(d)
        s = MARKER_RE.sub("", ln).strip()
        if not s:
            continue
        if d == 0:
            opens = s.startswith('"') and (
                _QUOTE_OPEN_RE.match(s) or _QUOTE_LEADIN_RE.search(prev))
            # «"Стаття 27. Повноваження у сфері оборони";» opens AND closes on one line —
            # a one-line quote, not a block.
            if opens and not _QUOTE_CLOSE_RE.search(s):
                d = 1
        elif _QUOTE_CLOSE_RE.search(s):
            d = 0
        prev = s
    return depths


def _block_title(lines: list[str], start: int, end: int) -> str:
    """Heading of a ЗАТВЕРДЖЕНО / Додаток block — its first CAPTION line.

    Both are rendered as a stack of provenance lines before the real caption:
        Додаток 4              ЗАТВЕРДЖЕНО
        до Порядку             постановою Кабінету Міністрів України
        (в редакції …)         від 16 травня 2024 р. № 560
        ЗАЯВА          <-      ПОРЯДОК                <- the caption
    The provenance lines all start lowercase or with «(»; the caption is the first line
    opening with a capital — which is what makes «ЗАЯВА» (the відстрочка application form,
    the annex this corpus is built around) recoverable as a title, not buried in the body."""
    for j in range(start, end):
        s = lines[j].strip()
        if not s or s.startswith(("(", "{")) or DOCTYPE_RE.match(s):
            continue
        if s[:1].isupper():
            return s
    return ""


def _quote_eof_warn(lines: list[str]) -> str | None:
    """Fail-loud guard: an amendment-quote block that never closes.

    The failure mode is SILENT — every structural heading after the unclosed opener is
    suppressed, so the act quietly collapses toward one unit and no counter notices (this
    is exactly how the z1109-08 form-blank bug survived a "0 false positives" measurement).
    Depth at EOF must be 0. Corpus today: 0 editions trip this — it is a
    tripwire for the next source change, not a live finding."""
    depths = _quote_depths(lines)
    if not depths:
        return None
    # depth AT EOF = depth entering a hypothetical line after the last one
    tail = _quote_depths(lines + [""])[-1]
    if not tail:
        return None
    opener = next((i for i in range(len(lines) - 1, -1, -1)
                   if _QUOTE_OPEN_RE.match(MARKER_RE.sub("", lines[i]).strip())), None)
    where = f" (last quoted heading at line {opener + 1})" if opener is not None else ""
    return ("UNCLOSED amendment-quote block at EOF — every structural heading after it was "
            f"SUPPRESSED and the act's tail is silently merged{where}")


def _roman_sections(lines: list[str]) -> bool:
    """Whether bare Roman ordinals («II. Прикінцеві…») are this edition's section level.

    True only when the edition carries no «Розділ» heading at all. КУпАП has both — its
    «I. ЗАГАЛЬНА ЧАСТИНА» sits INSIDE Розділ II as a sub-heading, so honouring it there
    would duplicate розд.I and re-parent all 39 chapters (verified: 8073-10/80731-10 are
    the only acts carrying both, and this guard skips exactly them)."""
    return not any(ROZDIL_ANY_RE.match(ln) for ln in lines)


def _resolve_run(nums: list[str]) -> tuple[list[str], list[str | None]]:
    """Disambiguate a run of rendered numbers (points of one parent, or an edition's annexes).

    Returns (resolved, hints). `resolved` applies a rename ONLY when the positional evidence is
    corroborated; `hints[i]` carries the hyphenated form that base tracking PROPOSED but that
    was left unapplied, so a cross-edition twin can still corroborate it later (`reconcile_runs`).

    Why a bare adjacency is not enough (a review finding): base tracking fires on ONE
    adjacency, so a run «1., 11.» whose п.2–п.10 are absent — or rendered entirely inside {…}
    markers, hence invisible as bare «N.» — would turn a GENUINE п.11 into п.1-1. The guard:
    a collapsed reading is accepted only if the run RESUMES with a plain number afterwards
    (19 after 18-1; 67 after 66-1; п.11 after 10-14) — i.e. the suffix series is bracketed,
    not dangling at the edge of the run. Measured over all 1 198 in-force editions: every one
    of the 59 real renames is corroborated (56 also by a cross-edition twin, 3 by position
    alone), so this guard costs nothing today and closes the FP edge.
    """
    marks = []                       # [raw, proposed, advanced_base?]
    base: str | None = None
    for n in nums:
        disp, nb = _article_num(n, base)
        marks.append([n, disp, nb != base])
        base = nb
    resolved: list[str] = []
    hints: list[str | None] = []
    for i, (raw, disp, _adv) in enumerate(marks):
        if disp == raw:
            resolved.append(raw); hints.append(None); continue
        # positional corroboration: some LATER item is a plain number that advances the base
        continues = any(m[1] == m[0] and m[2] for m in marks[i + 1:])
        resolved.append(disp if continues else raw)
        hints.append(None if continues else disp)
    return resolved, hints


class Unit:
    __slots__ = ("path", "kind", "ordinal", "title", "text", "markers", "hint")

    def __init__(self, path, kind, ordinal, title, text, markers, hint=None):
        self.path, self.kind, self.ordinal = path, kind, ordinal
        # Hyphenated form proposed by base tracking but NOT applied for want of
        # positional corroboration; `reconcile_runs` may still apply it on a cross-edition twin.
        self.hint = hint
        # Canon titles too (section text == its title); _canon is idempotent so
        # re-applying to already-cleaned body text is a no-op.
        self.title = _canon(title) if title else title
        self.text = _canon(text)
        self.markers = markers

    def row(self, nreg, ed):
        return (nreg, ed, self.path, self.kind, self.ordinal, self.title or None,
                self.text, self.markers, len(self.text))


def _points(body: list[str], parent_path: str, start_ord: int) -> list[Unit]:
    """Numbered parts (N. ...) directly inside a parent unit's body.

    Brace-aware AND quote-aware: the numbered частини of an act QUOTED inside an
    amendment block are that act's, not ours — without the quote guard the
    Прикінцеві-положення span of 1404-19 contributed three separate "1./2./3." runs
    from the codes it amends, which is what produced the ~N duplicate paths.
    `parent_path` is the owning unit's path (ст.23, розд.XIII, розд.II/гл.5 …) so the
    same routine serves article-, section- and chapter-level points.

    Point numbers get the same collapsed-superscript disambiguation as articles,
    by walking the run IN DOCUMENT ORDER and tracking the base (`_article_num`). The
    positional evidence is what makes it safe AND is what separates the two meanings of
    the same rendered number: in 1404-19 розд.XIII the run reads 1, 11, 12 … 16, 2, 3 …
    10, 101 … 108, 11 — the FIRST «11» follows base 1 and is п.1¹, the LAST follows base
    10 (which «11» does not extend) and is the GENUINE п.11. Base tracking resolves both
    without a special case, and a number with no base in front of it is left alone."""
    depths = _start_depths(body)
    qdepths = _quote_depths(body)
    starts = [i for i, ln in enumerate(body)
              if depths[i] == 0 and not qdepths[i] and POINT_RE.match(ln)]
    nums, hints = _resolve_run([POINT_RE.match(body[i]).group(1) for i in starts])
    out: list[Unit] = []
    for k, i in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(body)
        span = "\n".join(body[i:end])
        out.append(Unit(f"{parent_path}/п.{nums[k]}", "point", start_ord + k,
                        None, _clean(span), _markers(span), hints[k]))
    return out


def parse_edition(text: str) -> list[Unit]:
    lines = text.split("\n")
    depths = _start_depths(lines)
    qdepths = _quote_depths(lines)
    roman_ok = _roman_sections(lines)

    def struct(i: int):
        if depths[i] != 0 or lines[i].lstrip().startswith("{"):
            return None
        if qdepths[i]:
            return None       # inside a quoted amendment: a FOREIGN act's heading
        if (m := ARTICLE_RE.match(lines[i])):
            return ("article", m)
        if (m := SECTION_RE.match(lines[i])):
            return ("section", m)
        if (m := GLAVA_RE.match(lines[i])):
            return ("chapter", m)
        if (m := DODATOK_RE.match(lines[i])):
            return ("annex", m)
        if (m := ZATVERDZHENO_RE.match(lines[i])):
            return ("approved", m)
        if roman_ok and (m := ROMAN_SECTION_RE.match(lines[i])):
            return ("section", m)
        return None

    stops = [(i, *s) for i in range(len(lines)) if (s := struct(i))]
    units: list[Unit] = []
    ordinal = 0

    # Preamble = everything before the first section/article.
    first = stops[0][0] if stops else len(lines)
    head = lines[:first]
    title = next((ln.strip() for ln in head[:4]
                  if ln.strip() and not DOCTYPE_RE.match(ln.strip())
                  and not ln.strip().startswith("(")), "")
    pre_text = _clean("\n".join(
        ln for ln in head
        if not ln.strip().startswith("(") and not DOCTYPE_RE.match(ln.strip())))
    if pre_text:
        ordinal += 1
        units.append(Unit("преамбула", "preamble", ordinal, title, pre_text,
                          _markers("\n".join(head))))
        # A постанова's own operative пункти live here — «1. Затвердити такі, що додаються:»
        # sits before the first ЗАТВЕРДЖЕНО block, i.e. inside the preamble span. They are
        # citable units, so the preamble carries points like any other parent.
        pre_pts = _points(head, "преамбула", ordinal + 1)
        ordinal += len(pre_pts)
        units.extend(pre_pts)

    base_art: str | None = None  # last plain article's raw number (superscript disambig)
    cur_section: str | None = None  # parent section, to scope chapter paths
    approved = 0                 # ordinal of the ЗАТВЕРДЖЕНО block within this edition
    scope = ""                   # «дод.2/» or «затв.1/» — the enclosing document, if any
    # The annex numbers form one run per edition and need the same look-ahead corroboration as
    # points, so they are resolved up front rather than as the stops loop walks past them.
    annex_nums, annex_hints = _resolve_run([m.group(1) for _i, kind, m in stops
                                            if kind == "annex" and m.group(1)])
    annex_seen = 0
    for k, (i, kind, m) in enumerate(stops):
        end = stops[k + 1][0] if k + 1 < len(stops) else len(lines)
        span_lines = lines[i:end]
        span = "\n".join(span_lines)
        if kind in ("section", "chapter"):
            if kind == "section":
                cur_section = _norm_section(m.group(1))
                path = f"{scope}розд.{cur_section}"
            else:
                # chapter numbers restart per section in some codes (КАС: Розділ I/
                # Глава 1, Розділ II/Глава 1…) → scope to the parent section so the
                # path is unique and deterministically sliceable.
                ch = _norm_section(m.group(1).upper())   # Roman «Глава III1» → гл.III-1
                path = (f"{scope}розд.{cur_section}/гл.{ch}" if cur_section
                        else f"{scope}гл.{ch}")
            title = m.group(2).strip() or next(
                (lines[j].strip() for j in range(i + 1, end) if lines[j].strip()), "")
            body = span_lines[1:]        # lines after the «Розділ X» / «Глава N» line
            # A v0 limit, now fixed: the body used to be DISCARDED — a section/chapter unit
            # stored its title as its text, so every розділ carrying content instead of
            # articles (Прикінцеві та перехідні положення: the виконавче-провадження
            # moratoria, поновлення строків) was silently dropped. Build the text exactly
            # the way an article does (heading + body): for a section that DOES contain
            # articles the span already ends at its first one, so this stays its title —
            # the change only materialises the bodies that were being thrown away.
            sec_text = _clean("\n".join([m.group(2), *body]))
            ordinal += 1
            units.append(Unit(path, kind, ordinal, title, sec_text, _markers(span)))
            pts = _points(body, path, ordinal + 1)   # розд.XIII/п.1 …
            ordinal += len(pts)
            units.extend(pts)
        elif kind in ("annex", "approved"):
            # A new top-level scope. Everything inside restarts its own numbering — z1109-08
            # carries TWO Розклад-хвороб annexes that each run «I.»…«XVIII.», so an unscoped
            # розд.I would be three different things — hence the scoping.
            cur_section = None
            hint = None
            if kind == "annex":
                num = m.group(1)
                if num:
                    # Same collapsed-superscript trap one level up: 560-2024-п runs
                    # Додаток 1, 1¹, 2 … 10, 11, 12 … and the TXT renders 1¹ as «Додаток 11»,
                    # colliding with the genuine Додаток 11 — two DIFFERENT annexes on one path
                    # (СЛУЖБОВЕ ПОСВІДЧЕННЯ vs НАПРАВЛЕННЯ). The run is resolved up front, with
                    # the same positional corroboration the points get.
                    num, hint = annex_nums[annex_seen], annex_hints[annex_seen]
                    annex_seen += 1
                path = f"дод.{num}" if num else "додаток"
            else:
                approved += 1
                path = f"затв.{approved}"
            scope = f"{path}/"
            title = _block_title(lines, i + 1, end)
            body = span_lines[1:]
            ordinal += 1
            units.append(Unit(path, kind, ordinal, title, _clean("\n".join(body)),
                              _markers(span), hint))
            pts = _points(body, path, ordinal + 1)   # дод.5/п.1 · затв.1/п.4 …
            ordinal += len(pts)
            units.extend(pts)
        else:  # article
            art_num, base_art = _article_num(m.group(1), base_art)
            heading = _clean(m.group(2))          # short heading (marker-free)
            body = span_lines[1:]                 # lines after "Стаття N. ..."
            # Article text = heading + body, so the heading is retrievable AND
            # single-line articles (1993 original writes the whole article on the
            # "Стаття N." line) keep their content instead of an empty body.
            art_text = _clean("\n".join([m.group(2), *body]))
            ordinal += 1
            units.append(Unit(f"ст.{art_num}", "article", ordinal, heading,
                              art_text, _markers(span)))
            pts = _points(body, f"ст.{art_num}", ordinal + 1)
            ordinal += len(pts)
            units.extend(pts)
    _fix_superscript_runs(units)   # base-absent (виключено) superscript runs
    return units


_PLAIN_ART_RE = re.compile(r"^ст\.(\d+)$")


def _fix_superscript_runs(units: list[Unit]) -> int:
    """Post-pass: rewrite runs of collapsed superscript articles whose BASE
    article is ABSENT from the edition (виключено), which `_article_num` can't track
    line-by-line (it never sees a plain ст.166 to set the base). A run is a sequence of
    plain-numeric article paths base·1, base·2, base·3 … (starting at superscript ¹).

    Guard against genuine multi-digit articles (e.g. ЦК ст.1301…1308): convert ONLY when
    ст.{base} is NOT present in this edition. A real code always carries its base article
    (ст.130 exists → 1301 is genuine art. 1301, left alone); when the base IS present the
    per-line heuristic already split the superscripts, so there is nothing left to fix.
    Returns the number of paths rewritten."""
    arts = [u for u in units if u.kind == "article"]
    present = {u.path for u in arts}
    nums = [(_PLAIN_ART_RE.match(u.path), u) for u in arts]
    n = 0
    i = 0
    while i < len(nums):
        m, _ = nums[i]
        if not m or len(m.group(1)) < 2:
            i += 1
            continue
        d = m.group(1)
        base = d[:-1]
        if d[len(base):] != "1" or f"ст.{base}" in present:
            i += 1                                   # not a base¹ start, or base exists
            continue
        run = [i]
        expect, j = 2, i + 1
        while j < len(nums):
            mj, _ = nums[j]
            if mj and mj.group(1).startswith(base) and mj.group(1)[len(base):] == str(expect):
                run.append(j)
                expect += 1
                j += 1
            else:
                break
        if len(run) >= 2:
            for k, idx in enumerate(run, start=1):
                nums[idx][1].path = f"ст.{base}-{k}"
            n += len(run)
            i = j
        else:
            i += 1
    return n


_ART_BASE_RE = re.compile(r"^ст\.(\d+)(-.*)?$")
_GENUINE_GAP = 200  # a jump larger than this above the dense article cluster = collapsed


def genuine_max(article_paths) -> int:
    """Largest legit article NUMBER of an act. Walk the article base numbers
    ascending from the low, dense, near-contiguous genuine cluster; the first gap wider
    than _GENUINE_GAP marks where collapsed superscripts (ст.861, ст.1214 …) sit far above.
    Hyphenated bases (ст.86-1 → 86) count as genuine bases, so this is robust to the highest
    articles carrying superscripts (or not)."""
    bases = sorted({int(m.group(1)) for p in article_paths
                    if (m := _ART_BASE_RE.match(p))})
    top = 0
    for n in bases:
        if top == 0 or n - top <= _GENUINE_GAP:
            top = n
        else:
            break
    return top


def _expand_collapsed(num: int, tail: str, gmax: int, known: set[str]) -> str | None:
    """A plain/base article number > gmax is a collapsed superscript. Split it as base·suffix
    (1 then 2 trailing digits) where base ≤ gmax. For a plain path require the expanded path
    (or its base) to EXIST elsewhere in the act (cross-edition twin) — unambiguous. A compound
    path ст.NNNN-M (tail set, e.g. 1729-1 → 172-9-1) is expanded deterministically."""
    for k in (10, 100):
        base, suffix = num // k, num % k
        if suffix >= 1 and 1 <= base <= gmax:
            cand = f"ст.{base}-{suffix}{tail}"
            if tail:
                return cand
            if (cand in known) or (f"ст.{base}-{suffix}" in known) or (f"ст.{base}" in known):
                return cand
    return None


_POINT_RE = re.compile(r"^ст\.(\d+)(-\d+)?/п\.(\d+)(-\d+)?$")


def _reconcile_point(path: str, gmax: int, known: set[str]) -> str | None:
    """A point path ст.X/п.Y where the ARTICLE prefix is a
    collapsed superscript (ст.1214/п.*) and/or the POINT number is collapsed (п.101 = п.10¹)
    → rewrite to ст.121-4/п.10-1, using the cross-edition twin (the correct form exists in
    the act's other editions). Only converts when the resulting path EXISTS in `known` —
    unambiguous, never corrupts a genuine point."""
    m = _POINT_RE.match(path)
    if not m:
        return None
    art_num, art_tail = int(m.group(1)), (m.group(2) or "")
    pt, pt_tail = int(m.group(3)), (m.group(4) or "")
    # fix the article prefix if it is a collapsed superscript
    art_str = f"ст.{art_num}{art_tail}"
    if art_num > gmax:
        art_str = _expand_collapsed(art_num, art_tail, gmax, known) or art_str
    # keep the point number if the (prefix-fixed) path already exists; else expand the point
    # number via its cross-edition twin (base·suffix where the hyphenated form is known).
    base_cand = f"{art_str}/п.{pt}{pt_tail}"
    if base_cand in known:
        return base_cand if base_cand != path else None
    for k in (10, 100):
        b, s = pt // k, pt % k
        if s >= 1 and b >= 1:
            cand = f"{art_str}/п.{b}-{s}{pt_tail}"
            if cand in known:
                return cand
    # Family-bracket fallback: no exact twin, but if base b has an established
    # hyphenated point-family in the act (≥2 members) and the suffix s is within its observed
    # range, the collapsed п.{b}{s} is that superscript (п.1013 → п.10-13, bracketed by 12/14).
    for k in (10, 100):
        b, s = pt // k, pt % k
        if s < 1 or b < 1:
            continue
        fam = [int(mm.group(1)) for kp in known
               if (mm := re.match(rf"^{re.escape(art_str)}/п\.{b}-(\d+)$", kp))]
        if len(fam) >= 2 and 1 <= s <= max(fam):
            return f"{art_str}/п.{b}-{s}{pt_tail}"
    # article prefix changed but the point number had no twin — still fix the prefix.
    return base_cand if art_str != f"ст.{art_num}{art_tail}" else None


def reconcile_collapsed(editions: list, gmax: int, known: set[str]) -> int:
    """Cross-edition pass: rewrite collapsed superscripts that a single edition
    could not resolve (base article виключено), using genuine_max + the union of the act's
    real article/point paths. Fixes the harm class — the SAME article (or point) under two
    paths across editions (ст.86-1 vs ст.861; ст.121-4/п.10-1 vs ст.1214/п.101). `editions`
    = list of (ed, units). Returns #rewritten."""
    n = 0
    for _ed, units in editions:
        for u in units:
            new = None
            if u.kind == "article":
                m = _ART_BASE_RE.match(u.path)
                if m and int(m.group(1)) > gmax:
                    new = _expand_collapsed(int(m.group(1)), m.group(2) or "", gmax, known)
            elif u.kind == "point":
                new = _reconcile_point(u.path, gmax, known)
            if new and new != u.path:
                u.path = new
                n += 1
    return n


def reconcile_runs(editions: list, known: set[str]) -> int:
    """Cross-edition TWIN corroboration for collapsed point/annex numbers.

    The positional guard in `_resolve_run` is deliberately conservative: it declines a rename
    whose suffix series dangles at the end of a run. That is the right default, but it would
    also decline a REAL case — a розділ whose tail is «… 10, 101, 102» (EOF) while the act's
    other editions render 10-1 / 10-2. This pass rescues exactly those: it applies the hint
    when the hyphenated form exists elsewhere in the act.

    It acts ONLY on units carrying a `hint`, i.e. on numbers base tracking already identified
    as collapsed CANDIDATES. That scoping is load-bearing, not tidiness: `known` legitimately
    contains п.1-1, so a twin check applied to every plain number would rename the GENUINE
    п.11 of 1404-19 (whose twin п.1-1 exists) and recreate the very collision this removed.
    `editions` = [(ed, units)]. Returns #rewritten.
    """
    n = 0
    for _ed, units in editions:
        for u in units:
            if not u.hint:
                continue
            prefix = u.path[:u.path.rindex(".") + 1]     # «розд.XIII/п.» or «дод.»
            cand = f"{prefix}{u.hint}"
            if cand in known and cand != u.path:
                u.path = cand
                n += 1
    return n


def _dedupe(units: list[Unit]) -> int:
    """Suffix any duplicate unit_path within one edition (parser-quirk guard);
    keeps every unit rather than crashing on the PK. Returns #collisions.

    The canonical path goes to the SUBSTANTIVE unit. Rada renders a repeal as a
    heading whose whole body is a {…} marker: «Стаття 163. {Статтю 163 виключено на
    підставі Закону № 2342-III від 05.04.2001}». Once the marker is stripped that husk is
    empty, and КУпАП carries BOTH it and the live, re-issued «Стаття 163. Розміщення
    цінних паперів…». Suffixing in plain document order let the EMPTY husk keep `ст.163`
    and pushed the live article (694 chars) onto `ст.163~2` — a live administrative-offence
    article addressable only at a dedup artefact. Ordering non-empty first fixes that; the
    husk is kept (it carries the repeal provenance), just not on the canonical path.
    Ties (all empty or all substantive) keep document order, so the pass stays deterministic.
    """
    groups: dict[str, list[Unit]] = {}
    for u in units:
        groups.setdefault(u.path, []).append(u)
    dups = 0
    for path, group in groups.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda u: (not u.text, u.ordinal))   # substantive first, then order
        for n, u in enumerate(group[1:], start=2):
            u.path = f"{path}~{n}"
            dups += 1
    return dups


def _section_warn(text: str, units: list[Unit]) -> str | None:
    """Warn if the edition clearly has sections we failed to parse:
    no section units but >1 line begins with 'Розділ' (any case)."""
    if any(u.kind == "section" for u in units):
        return None
    rozdil = sum(1 for ln in text.split("\n")
                 if re.match(r"^\s*розділ\b", ln, re.IGNORECASE))
    return (f"0 sections parsed but {rozdil} 'Розділ' lines — check SECTION_RE"
            if rozdil > 1 else None)


def _write(conn, nreg: str, ed, units: list[Unit]) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM units WHERE act_nreg = %s AND edition_date = %s",
                    (nreg, ed))
        cur.executemany(
            "INSERT INTO units (act_nreg, edition_date, unit_path, kind, ordinal, "
            "title, text, inline_markers, char_len) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [u.row(nreg, ed) for u in units])
    conn.commit()


def _editions(conn, nreg: str, which: str) -> list[tuple]:
    # units materialize IN-FORCE + historical editions only. Rada publishes scheduled
    # amendments dated in the future (3000/2027/2030…); parsing them would let any
    # latest-edition selector serve a not-yet-in-force text as the current law — the
    # exact risk that a design review flagged. So both "current" and the default "all"
    # exclude edition_date > today. An explicit YYYYMMDD can still target any single
    # edition (deliberate dev override).
    # Deliberate: CURRENT_DATE is the Postgres server TZ = Etc/UTC, not Europe/Kyiv.
    # Direction is fail-safe (never includes a future edition); worst case an edition enacted
    # "today Kyiv" is excluded for the 00:00–03:00 Kyiv window. Accepted.
    explicit = bool(re.fullmatch(r"\d{8}", which or ""))
    in_force = "" if explicit else "AND edition_date <= CURRENT_DATE"
    with conn.cursor() as cur:
        cur.execute(
            "SELECT edition_date, txt_path FROM editions "
            f"WHERE act_nreg = %s AND txt_path IS NOT NULL {in_force} "
            "ORDER BY edition_date DESC",
            (nreg,))
        rows = cur.fetchall()
    if which == "current":
        return rows[:1]
    if explicit:
        want = f"{which[:4]}-{which[4:6]}-{which[6:]}"
        return [r for r in rows if r[0].isoformat() == want]
    return rows


def main() -> int:
    from pipelines.orchestration import warn_if_standalone
    warn_if_standalone("A-03b (rada.parse_structure)")  # loud unless orchestrated
    ap = argparse.ArgumentParser(description="Parse Rada edition TXT into units (T4 v0)")
    ap.add_argument("acts", nargs="*", help="act nreg(s); empty with --all = all acts")
    ap.add_argument("--all", action="store_true", help="every act that has txt")
    ap.add_argument("--editions", default="all",
                    help="all | current | YYYYMMDD (default all)")
    ap.add_argument("--current", action="store_true", help="alias for --editions current")
    args = ap.parse_args()
    which = "current" if args.current else args.editions

    grand_units = grand_eds = 0
    quote_eof_bad: list[str] = []   # editions whose amendment quote never closes
    try:
        with connect() as conn:
            acts = list(args.acts)
            if args.all or not acts:
                with conn.cursor() as cur:
                    cur.execute("SELECT DISTINCT act_nreg FROM editions "
                                "WHERE txt_path IS NOT NULL ORDER BY act_nreg")
                    acts = [r[0] for r in cur.fetchall()]

            for nreg in acts:
                eds = _editions(conn, nreg, which)
                if not eds:
                    print(f"  {nreg}: no matching editions with txt"); continue
                # Parse ALL of the act's editions first, then reconcile collapsed superscripts
                # cross-edition (needs the union of real article paths + the act's genuine max).
                parsed: list = []
                warns: list = []
                for ed, txt_path in eds:
                    text = (DATA_DIR / txt_path).read_text(encoding="utf-8")
                    units = parse_edition(text)
                    if (w := _section_warn(text, units)):
                        warns.append(f"  ! {nreg} {ed}: {w}")
                    if (w := _quote_eof_warn(text.split("\n"))):
                        warns.append(f"  !! {nreg} {ed}: {w}")
                        quote_eof_bad.append(f"{nreg}@{ed}")
                    parsed.append((ed, units))
                known_art = {u.path for _e, us in parsed for u in us if u.kind == "article"}
                # genuine_max from ARTICLE paths only; the twin set includes POINT paths too so
                # ст.121-4/п.10-1 (in other editions) can reconcile a collapsed ст.1214/п.101.
                known = {u.path for _e, us in parsed for u in us if u.kind in ("article", "point")}
                gmax = genuine_max(known_art)
                if (r := reconcile_collapsed(parsed, gmax, known)):
                    print(f"  ~ {nreg}: reconciled {r} collapsed superscript path(s) "
                          f"cross-edition (genuine max ст.{gmax})")
                # point/annex numbers whose positional evidence dangled at the end of
                # a run — rescue them only on a cross-edition hyphenated twin.
                known_pt = {u.path for _e, us in parsed for u in us
                            if u.kind in ("point", "annex")}
                if (r := reconcile_runs(parsed, known_pt)):
                    print(f"  ~ {nreg}: {r} collapsed point/annex number(s) reconciled by "
                          f"cross-edition twin (no positional continuation)")
                arts_last = 0
                for w in warns:
                    print(w)
                for ed, units in parsed:
                    if (d := _dedupe(units)):
                        print(f"  ! {nreg} {ed}: {d} duplicate unit_path(s) suffixed")
                    _write(conn, nreg, ed, units)
                    grand_units += len(units); grand_eds += 1
                    arts_last = sum(1 for u in units if u.kind == "article")
                kinds = {}
                with conn.cursor() as cur:
                    cur.execute("SELECT kind, count(*) FROM units WHERE act_nreg=%s "
                                "GROUP BY kind", (nreg,))
                    kinds = dict(cur.fetchall())
                print(f"  {nreg:12s} editions={len(eds):3d}  latest: articles={arts_last} "
                      f"| totals {dict(sorted(kinds.items()))}")
    except Exception:
        # Even a mid-parse crash emits an honest COLLECT-SUMMARY (partial ok + failed=1) so the
        # orchestrator journals real partial counts, not 'unmeasured'; then re-raise so the
        # subprocess still exits non-zero.
        _summary.emit(ok=grand_eds, failed=1, nbytes=0)
        raise

    print(f"\nDONE: parsed {grand_eds} editions → {grand_units} units.")
    if quote_eof_bad:
        # RED, not a warning. An unclosed quote silently eats the tail of an act, and the
        # counters cannot see it — the only honest signal is a failed run.
        print(f"\n!! UNCLOSED amendment-quote at EOF in {len(quote_eof_bad)} edition(s): "
              f"{quote_eof_bad[:10]}\n   Their structural tail is suppressed — parse is NOT "
              f"trustworthy for them. Fix _quote_depths before trusting these units.")
        _summary.emit(ok=grand_eds - len(quote_eof_bad), failed=len(quote_eof_bad), nbytes=0)
        return 1
    # Honest counts for the orchestrator. Derived transform — no wire bytes.
    _summary.emit(ok=grand_eds, failed=0, nbytes=0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
