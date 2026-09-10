"""Eval data schema (pydantic).

`EvalQuestion` is the gold-standard record. The harvester only collects questions
and drafts a selection tagged `[CLAIM]` with EMPTY gold: `gold_citations` and
`gold_key_points` (the reference answers) are written, and `validated` flipped, in
a separate review pass — never by the model under evaluation, because an eval must
not grade itself. `FaqItem` is a raw harvested Q&A; `RunResult` is one runner
output row.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class FaqItem(BaseModel):
    """One raw Q&A pair harvested from a public FAQ."""

    category: str | None = None
    question: str
    answer: str
    source: str
    source_url: str


class EvalQuestion(BaseModel):
    """A gold-standard eval record. Gold fields stay empty until review validates them."""

    id: str
    question: str
    persona: str | None = None          # who is asking (e.g. «мобілізований громадянин»)
    as_of_date: str | None = None       # legal state date (edition temporality), set in review
    category: str | None = None
    source: str                         # e.g. "army.gov.ua/qa"
    source_url: str | None = None
    derived_from: str | None = None     # provenance of the gold once written
    gold_citations: list[str] = Field(default_factory=list)    # reference answer — review only
    gold_key_points: list[str] = Field(default_factory=list)   # reference answer — review only
    validated: bool = False             # validated in review?
    tag: str = "[CLAIM]"                # evidence tag: a claim until validated


class RunResult(BaseModel):
    """One runner row: the model's answer to a question + stub metrics."""

    question_id: str
    question: str
    model: str
    answer: str
    citations: list[str] = Field(default_factory=list)
    abstain: bool = False
    has_article_ref: bool = False       # stub metric: any «ст./стаття N» in answer|citations
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hit_tokens: int = 0
    backend: str = "deepseek"           # deepseek | local | stub
    run_at: str = ""                    # ISO timestamp (passed in; no clock in library code)
