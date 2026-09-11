"""Retrieval: temporal scope-gate, three candidate channels, RRF fusion, cross-encoder rerank.

The retriever was built layer by layer, each layer added only after it showed a measurable recall
gain on the reference questions: scope-gate → dense baseline → FTS/lemma channels → RRF merge →
reranker.

**Scope-gate FIRST**: every candidate is filtered by "edition in force on `as_of`" BEFORE scoring —
never serve a not-yet-in-force edition, never spend budget on an invalid one. In v0 the gate is
near-trivial (all 4 706 chunks are currently in force, 0 future), so a live run filters nothing;
correctness is proven by a FIXTURE (an expired and a future row must both drop), not by a run where
there is nothing to drop.

Dense uses the embedding index (`embeddings ⋈ chunks_indexable`, model-pinned). The query gets the
`query: ` prefix (embed_query, ephemeral — never cached). Containers (606) are OUT of
chunks_indexable; the with/without-containers recall re-check is an acceptance item that needs the
reference questions.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# «today» is Europe/Kyiv, computed in the DB (the container's Postgres runs Etc/UTC) — same rule
# the chunk layer uses; a NULL as_of falls back to it via COALESCE.
_TODAY_KYIV = "(now() AT TIME ZONE 'Europe/Kyiv')::date"


def scope_clause(alias: str = "") -> str:
    """SQL predicate "edition in force on `as_of`" for a row with in_force_from/in_force_to.

    Takes a single named param `%(as_of)s` (a date or None); NULL → today Kyiv. The SAME clause is
    reused by every future channel (FTS/lemma) so the gate is one writer, not three copies."""
    p = f"{alias}." if alias else ""
    aod = f"COALESCE(%(as_of)s::date, {_TODAY_KYIV})"
    return (f"{p}in_force_from <= {aod} "
            f"AND ({p}in_force_to IS NULL OR {p}in_force_to >= {aod})")


def dense(conn, query_text: str, as_of=None, k: int = 10, model: str | None = None,
          source: str = "chunks_indexable") -> list[dict]:
    """Top-k dense neighbours over the SCOPE-GATED indexable set, by cosine distance.

    Returns richest-first dicts: content_hash, act, unit_path, citation, in_force_from/to, dist.
    Needs LM Studio (query embedding) — the caller handles unavailability (R-10 discipline).
    `source` is a controlled table/view name (default `chunks_indexable`); the containers
    measurement passes `chunks` to score WITH the 606 containers included — NOT user input, never
    interpolated from a query."""
    from ml.embed_index import _model, embed_query
    model = model or _model()
    qvec = embed_query(query_text)[0]
    lit = "[" + ",".join(repr(x) for x in qvec) + "]"
    sql = (
        "SELECT ci.content_hash, ci.act_nreg, ci.unit_path, ci.citation, ci.in_force_from, "
        "       ci.in_force_to, e.embedding <=> %(q)s::vector AS dist "
        f"FROM {source} ci "
        "JOIN embeddings e ON e.model = %(model)s AND e.text_hash = ci.content_hash "
        f"WHERE {scope_clause('ci')} "
        "ORDER BY e.embedding <=> %(q)s::vector LIMIT %(k)s")
    with conn.cursor() as cur:
        cur.execute(sql, {"q": lit, "model": model, "k": k, "as_of": as_of})
        rows = cur.fetchall()
    return [{"content_hash": h, "act": a, "unit_path": p, "citation": c, "in_force_from": f,
             "in_force_to": t, "dist": float(d)} for h, a, p, c, f, t, d in rows]


def fts(conn, query_text: str, as_of=None, k: int = 10) -> list[dict]:
    """Top-k full-text candidates over the SCOPE-GATED indexable set. `simple` config (no stemming,
    by decision; morphology and special tokens are the lemma channel's job).
    `websearch_to_tsquery` gives phrase/position; `ts_rank_cd` (cover density) ranks. NO LM Studio —
    pure text search. Row shape mirrors dense() but carries `rank` (higher = better) instead of
    `dist`; RRF fuses BY RANK, so the scale difference is moot.

    ⚠ `simple` splits «283-2» into «283» + «-2» (dash boundary) — an exact special-token match is
    NOT this channel's strength; that is the lemma channel. FTS and lemma are complementary, not
    redundant."""
    sql = (
        "SELECT ci.content_hash, ci.act_nreg, ci.unit_path, ci.citation, ci.in_force_from, "
        "       ci.in_force_to, ts_rank_cd(ci.text_tsv, q) AS rank "
        "FROM chunks_indexable ci, websearch_to_tsquery('simple', %(query)s) q "
        f"WHERE {scope_clause('ci')} AND ci.text_tsv @@ q "
        "ORDER BY rank DESC LIMIT %(k)s")
    with conn.cursor() as cur:
        cur.execute(sql, {"query": query_text, "k": k, "as_of": as_of})
        rows = cur.fetchall()
    return [{"content_hash": h, "act": a, "unit_path": p, "citation": c, "in_force_from": f,
             "in_force_to": t, "rank": float(r)} for h, a, p, c, f, t, r in rows]


def lemma(conn, query_text: str, as_of=None, k: int = 10) -> list[dict]:
    """Top-k lemma-matched candidates over the SCOPE-GATED indexable set, MORPHOLOGY ONLY. The
    query is lemmatised the SAME way the index was (ml.lemma_index.lemmatize — one writer), so
    «відстрочку» matches «відстрочка» that `simple`-FTS missed. `lemma_cache` is joined by
    content_hash for the CURRENT PIPELINE_VERSION; NO LM Studio.

    Part B (special tokens) is deferred — v0 catches morphology, which is where the measured need
    is (the FTS channel scored 1/5 on it)."""
    from ml.lemma_index import PIPELINE_VERSION, lemmatize
    lq = lemmatize(query_text)
    sql = (
        "SELECT ci.content_hash, ci.act_nreg, ci.unit_path, ci.citation, ci.in_force_from, "
        "       ci.in_force_to, ts_rank_cd(l.lemma_tsv, q) AS rank "
        "FROM chunks_indexable ci "
        "JOIN lemma_cache l ON l.content_hash = ci.content_hash AND l.pipeline_version = %(pv)s, "
        "     websearch_to_tsquery('simple', %(lq)s) q "
        f"WHERE {scope_clause('ci')} AND l.lemma_tsv @@ q "
        "ORDER BY rank DESC LIMIT %(k)s")
    with conn.cursor() as cur:
        cur.execute(sql, {"lq": lq, "pv": PIPELINE_VERSION, "k": k, "as_of": as_of})
        rows = cur.fetchall()
    return [{"content_hash": h, "act": a, "unit_path": p, "citation": c, "in_force_from": f,
             "in_force_to": t, "rank": float(r)} for h, a, p, c, f, t, r in rows]


# ── RRF fusion (rank fusion in memory; no schema, no cache) ─────────────────────────────────────
# Config in .env: the defaults started out equal — calibration constants are configuration, never
# hardcoded at a call site.
# k=60 is the standard RRF constant; top-N per channel bounds each channel's candidate set.
CHANNELS = ("dense", "fts", "lemma")


def _rrf_k() -> int:
    return int(os.getenv("RRF_K", "60"))


def _rrf_topn() -> int:
    return int(os.getenv("RRF_TOPN", "50"))


# Calibrated CANON: DENSE=2.0 / FTS=0.5 / LEMMA=0.5 restores dense-parity p@1 on the reference
# questions — correlated fts+lemma share the weight (measured in an ablation, closed here). These
# are the OPERATIVE defaults (a measured calibration, not a smoke-test guess); .env overrides them.
_WEIGHT_CANON = {"dense": "2.0", "fts": "0.5", "lemma": "0.5"}


def _weights() -> dict[str, float]:
    return {c: float(os.getenv(f"RRF_WEIGHT_{c.upper()}", _WEIGHT_CANON[c])) for c in CHANNELS}


def _rrf(channel_hits: dict[str, list[dict]], weights: dict[str, float], k: int) -> list[dict]:
    """Reciprocal Rank Fusion: score(doc) = Σ_channel w_c / (k + rank_c(doc)). Scale-invariant —
    fuses by RANK, so cosine-dist / ts_rank_cd being on different scales is moot."""
    scores: dict[tuple, float] = {}
    info: dict[tuple, dict] = {}
    for ch, hits in channel_hits.items():
        w = weights.get(ch, 1.0)
        for rank, h in enumerate(hits, 1):
            key = (h["act"], h["unit_path"], h["in_force_from"])
            scores[key] = scores.get(key, 0.0) + w / (k + rank)
            info.setdefault(key, {"hit": h, "channels": {}})
            info[key]["channels"][ch] = rank
    out = []
    for key, score in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        h = dict(info[key]["hit"])
        h.pop("dist", None)
        h.pop("rank", None)   # channel-local scores are meaningless post-fusion
        h["rrf_score"] = score
        h["channels"] = info[key]["channels"]        # {channel: rank} — which channel contributed
        out.append(h)
    return out


def _run_channel(conn, name: str, query_text: str, as_of, topn: int,
                 degraded: list[str]) -> list[dict] | None:
    """Run ONE candidate channel; on ANY failure degrade honestly (append to `degraded`, return
    None), never crash the fusion — degradation must be SYMMETRIC. All three channels are wrapped
    the same way — a DB channel (fts/lemma) throwing (dead conn, pipeline_version
    mismatch) must NOT discard the results the other channels already produced, exactly as a
    down LM Studio must not (dense). A failed query aborts the tx, so roll back defensively before
    the next channel runs on the same conn; on a truly-dead conn the rollback itself no-ops and the
    remaining channels degrade too — still honest, never hidden."""
    # resolve the channel fn from the module globals AT CALL TIME (not a frozen dict) so a
    # mock.patch.object(retrieval, "dense"/…) in tests — and any future channel swap — is honoured.
    fn = {"dense": dense, "fts": fts, "lemma": lemma}[name]
    try:
        return fn(conn, query_text, as_of, k=topn)
    except Exception as exc:  # noqa: BLE001 — LM down / DB error / version mismatch: degrade, don't hide
        degraded.append(name)
        try:
            conn.rollback()   # clear an aborted tx so sibling channels survive (no-op if none/dead)
        except Exception:     # noqa: BLE001 — conn dead: next channel degrades too, still surfaced
            pass
        if os.getenv("RAG_DEBUG"):
            strong = " (dense is the strongest channel)" if name == "dense" else ""
            print(f"[RAG_DEBUG] {name} channel UNAVAILABLE ({type(exc).__name__}) — fusing the "
                  f"remaining channels only; result is DEGRADED{strong}.")
        return None


def hybrid(conn, query_text: str, as_of=None, k: int = 10) -> tuple[list[dict], dict]:
    """Fuse dense + fts + lemma by RRF → (top-k, meta). Scope-gate is applied INSIDE each channel.

    Channel unavailability is NEVER silent (a silent drop is the antipattern we refuse): EVERY
    channel is wrapped symmetrically — a failure (LM Studio down for dense, a dead conn / version
    mismatch for fts/lemma) drops that channel into `meta['degraded']`, logs it under RAG_DEBUG, and
    fuses the survivors — a partial result MUST be surfaced with its degradation flagged, not
    returned as if whole nor thrown away. dense is the strongest channel (5/5 on paraphrases vs 1/5
    keyword), so a dense-less result is especially flagged. (Honest-R-10 on a down RERANKER is a
    different, louder contract — the rerank layer, not this one.) meta always carries which channels
    ran, for the caller + RAG_DEBUG."""
    topn, weights, kk = _rrf_topn(), _weights(), _rrf_k()
    hits: dict[str, list[dict]] = {}
    degraded: list[str] = []
    for name in CHANNELS:
        res = _run_channel(conn, name, query_text, as_of, topn, degraded)
        if res is not None:
            hits[name] = res

    fused = _rrf(hits, weights, kk)[:k]
    meta = {"channels_run": [c for c in CHANNELS if c in hits], "degraded": degraded,
            "weights": weights, "rrf_k": kk, "topn": topn}
    if os.getenv("RAG_DEBUG"):
        print(f"[RAG_DEBUG] hybrid: ran={meta['channels_run']} degraded={degraded} "
              f"k={kk} topn={topn} weights={weights}")
        for h in fused:
            print(f"[RAG_DEBUG]   {h['act']:12s} {h['unit_path']:18s} rrf={h['rrf_score']:.5f} "
                  f"channels={h['channels']}")
    return fused, meta


# ── Reranker gate: cross-encoder PRECISION over RRF RECALL ──────────────────────────────────────
# RRF gets the target into the top-N; the reranker reorders those finalists by a cross-encoder that
# reads query+doc together (ml.reranker, bge-reranker-v2-m3, in-process on the GPU).
# Config in .env: RERANK_TOPN (how many RRF candidates to rerank). The rerank score is EPHEMERAL —
# no cache, no schema. The reranker is a QUALITY GATE: its absence is honest-R-10, NOT a silent
# fallback to RRF order.


def _rerank_topn() -> int:
    return int(os.getenv("RERANK_TOPN", "50"))


def _fetch_texts(conn, hits: list[dict]) -> dict[str, str]:
    """content_hash → chunk text for the fused candidates (one batched read). The reranker needs the
    full text (the channels carry only citations); text is 1:1 with content_hash so it is the key."""
    hashes = list({h["content_hash"] for h in hits if h.get("content_hash")})
    if not hashes:
        return {}
    with conn.cursor() as cur:
        cur.execute("SELECT content_hash, text FROM chunks_indexable WHERE content_hash = ANY(%s)",
                    (hashes,))
        return {ch: txt for ch, txt in cur.fetchall()}


# ── Exact-lookup route: citation queries resolve by regex+SQL, NOT ML (a citation is an ID) ─────
# The citation class of the reference questions measures 0.167 STRUCTURALLY: the article NUMBER
# lives only in unit_path/citation metadata, never in the chunk TEXT, so no text/embedding channel
# can find it. A parsed «ст.N» + a resolved act → a deterministic SQL lookup returns the article's
# servable leaves as candidate #1 BEFORE the channels; the channels supplement. Act not recognised
# (or no article number) → the route stays SILENT (never guess), channels run as usual.

# «стаття N» / «статті N» / «ст. N» / «ст.N-M» → the digits (unit_path stem 'ст.N').
_ART_RE = re.compile(r"\b(?:статт\w*|ст)\.?\s*(\d+(?:-\d+)?)", re.IGNORECASE)


def natkey(s: str) -> tuple:
    """Natural-sort key for a unit_path: digit runs compare numerically so ст.N/п.2 < ст.N/п.10
    (lexicographic order put п.10 before п.2). Used to order an article's leaves."""
    return tuple(int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s or ""))

