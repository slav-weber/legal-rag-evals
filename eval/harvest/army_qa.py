"""Harvest the public army.gov.ua/qa FAQ into eval questions.

The page is server-rendered: 193 `faq-item` blocks (each a `faq-toggle` question +
a `faq-answer` answer) grouped under `faq-category` headers. We parse them into
eval/data/questions_raw.jsonl (full Q&A), then draft a ~40-question selection about
the headline topics (штрафи ТЦК / повістки / відстрочки / військовий облік) into
eval/data/questions_v0.jsonl — each tagged [CLAIM] with EMPTY gold. Finalising the
selection and writing the gold reference answers is a separate review job, never
the model's.

Run:  uv run python -m eval.harvest.army_qa
"""

from __future__ import annotations

import hashlib
import html
import sys
from html.parser import HTMLParser
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

from eval.schema import EvalQuestion, FaqItem  # noqa: E402

URL = "https://army.gov.ua/qa/"
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
VOID = {"br", "img", "input", "hr", "meta", "link", "source", "area", "base",
        "col", "embed", "param", "track", "wbr"}
# Headline-topic selection heuristic (question text, lowercased).
KEYWORDS = ["штраф", "тцк", "повістк", "повестк", "відстрочк", "мобіліз", "оскарж",
            "облік", "влк", "бронюв", "210", "ухилен", "розшук", "сзч", "призов",
            "адмінправопоруш", "постанов"]


class FaqParser(HTMLParser):
    """Collect (category, question, answer) triples, tracking element depth so
    nested tags (svg/p/a) inside a toggle/answer don't close it early."""

    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str | None, str, str]] = []
        self.category: str | None = None
        self.mode: str | None = None
        self.depth = 0
        self.buf: list[str] = []
        self._q: str | None = None

    def handle_startendtag(self, tag, attrs):
        # A self-closing tag (<br/>, <img/>) is balanced — it must NEVER change depth.
        # The HTMLParser default routes it to starttag+endtag, and since void tags skip
        # the increment but not the decrement, depth drifted negative and closed the
        # block early. A no-op is the correct override.
        pass

    def handle_starttag(self, tag, attrs):
        if self.mode:
            if tag not in VOID:
                self.depth += 1
            return
        cls = dict(attrs).get("class", "") or ""
        # NB: faq-category is a CONTAINER wrapping the items, not a header — do not
        # capture it (it would swallow every nested Q&A). Category is dropped in v0.
        if "faq-toggle" in cls:
            self.mode, self.depth, self.buf = "question", 1, []
        elif "faq-answer" in cls:
            self.mode, self.depth, self.buf = "answer", 1, []

    def handle_endtag(self, tag):
        if not self.mode or tag in VOID:  # void endtags don't balance a depth increment
            return
        self.depth -= 1
        if self.depth > 0:
            return
        text = html.unescape(" ".join("".join(self.buf).split())).strip()
        if self.mode == "category":
            self.category = text
        elif self.mode == "question":
            self._q = text
        elif self.mode == "answer" and self._q:
            self.items.append((self.category, self._q, text))
            self._q = None
        self.mode, self.buf = None, []

    def handle_data(self, data):
        if self.mode:
            self.buf.append(data)


RAW_HTML = DATA_DIR / "army_qa_raw.html"


def harvest(html_text: str | None = None) -> list[FaqItem]:
    """Parse the FAQ into items. With ``html_text`` (or a saved snapshot) the run is
    reproducible; otherwise fetch live AND persist the raw HTML + sha256 as the source
    of truth, so the corpus survives the page migrating again."""
    if html_text is None:
        r = httpx.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30,
                      follow_redirects=True)
        r.raise_for_status()
        html_text = r.text
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        RAW_HTML.write_text(html_text, encoding="utf-8")
        sha = hashlib.sha256(html_text.encode("utf-8")).hexdigest()
        (DATA_DIR / "army_qa_raw.sha256").write_text(sha, encoding="utf-8")
        print(f"  saved raw HTML {len(html_text)} B sha256={sha[:16]}… "
              f"(final url {r.url}) → {RAW_HTML.name}")
    p = FaqParser()
    p.feed(html_text)
    items = [FaqItem(category=c, question=q, answer=a, source="army.gov.ua/qa",
                     source_url=URL) for c, q, a in p.items if q and a]
    if not items:
        print("  ! 0 FAQ items parsed — the page likely migrated (301). Re-validate the "
              "faq-toggle/faq-answer selectors against the saved army_qa_raw.html.")
    return items


def select(items: list[FaqItem], want: int = 42) -> list[EvalQuestion]:
    """Draft selection about the headline topics. [CLAIM], empty gold — review finalises."""
    chosen, seen = [], set()
    for it in items:
        low = it.question.lower()
        if any(k in low for k in KEYWORDS) and it.question not in seen:
            seen.add(it.question)
            chosen.append(it)
    # If the heuristic under-shoots, top up with remaining items to reach the floor.
    if len(chosen) < want:
        for it in items:
            if it.question not in seen:
                seen.add(it.question)
                chosen.append(it)
            if len(chosen) >= want:
                break
    out = []
    for i, it in enumerate(chosen[:want], 1):
        out.append(EvalQuestion(
            id=f"army-{i:03d}", question=it.question, category=it.category,
            source=it.source, source_url=it.source_url,
            tag="[CLAIM]", validated=False))  # gold stays EMPTY — review writes the references
    return out


def _dump(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(row.model_dump_json() + "\n")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Harvest army.gov.ua/qa into eval questions")
    ap.add_argument("--snapshot", action="store_true",
                    help="parse the saved army_qa_raw.html (reproducible, offline)")
    args = ap.parse_args()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if args.snapshot and RAW_HTML.exists():
        items = harvest(RAW_HTML.read_text(encoding="utf-8"))
    else:
        items = harvest()
    _dump(DATA_DIR / "questions_raw.jsonl", items)
    print(f"harvested {len(items)} FAQ Q&A → questions_raw.jsonl")
    picks = select(items)
    _dump(DATA_DIR / "questions_v0.jsonl", picks)
    kw_hits = sum(1 for p in picks if any(k in p.question.lower() for k in KEYWORDS))
    print(f"selected {len(picks)} questions → questions_v0.jsonl "
          f"([CLAIM], empty gold; {kw_hits} keyword-matched, rest top-up)")
    cats = {}
    for p in picks:
        cats[p.category] = cats.get(p.category, 0) + 1
    print("by category:", dict(sorted(cats.items(), key=lambda x: -x[1])))
    return 0 if len(picks) >= 40 else 1


if __name__ == "__main__":
    raise SystemExit(main())