# Code abbreviations the Rada card does NOT carry (acts.title has only the full name — no abbreviation
# column). Hardcoded deliberately; on corpus expansion beyond the closed 14-act set, move this to
# config. Matched CASE-SENSITIVELY on the ORIGINAL query (an adversarial-review fix): «КАС» /
# «КУпАП» is the code; lowercase «кас» is the word каса (cash desk) / касаційний — must NOT route.
# Maps to the CURRENT nreg, not the archival КУпАП splits (80731/80732-10).
_ABBR = {"КУпАП": "8073-10", "КАС": "2747-15"}

# The channels SUPPLEMENT the exact route: slots reserved for the top reranked channel hits in
# search(), so a large exact article cannot fully saturate the top-k (an adversarial-review fix).
_EXACT_RESERVE = 2

_TITLE_KEYS_CACHE: list[tuple[str, str]] | None = None


def _norm(s: str) -> str:
    """Lowercase, drop quote marks, fold apostrophe variants (incl. U+02BC ʼ) to U+0027, collapse
    whitespace. Keeps in-word apostrophes (обов'язок) so title/query align."""
    s = s.lower()
    for q in "«»\"“”„‹›":
        s = s.replace(q, " ")
    for ap in "’`´ʼ":                                 # U+2019 U+0060 U+00B4 U+02BC → U+0027
        s = s.replace(ap, "'")
    return re.sub(r"\s+", " ", s).strip()


def _title_keys(conn) -> list[tuple[str, str]]:
    """(normalised title key, nreg), longest first. Keys = full title + title-minus-first-word
    (handles genitive «Кодексу» vs «Кодекс») + raw nreg. Abbreviations are handled separately
    (case-sensitive). Built once from the acts table (self-maintaining), cached per process."""
    global _TITLE_KEYS_CACHE
    if _TITLE_KEYS_CACHE is None:
        keys: list[tuple[str, str]] = []
        with conn.cursor() as cur:
            cur.execute("SELECT nreg, title FROM acts")
            rows = cur.fetchall()
        for nreg, title in rows:
            t = _norm(title or "")
            if len(t) >= 6:
                keys.append((t, nreg))
                parts = t.split()
                if len(parts) >= 3:                       # drop the inflecting first word
                    keys.append((" ".join(parts[1:]), nreg))
            keys.append((nreg.lower(), nreg))             # raw nreg literal
        _TITLE_KEYS_CACHE = sorted(keys, key=lambda kv: -len(kv[0]))   # longest first = most specific
    return _TITLE_KEYS_CACHE


def _act_mentions(conn, query: str) -> list[tuple[int, str]]:
    """[(position_in_normalised_query, nreg)] for every act mentioned: titles/nreg (case-insensitive,
    normalised) + abbreviations (case-SENSITIVE on the ORIGINAL — «КАС» the code, not the word)."""
    qn = _norm(query)
    hits: list[tuple[int, str]] = []
    for key, nreg in _title_keys(conn):
        if len(key) <= 8:                                  # short keys: word-boundary (no substring)
            for m in re.finditer(rf"(?<!\w){re.escape(key)}(?!\w)", qn):
                hits.append((m.start(), nreg))
        else:
            i = qn.find(key)
            while i >= 0:
                hits.append((i, nreg))
                i = qn.find(key, i + 1)
    for abbr, nreg in _ABBR.items():
        if re.search(rf"(?<!\w){re.escape(abbr)}(?!\w)", query):       # ORIGINAL, case-sensitive
            for m in re.finditer(rf"(?<!\w){re.escape(abbr.lower())}(?!\w)", qn):
                hits.append((m.start(), nreg))
    return hits


def _parse_article(query: str) -> str | None:
    m = _ART_RE.search(query)
    return f"ст.{m.group(1)}" if m else None


def _citations(conn, query: str) -> list[tuple[str, str]]:
    """[(nreg, 'ст.N')] — every «ст.N» paired with the NEAREST act mention to its RIGHT (Ukrainian
    order «статтю N Кодексу X»). Fallback to an act on the LEFT is allowed ONLY for a lone citation
    (exactly one article AND one act — «У Кодексі X статтю N»); when the query names ≥2 acts, an
    article with no act to its right is DROPPED, never bound to some other clause's act: «ст.47 КАС
    і ст.15 закону про рибальство» must NOT serve КАС ст.15 — рибальство is unrecognised,
    ст.15 has no right act, and there are 2 acts → drop it. «ст.47 КАС і ст.210 КУпАП» → both.
    Deduped, in article order."""
    qn = _norm(query)
    arts = [(m.start(), f"ст.{m.group(1)}") for m in _ART_RE.finditer(qn)]
    mentions = _act_mentions(conn, query)
    if not arts or not mentions:
        return []
    distinct_acts = {n for _p, n in mentions}
    lone = len(arts) == 1 and len(distinct_acts) == 1     # unambiguous single citation
    pairs: list[tuple[str, str]] = []
    seen: set = set()
    for apos, art in arts:
        right = [(p, n) for p, n in mentions if p >= apos]
        if right:
            _pos, nreg = min(right, key=lambda pn: abs(pn[0] - apos))
        elif lone:
            nreg = next(iter(distinct_acts))              # act to the LEFT, single citation only
        else:
            continue                                      # ≥2 acts, no act to the right → drop
        if (nreg, art) not in seen:
            seen.add((nreg, art))
            pairs.append((nreg, art))
    return pairs


def _resolve_act(conn, query: str) -> str | None:
    """The act nreg cited (nearest to the first article; else any mention). None → not recognised
    (route stays silent — never guess)."""
    cits = _citations(conn, query)
    if cits:
        return cits[0][0]
    mentions = _act_mentions(conn, query)
    return mentions[0][1] if mentions else None


def exact_lookup(conn, query_text: str, as_of=None, limit: int = 10) -> list[dict]:
    """Deterministic citation route: each «ст.N» + resolved act (via _citations) → that article's
    scope-gated servable leaves (unit_path = ст.N OR ст.N/*, article-container FIRST then leaves by
    unit_path). [] if no article resolves to an act (silent — the channels handle it).

    Multi-citation is ROUND-ROBIN interleaved: with M cited articles every one gets
    top slots even when one is far larger — «ст.47 КАС (9 leaves) і ст.210 КУпАП (1)» → both reach
    the top, ст.210 is not starved by ст.47's leaves. route='exact' per hit."""
    pairs = _citations(conn, query_text)
    if not pairs:
        return []
    # Fetch ALL of the article's leaves (cap 500, safely above any real article), THEN natkey-sort,
    # THEN slice to `limit`: `ORDER BY unit_path LIMIT k` selected a LEXICOGRAPHIC page — limit=6
    # took п.10 and cut п.5–п.9 before the natural re-sort could run.
    sql = (
        "SELECT ci.content_hash, ci.act_nreg, ci.unit_path, ci.citation, ci.in_force_from, "
        "       ci.in_force_to FROM chunks_indexable ci "
        "WHERE ci.act_nreg = %(act)s AND (ci.unit_path = %(art)s OR ci.unit_path LIKE %(pfx)s) "
        f"AND {scope_clause('ci')} ORDER BY ci.unit_path LIMIT 500")
    per_article: list[list[dict]] = []
    with conn.cursor() as cur:
        for act, art in pairs:
            cur.execute(sql, {"act": act, "art": art, "pfx": art + "/%", "as_of": as_of})
            rows = sorted(cur.fetchall(), key=lambda r: natkey(r[2]))[:limit]   # natural order, THEN cap
            per_article.append([{"content_hash": h, "act": a, "unit_path": p, "citation": c,
                                 "in_force_from": f, "in_force_to": t, "route": "exact"}
                                for h, a, p, c, f, t in rows])
    out: list[dict] = []
    for i in range(max((len(a) for a in per_article), default=0)):
        for a in per_article:
            if i < len(a):
                out.append(a[i])
    return out[:limit]


def search(conn, query_text: str, as_of=None, k: int = 10,
           rerank_topn: int | None = None) -> tuple[list[dict], dict]:
    """Full retrieval: exact-lookup → hybrid RRF → cross-encoder rerank → top-k (+ meta).

    Exact route FIRST: a parsed «ст.N» + resolved act yields the article's servable
    leaves as the DETERMINISTIC #1 candidate(s) — placed at the top, NEVER reranked (a citation is
    an ID, not a relevance guess). The channels then supplement: hybrid() fuses RRF_TOPN candidates
    per channel (calibrated weights, degradation already surfaced in meta), the reranker reorders
    THOSE (precision), and they are appended after the exact hits, deduped by citable identity.
    meta['route'] = 'exact' when the exact route fired, else 'channels'.

    Honest-R-10: the reranker is a QUALITY GATE. If it is UNAVAILABLE (RerankerUnavailable —
    no GPU / OOM / model absent) the channel order falls back down the ladder reranker→dense→keyword,
    FLAGGED not silent: meta['reranked']=False, 'reranker' appended to meta['degraded'], RAG_DEBUG
    logs it. A model DRIFT is NOT degraded here — that is a SystemExit from the pin (refuse the wrong
    model), which propagates. The exact route is unaffected by a down reranker — it never reranks."""
    exact = exact_lookup(conn, query_text, as_of, limit=k)
    topn = rerank_topn if rerank_topn is not None else _rerank_topn()
    fused, meta = hybrid(conn, query_text, as_of, k=topn)
    meta["reranked"] = False
    meta["route"] = "exact" if exact else "channels"

    if fused:
        from ml.reranker import RerankerUnavailable, rerank
        try:
            texts = _fetch_texts(conn, fused)
            scored = rerank(query_text, [texts.get(h["content_hash"], "") for h in fused])
            for h, s in zip(fused, scored):
                h["rerank_score"] = s
            fused = sorted(fused, key=lambda h: h["rerank_score"], reverse=True)
            meta["reranked"] = True
        except RerankerUnavailable as exc:
            # honest-R-10: quality gate down — surface LOUDLY, keep the RRF-order ladder fallback.
            meta["degraded"] = meta.get("degraded", []) + ["reranker"]
            if os.getenv("RAG_DEBUG"):
                print(f"[RAG_DEBUG] RERANKER UNAVAILABLE ({type(exc).__name__}) — honest-R-10: "
                      f"RRF-order fallback (ladder reranker→dense→keyword), NOT reranked. {exc}")

    # exact hits = deterministic citation authority → FIRST, never reranked; reranked channel
    # candidates supplement, deduped by citable identity (act, unit_path, in_force_from). Reserve a
    # couple of slots for the top reranked channels so a large exact article (or a passing-mention
    # citation) can't fully bury the semantic best — the channels supplement the exact route.
    exact_keys = {(h["act"], h["unit_path"], h["in_force_from"]) for h in exact}
    channel = [h for h in fused
               if (h["act"], h["unit_path"], h["in_force_from"]) not in exact_keys]
    reserve = min(_EXACT_RESERVE, len(channel))
    merged = (exact[:max(1, k - reserve)] + channel)[:k]
    if os.getenv("RAG_DEBUG"):
        print(f"[RAG_DEBUG] search: route={meta['route']} exact={len(exact)} "
              f"reranked={meta['reranked']} degraded={meta.get('degraded', [])} → top {k}")
        for h in merged[:k]:
            tag = ("exact" if h.get("route") == "exact"
                   else f"rerank={h.get('rerank_score', 0):+.3f}" if meta["reranked"]
                   else f"rrf={h.get('rrf_score', 0):.5f}")
            print(f"[RAG_DEBUG]   {h['act']:12s} {h['unit_path']:18s} {tag}")
    return merged[:k], meta
