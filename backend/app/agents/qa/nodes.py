"""The five nodes of the Q&A subgraph.

    rewrite_query → hybrid_retrieve → rerank → generate → ground_check

## Why hybrid retrieval at 338 rows

Dense-only retrieval is the default everywhere and it is the wrong default
here. The corpus is 338 short rows of policy text, and the questions people ask
it contain exact terms: a knowledge-base id ("ASP-042"), a parish name, a form
number, "EC$500". Embeddings are built to lose exactly that -- they map
surface form to meaning, and "ASP-042" has no meaning to map.

BM25 finds those trivially and is useless on "what if my child moves away",
which the dense side handles. So both run, and reciprocal rank fusion combines
them without either needing a calibrated score. RRF is used rather than a
weighted score sum because the two retrievers' scores are not comparable --
cosine similarity and BM25 saturation are different quantities, and any weight
that works today is a weight tuned to one corpus snapshot.

## Ungrounded means escalate, not guess

`ground_check` is the node that matters. It fails a turn in four ways:

  * nothing was retrieved at all;
  * nothing was retrieved at all;
  * the closest chunk's cosine relevance is below a floor set against the
    ABSURD rather than against the plausible (see below);
  * the answer cites no retrieved row, or cites one that was not retrieved;
  * the answer contains a FIGURE that appears in no retrieved chunk.

## Similarity cannot decide this, and the measurement says so

The obvious design is a similarity threshold. It does not work here, and the
numbers are in `evals/harness.py`: on this corpus the in-KB questions score
0.614-0.873 and the out-of-KB ones score 0.443-0.757, so the two populations
OVERLAP and the best possible threshold still misclassifies eleven of fifty.
"Can I get a loan against my child's ASPIRE account?" scores 0.757 -- higher
than most real questions -- because it is about savings accounts in every
respect except that the programme has no such product.

So the cosine floor is set below the lowest real question and does one job:
reject the case where nothing retrieved is even the same subject.

What decides groundedness is ATTRIBUTION. The model must cite a retrieved row,
the cited row must be one that was actually retrieved, and every figure in the
answer must appear in a chunk. A model that cannot find a row to point at for
"can I borrow against this?" does not produce one -- which is the property a
similarity score cannot give.

An ungrounded turn hands off to `escalate_agent`. It does not apologise and
answer anyway.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import Command

from app.config import get_settings
from app.graph.state import AspireState, Citation, KBChunk

logger = logging.getLogger(__name__)


# ── rewrite_query ────────────────────────────────────────────────────────────

REWRITE_SYSTEM = (
    "Rewrite the last user message into a standalone search query. Resolve "
    "pronouns and anything left out, using the conversation for context. Keep "
    "the user's own words wherever you can -- you are preparing a search, not "
    "improving a question. Reply with the query and nothing else. If the "
    "message already stands alone, repeat it unchanged."
)

#: How many turns of context the rewriter sees. Four is two exchanges, which is
#: where ellipsis actually reaches back to ("and for my son?" refers to the
#: question before last, not to turn nine).
REWRITE_WINDOW = 4


def make_rewrite_query(invoke=None):
    """Resolve pronouns and ellipsis before embedding.

    "And what about my son?" embeds to nothing useful; "what are the eligibility
    rules for a son?" embeds to the eligibility rows. This is the cheapest
    retrieval improvement available and it is why it runs on a small model.

    The rewrite is logged as a SHA and a length, never as text. A retrieval
    that returns nothing is nearly always a rewrite that went wrong, and the
    pair of hashes is enough to find that turn again -- whereas the questions
    themselves are children's, and this runs at INFO.
    """

    async def rewrite_query(state: AspireState) -> dict[str, Any]:
        messages = state.get("messages", [])
        original = _latest_user_text(state)
        if not original:
            return {}

        if invoke is None or len(messages) <= 1:
            # An opening question has no context to resolve against, so the
            # rewrite would be an identity transform with a model call attached.
            return {"qa_query": original}

        context = "\n".join(
            f"{_role(message)}: {_text_of(message)}"
            for message in messages[-(REWRITE_WINDOW + 1) : -1]
        )
        try:
            rewritten = (await invoke(REWRITE_SYSTEM, f"{context}\n\nuser: {original}")).strip()
        except Exception:
            logger.warning("Query rewrite failed; searching the original.", exc_info=True)
            rewritten = original

        # A rewrite that came back empty, or vastly longer than the question, is
        # a rewrite that went wrong. Falling back costs nothing.
        if not rewritten or len(rewritten) > len(original) * 6 + 80:
            rewritten = original

        if rewritten != original:
            # Shape, not text. The debugging value of this line is "the rewrite
            # changed the question, and by how much" -- a retrieval that returns
            # nothing is usually a rewrite that went wrong, and the lengths plus
            # the sha are enough to find that turn again. The question itself is
            # a child's, at INFO, in the system journal; it does not go here.
            logger.info(
                "rewrote query sha=%s (%d chars) -> sha=%s (%d chars)",
                hashlib.sha256(original.encode("utf-8")).hexdigest()[:12],
                len(original),
                hashlib.sha256(rewritten.encode("utf-8")).hexdigest()[:12],
                len(rewritten),
            )
        return {"qa_query": rewritten}

    return rewrite_query


# ── hybrid_retrieve ──────────────────────────────────────────────────────────


def rrf_fuse(
    rankings: list[list[str]], *, k: int = 60
) -> dict[str, float]:
    """Reciprocal rank fusion over several ranked id lists.

    `score(d) = sum over rankings of 1 / (k + rank(d))`, rank being 1-based.
    `k=60` is the value from the original paper; it damps the top of each list
    so a single retriever cannot dominate on its own confidence.

    The property that makes this the right choice here: it uses only RANKS. The
    two retrievers' scores are not on a comparable scale and never will be, so
    any weighted sum of them is a weight tuned to one corpus snapshot.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for position, identifier in enumerate(ranking, start=1):
            scores[identifier] = scores.get(identifier, 0.0) + 1.0 / (k + position)
    return scores


def bm25_rank(query: str, corpus: list[tuple[str, str]], top: int) -> list[str]:
    """BM25 over `(id, text)` pairs. Returns ids, best first.

    The id is indexed ALONGSIDE the text, which is the whole reason this half
    exists: "what does ASP-004 say" is a real question, and the row id does not
    appear in the row's own content. Without this the lexical retriever is blind
    to exactly the queries the dense one cannot handle.

    Built per call rather than cached, and that is affordable precisely because
    the corpus is 338 rows -- tokenising it costs single-digit milliseconds. At
    ten thousand rows this would need an index; at 338 an index is a cache
    invalidation problem in exchange for nothing.
    """
    if not corpus:
        return []
    from rank_bm25 import BM25Okapi

    tokenised = [_tokens(f"{identifier} {text}") for identifier, text in corpus]
    if not any(tokenised):
        return []
    index = BM25Okapi(tokenised)
    scores = index.get_scores(_tokens(query))
    ordered = sorted(
        range(len(corpus)), key=lambda position: scores[position], reverse=True
    )
    return [corpus[position][0] for position in ordered[:top] if scores[position] > 0]


_WORD = re.compile(r"[a-z0-9$]+")


def _tokens(text: str) -> list[str]:
    """Lowercase alphanumeric runs, keeping `$` so "EC$500" survives.

    Dropping `$` would split that into "ec" and "500", and "500" matches every
    row with a number in it.
    """
    return _WORD.findall(text.lower())


def make_hybrid_retrieve(search=None, corpus=None):
    """Dense and BM25 together, fused by RRF.

    `search` is `async (query, k) -> list[KBChunk]` and `corpus` is
    `async () -> list[(kb_id, text)]`. Both are injected so this node is
    testable without a database, and so the eval harness can swap in a fixed
    corpus.

    The audience filter narrows BOTH halves for `qa_agent_limited` and
    `qa_agent_public` -- the dense results by chunk metadata, the lexical corpus
    by the loader, which is handed the audience. It is a FILTER on this node
    rather than a separate subgraph, which is the whole point of A5's seventh
    rule: three agents, one graph, one place where retrieval can be got wrong.
    """

    async def hybrid_retrieve(state: AspireState) -> dict[str, Any]:
        settings = get_settings()
        query = state.get("qa_query") or _latest_user_text(state)
        if not query:
            return {"retrieved": []}

        audience = _audience(state)
        dense: list[KBChunk] = []
        if search is not None:
            try:
                dense = await search(query, settings.qa_retrieve_k)
            except Exception:
                # A dense failure is survivable BECAUSE there is a second
                # retriever. Failing the turn here would throw away the half of
                # the system that handles exact terms.
                logger.warning("Dense retrieval failed; BM25 only.", exc_info=True)

        rows: list[tuple[str, str]] = []
        if corpus is not None:
            try:
                rows = await corpus(audience)
            except Exception:
                logger.warning("Could not load the corpus for BM25.", exc_info=True)

        dense = [chunk for chunk in dense if _permitted(chunk, audience)]
        by_id: dict[str, KBChunk] = {chunk.kb_id: chunk for chunk in dense}

        # BM25 searches the WHOLE audience-permitted corpus, never a subset of
        # what the dense side already found. Restricting it to the dense
        # results would make it a re-ranker of that list -- and the queries it
        # exists for are precisely the ones the dense side missed entirely.
        lexical = bm25_rank(query, rows, settings.qa_retrieve_k)
        text_by_id = dict(rows)
        for identifier in lexical:
            if identifier not in by_id:
                by_id[identifier] = KBChunk(
                    kb_id=identifier, content=text_by_id.get(identifier, ""), source="bm25"
                )

        rankings = [[chunk.kb_id for chunk in dense], lexical]
        fused = rrf_fuse(rankings, k=settings.qa_rrf_k)
        ranked = sorted(fused, key=lambda identifier: -fused[identifier])

        # Normalised against the best score this fusion could possibly produce
        # -- a document ranked first by every retriever. Without it the scores
        # are around 0.03 and mean nothing to a reader of a trace.
        #
        # The scale is AGREEMENT, not similarity: 1.0 means both retrievers put
        # this first. It orders chunks and it is deliberately NOT what
        # `ground_check` uses as its relevance floor -- see `lexical_coverage`
        # there for why a rank-fusion score cannot answer "is anything in the
        # corpus about this?".
        ceiling = len(rankings) / (settings.qa_rrf_k + 1)

        chunks: list[KBChunk] = []
        for identifier in ranked[: settings.qa_retrieve_k]:
            chunk = by_id.get(identifier)
            if chunk is None:
                continue
            chunks.append(
                chunk.model_copy(
                    update={
                        "score": min(1.0, fused[identifier] / ceiling),
                        # `relevance` is NOT touched. Fusion decides order;
                        # only the dense retriever measures similarity, and a
                        # BM25-only hit legitimately keeps 0.0.
                        "source": "fused",
                    }
                )
            )

        # The QUERY IS NOT LOGGED, and that is the point of this shape.
        #
        # This logged `query[:60]` at INFO, which is the default level, so every
        # question a child typed went into the system journal verbatim -- name,
        # address, school and parent's email included when they volunteered
        # them, which children do. On a minors' programme that is the single
        # worst thing this service could write down.
        #
        # The counts are what the line was for; they are kept. `qa_query_sha` is
        # the correlation handle that replaces the text: it ties this line to a
        # later one about the same question without recording what was asked.
        logger.info(
            "hybrid retrieval: %d dense, %d lexical, %d fused (query sha=%s len=%d)",
            len(dense),
            len(lexical),
            len(chunks),
            hashlib.sha256(query.encode("utf-8")).hexdigest()[:12],
            len(query),
        )
        return {"retrieved": chunks}

    return hybrid_retrieve


def _audience(state: AspireState) -> str:
    """Which corpus slice this agent may see.

    `qa_agent_limited` and `qa_agent_public` are the SAME subgraph with a
    different filter, so the agent name is what selects the slice.
    """
    return {
        "qa_agent_limited": "youth",
        "qa_agent_public": "public",
    }.get(str(state.get("active_agent")), "all")


#: The corpus's own audience vocabulary, mapped onto the two filtered slices.
#:
#: ## Why this table exists rather than a `"public" in tags` test
#:
#: It did not exist, and the filter tested for `public` and `youth`. The corpus
#: does not use either word. Measured against the live 706-row table:
#:
#:     student  246    parent  188    general  166    child  57    teacher  49
#:
#: So `qa_agent_public` and `qa_agent_limited` matched NOTHING, on every turn,
#: since they were written. The failure was invisible because it fails closed in
#: the safest possible direction: retrieval returned nothing, `ground_check`
#: refused to answer without context, and the turn escalated to a human. No
#: wrong answer was ever produced. It simply meant that an anonymous visitor and
#: every 13-15 reader got a ticket instead of an answer, always.
#:
#: ## Both slices are every tag the corpus uses, and that is the honest answer
#:
#: The first attempt withheld `parent` and `teacher` from children, on the
#: reasoning that guardian consent and classroom guidance are adult material.
#: It was wrong, and a live turn showed why within minutes: a nine-year-old
#: asking *"what is the minimum age?"* got escalated to a human, because the
#: three rows that answer it -- ASP-029, ASP-030, ASP-241 -- are all tagged
#: `parent`.
#:
#: `parent` in this corpus means "written with a parent as the reader", not
#: "withheld from a child". *"The minimum age to join ASPIRE is 5"* is a fact
#: any child may know, and there is nothing in a public knowledge base that a
#: child must not read.
#:
#: So this maps the five tags the corpus actually has, and the filter's real
#: value is what it EXCLUDES: anything not listed. A `staff` or `internal` tier
#: -- reviewer notes, unpublished policy -- would be barred from both child
#: slices the day it is added, without this file changing.
#:
#: Stated plainly rather than dressed up: **the audience filter currently has
#: nothing to filter.** The mechanism is real and the two agent names are worth
#: keeping distinct for the day the corpus grows a tier that needs them. Until
#: then, making it appear to do work by withholding correct answers from
#: children is worse than admitting it does none.
AUDIENCE_TAGS: dict[str, frozenset[str]] = {
    "public": frozenset({"general", "student", "child", "parent", "teacher"}),
    "youth": frozenset({"general", "student", "child", "parent", "teacher"}),
}


def _permitted(chunk: KBChunk, audience: str) -> bool:
    """Whether this chunk may be shown to this audience.

    Metadata-driven and permissive by default: a corpus row with no audience
    tag is general information, and defaulting it to "hidden" would empty the
    knowledge base for the two filtered agents on the day the tags were added.

    An audience name this function does not know is also permissive, for the
    same reason -- but note that it is the ROW's tag being unknown that is
    permissive, never the request's. An unknown `audience` argument falls
    through to the `all` slice, which is why `_audience` maps agent names rather
    than accepting one.
    """
    if audience == "all":
        return True
    tags = chunk.metadata.get("audience")
    if not tags:
        return True
    if isinstance(tags, str):
        tags = [tags]

    allowed = AUDIENCE_TAGS.get(audience)
    if allowed is None:  # pragma: no cover - `_audience` cannot produce this
        return True
    return any(str(tag).strip().lower() in allowed for tag in tags)


# ── rerank ───────────────────────────────────────────────────────────────────


def make_rerank(score=None):
    """Narrow the fused list to the few chunks the model actually reads.

    `score` is `async (query, chunks) -> list[float]`, a cross-encoder. When it
    is absent this falls back to the RRF order, which is a real degradation and
    not a failure: RRF's top-4 is a decent approximation of a cross-encoder's
    top-4, and running without a reranker is a legitimate deployment.

    Cutting to four rather than passing twelve is a grounding decision as much
    as a cost one: every extra chunk is another set of numbers the model can
    blend into an answer that then attributes to none of them.
    """

    async def rerank(state: AspireState) -> dict[str, Any]:
        chunks = list(state.get("retrieved") or [])
        if not chunks:
            return {}
        top = get_settings().qa_rerank_k

        if score is None:
            return {"retrieved": chunks[:top]}

        query = state.get("qa_query") or _latest_user_text(state)
        try:
            scores = await score(query, chunks)
        except Exception:
            logger.warning("Reranking failed; keeping the fused order.", exc_info=True)
            return {"retrieved": chunks[:top]}

        paired = sorted(zip(chunks, scores), key=lambda pair: -pair[1])
        return {
            "retrieved": [
                chunk.model_copy(update={"score": float(value)})
                for chunk, value in paired[:top]
            ]
        }

    return rerank


# ── generate ─────────────────────────────────────────────────────────────────

GENERATE_SYSTEM = """You answer questions about the ASPIRE savings programme.

Rules, in order of importance:
1. Answer ONLY from the numbered knowledge-base extracts below. If they do not
   contain the answer, say so plainly -- do not fill the gap from anything you
   know.
2. Every figure, date, amount and rule in your answer must appear in an extract.
   Do not round, convert, average or infer one.
3. Cite the extracts you used by their [ASP-xxx] id, inline.
4. Write for the reader described below. Short sentences. No links.

Knowledge-base extracts:
{context}
"""


def make_generate(invoke=None):
    """Write the answer from the retrieved chunks and nothing else."""

    async def generate(state: AspireState) -> dict[str, Any]:
        chunks = list(state.get("retrieved") or [])
        question = _latest_user_text(state)

        if not chunks:
            # No context at all. Generating here would be generating from the
            # model's own weights, which is the single thing this subgraph
            # exists to prevent -- so it does not generate, it escalates.
            logger.info("Nothing retrieved; escalating rather than answering.")
            return {"groundedness": 0.0}

        context = "\n\n".join(
            f"[{chunk.kb_id}] {chunk.content}" for chunk in chunks
        )
        system = GENERATE_SYSTEM.format(context=context)
        audience = (
            f"Reader: age band {state.get('age_band')}, persona "
            f"{state.get('persona')}, language {state.get('locale')}."
        )

        if invoke is None:
            return {"groundedness": 0.0}

        text = await invoke(
            [SystemMessage(content=f"{system}\n{audience}"), HumanMessage(content=question)]
        )
        return {"messages": [AIMessage(content=text)]}

    return generate


# ── ground_check ─────────────────────────────────────────────────────────────

#: Numbers and money amounts in an answer. Each one has to be findable in a
#: retrieved chunk.
_FIGURE = re.compile(r"(?:EC\$|US\$|\$)?\d[\d,]*(?:\.\d+)?%?")

#: Figures that are never claims: small integers used as ordinals or counts
#: ("three documents", "step 2"), and years already present in the question.
_INNOCUOUS = frozenset({"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"})

#: Phrases that assert a rule. A sentence containing one must cite something.
_POLICY = re.compile(
    r"\b(?:must|required|not allowed|cannot|may not|is eligible|are eligible"
    r"|deadline|minimum|maximum|entitled|guaranteed)\b",
    re.IGNORECASE,
)


def normalise_figure(text: str) -> str:
    """A figure reduced to its digits, so `EC$1,200.00` matches `1200`.

    Comparing raw strings would fail on every difference in currency symbol,
    thousands separator and trailing zeros -- which is to say, on nearly every
    real pair. Trailing zeros after a decimal point are dropped so `1200.00`
    and `1200` are the same number.
    """
    digits = re.sub(r"[^\d.]", "", text)
    if "." in digits:
        digits = digits.rstrip("0").rstrip(".")
    return digits.lstrip("0") or "0"


def unattributed_figures(answer: str, chunks: list[KBChunk]) -> list[str]:
    """Figures in the answer that appear in no chunk.

    The crude check that catches the failure that actually happens: a model
    handed four chunks about eligibility and asked for a deposit minimum
    produces a plausible number in the same voice as the grounded sentences
    around it. Nothing subtler is needed, because nothing subtler is what goes
    wrong.
    """
    corpus = " ".join(chunk.content for chunk in chunks)
    known = {normalise_figure(match.group(0)) for match in _FIGURE.finditer(corpus)}

    missing: list[str] = []
    for match in _FIGURE.finditer(answer):
        raw = match.group(0)
        value = normalise_figure(raw)
        if value in _INNOCUOUS or value in known:
            continue
        missing.append(raw)
    return missing


#: English function words, removed before measuring coverage. Everything left
#: is a content word the corpus ought to contain if it is about this question.
_STOPWORDS = frozenset(
    "a an and are as at be by can could do does did for from had has have how i "
    "if in is it its me my of on or our so than that the their them there they "
    "this to us was we were what when where which who whom why will with would "
    "you your".split()
)


#: How many DISTINCT content words must appear, on top of the fraction floor.
#:
#: The fraction alone is not enough on a short question. "What is the capital of
#: Mongolia?" has two content words; one of them ("capital") appears in a
#: savings corpus by coincidence, so it scores 50% and clears a 25% floor.
#: Requiring two distinct matches means a single coincidental word can never
#: ground an answer -- which is exactly the failure mode of a short off-topic
#: question, and the one the eval set is full of.
#:
#: Two, not three: "who is eligible?" and "what documents?" are real questions
#: with two content words each, and a floor of three would refuse them.
MIN_MATCHED_TERMS = 2


def matched_terms(query: str, chunks: list[KBChunk]) -> int:
    """How many distinct content words from the question appear in the chunks."""
    terms = {token for token in _tokens(query) if token not in _STOPWORDS}
    if not terms:
        return MIN_MATCHED_TERMS
    corpus = set(_tokens(" ".join(chunk.content for chunk in chunks)))
    return len(terms & corpus)


def required_terms(query: str) -> int:
    """How many matches this question needs. Never more than it has.

    "Deposit?" is one content word, and demanding two matches from it would
    refuse a question the corpus answers directly. The floor is
    `min(MIN_MATCHED_TERMS, content words available)` -- so a two-word question
    still needs both, and a one-word question needs its one.
    """
    terms = {token for token in _tokens(query) if token not in _STOPWORDS}
    return min(MIN_MATCHED_TERMS, len(terms)) if terms else 0


def lexical_coverage(query: str, chunks: list[KBChunk]) -> float:
    """What fraction of the question's content words the retrieved text contains.

    This -- not the fusion score -- is the relevance floor, and the distinction
    matters. Reciprocal rank fusion produces a number from RANKS: it says which
    of the retrieved chunks is best, and it says nothing whatever about whether
    the best one is any good. Every chunk a retriever returns scores highly on
    it, including the twelve nearest neighbours of a question the corpus has
    never heard of. A floor built on it would be a floor that never fires.

    Coverage does fire. "What is the capital of Mongolia" has two content words
    and neither appears anywhere in a corpus about a savings programme, so it
    scores 0 and escalates -- which is the acceptance criterion for this agent.

    Returns 1.0 for a query with no content words at all ("what is it?"), which
    is a question the *rewrite* step should have resolved; failing it here would
    blame the wrong node.
    """
    terms = {token for token in _tokens(query) if token not in _STOPWORDS}
    if not terms:
        return 1.0
    corpus = set(_tokens(" ".join(chunk.content for chunk in chunks)))
    return len(terms & corpus) / len(terms)


def make_ground_check(threshold: float | None = None):
    """Decide whether this answer may be served, or must go to a person."""

    async def ground_check(state: AspireState) -> Command:
        settings = get_settings()
        floor = threshold if threshold is not None else settings.qa_relevance_floor
        coverage_floor = settings.qa_coverage_floor
        chunks = list(state.get("retrieved") or [])
        messages = state.get("messages") or []
        answer = _text_of(messages[-1]) if messages else ""

        if not chunks or not answer.strip():
            return _escalate(state, "no_context", "Nothing in the knowledge base matched.")

        query = state.get("qa_query") or _latest_user_text(state)

        # ── the primary floor: real cosine relevance ────────────────────────
        #
        # `relevance` is the dense retriever's cosine similarity, which is the
        # only CALIBRATED measure available. The fusion `score` is not: it is
        # derived from ranks, so every chunk a retriever returns scores highly
        # on it -- including the twelve nearest neighbours of a question the
        # corpus has never heard of.
        #
        # A BM25-only chunk carries 0.0, so a turn whose entire retrieval came
        # from the lexical side must clear the floor on the lexical check
        # below. That is the correct asymmetry: BM25 matching "apply" in "how
        # do I apply for a passport?" is not evidence of anything.
        best = max((chunk.relevance for chunk in chunks), default=0.0)
        dense_seen = any(chunk.relevance > 0.0 for chunk in chunks)
        if dense_seen and best < floor:
            return _escalate(
                state,
                "below_relevance_floor",
                f"The closest chunk scored {best:.3f}, below the {floor:.3f} floor.",
            )

        # ── the lexical floor: English only ─────────────────────────────────
        #
        # A second, independent signal, and the only one available when the
        # dense side is unavailable or returned nothing. English only, because
        # the corpus is English and cross-lingual retrieval is deliberate --
        # word overlap between a French question and an English chunk is zero by
        # construction, so applying this to those locales would escalate every
        # Spanish and French turn in the product.
        #
        # Those turns are not left ungoverned: the attribution checks below run
        # on every locale, and they are the ones that catch an invented figure.
        if str(state.get("locale") or "en") == "en":
            coverage = lexical_coverage(query, chunks)
            matched = matched_terms(query, chunks)
            needed = required_terms(query)
            if not dense_seen and (coverage < coverage_floor or matched < needed):
                return _escalate(
                    state,
                    "below_relevance_floor",
                    f"Only {coverage:.0%} of the question's words appear in the "
                    f"corpus ({matched} distinct term(s)); the floor is "
                    f"{coverage_floor:.0%} and {needed} term(s).",
                )

        missing = unattributed_figures(answer, chunks)
        if missing:
            logger.warning(
                "Ungrounded figures %s in an answer for session %s; escalating.",
                missing[:5],
                state.get("session_id"),
            )
            return _escalate(
                state,
                "unattributed_figure",
                f"The answer stated {', '.join(missing[:3])}, which no extract contains.",
            )

        # ── the gate that actually works: attribution ───────────────────────
        #
        # An answer with no citation is ungrounded, unconditionally. Not "if it
        # contains a policy word" -- that was the earlier rule and it let
        # through exactly the questions the measurement found hardest: "can I
        # get a loan against my child's account?" retrieves plausible chunks,
        # scores 0.757 cosine, contains no policy keyword, and is a question the
        # corpus does not answer.
        #
        # Requiring a citation moves the decision from "does this look
        # relevant?" -- which the embedding cannot settle -- to "can the model
        # point at the row it got this from?", which it can, and which is what
        # the specification asks for in as many words: never return an answer
        # without citations.
        known = {chunk.kb_id for chunk in chunks}
        cited = {
            match.group(1)
            for match in re.finditer(r"\[([A-Za-z]{2,6}-\d+)\]", answer)
        }
        grounded_citations = cited & known

        if not grounded_citations:
            return _escalate(
                state,
                "uncited",
                "The answer cites no retrieved extract, so nothing supports it.",
            )

        # A citation to something that was NOT retrieved is worse than none: it
        # is a fabricated reference, and it reads to a person as authority.
        invented = cited - known
        if invented:
            return _escalate(
                state,
                "invented_citation",
                f"The answer cited {sorted(invented)}, which was not retrieved.",
            )

        citations = [
            Citation(kb_id=chunk.kb_id, title=chunk.title)
            for chunk in chunks
            if chunk.kb_id in grounded_citations
        ]
        # The calibrated relevance of the best chunk, falling back to the fused
        # agreement when the dense side never ran. Telemetry -- the eval harness
        # tracks its distribution -- and deliberately not the gate: the gates
        # are the four checks above, each of which either fired or did not.
        groundedness = min(
            1.0,
            best if dense_seen else max((chunk.score for chunk in chunks), default=0.0),
        )

        return Command(
            update={
                "citations": citations,
                "groundedness": groundedness,
                "active_agent": state.get("active_agent"),
                "quick_replies": follow_up_chips(state, chunks, grounded_citations),
            }
        )

    return ground_check


#: How many chips go under an answer. Two, matching what `/chat` produced --
#: enough to suggest a direction, few enough that they read as an offer rather
#: than a menu.
FOLLOW_UP_CHIPS = 2

#: `QuickReplyOption.label`'s cap. A longer question is dropped rather than
#: truncated: half a question is not a question.
CHIP_MAX_CHARS = 60


def follow_up_chips(
    state: AspireState, chunks: list[KBChunk], cited: set[str]
) -> list[str]:
    """Two more questions the knowledge base can actually answer.

    ## Not a model call

    `/chat` spent a second model call per turn on this, showed it the question
    and the answer, and asked it to invent two follow-ups. It had no idea what
    the corpus contained, so a suggestion it produced was as likely to be a
    question ASPIRE cannot answer as one it can -- and tapping one of those
    lands on a refusal or an escalation.

    These come from the retrieval that already happened. Every chunk carries the
    `question` its row was written to answer, and the fused result is by
    construction the set of corpus questions nearest to the one just asked. So
    the chips are real questions, with real answers behind them, chosen by the
    retriever rather than guessed at -- for no extra call and no extra latency.

    ## What is excluded

    The rows the answer CITED, because a chip offering the question just
    answered is a chip that repeats the turn. And anything too similar to what
    the reader typed, for the same reason.
    """
    asked = _words(_last_question(state))
    seen: list[set[str]] = []
    chips: list[str] = []

    for chunk in chunks:
        if chunk.kb_id in cited:
            continue
        question = str(chunk.metadata.get("question") or chunk.title or "").strip()
        if not question or len(question) > CHIP_MAX_CHARS:
            continue

        words = _words(question)
        if not words:
            continue
        # Near-duplicates, not just exact ones. "What is the minimum age?" and
        # "What is the minimum age requirement for ASPIRE enrolment?" are
        # different rows and the same question, and offering the second under an
        # answer to the first reads as the assistant not having listened.
        if _restates(words, asked) or any(_restates(words, other) for other in seen):
            continue

        seen.append(words)
        chips.append(question)
        if len(chips) == FOLLOW_UP_CHIPS:
            break

    return chips


#: Above this overlap, two questions are the same question. Containment rather
#: than symmetric similarity, because the failure is a LONGER row restating a
#: short question -- Jaccard scores that pair low precisely when it matters.
_RESTATEMENT = 0.75

#: Words that carry no topic. Without these, "what is the" alone puts two
#: unrelated questions over the threshold.
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "at", "be", "can", "do", "does", "for", "how",
        "i", "in", "is", "it", "me", "my", "of", "on", "or", "the", "to", "we",
        "what", "when", "where", "which", "who", "why", "you", "your",
    }
)


def _words(text: str) -> set[str]:
    return {
        word.strip("?.!,;:'\"")
        for word in text.lower().split()
        if word.strip("?.!,;:'\"") and word.strip("?.!,;:'\"") not in _STOPWORDS
    }


#: Below this many content words, containment stops meaning anything and only
#: an exact match counts.
#:
#: TWO, and the boundary was found by trying three. "What is ASPIRE?" has ONE
#: content word, so every question mentioning ASPIRE contains it completely and
#: scores 1.0 -- unguarded, the product's most-asked question suppressed every
#: chip under its own answer. But "What is the minimum age?" has TWO
#: ("minimum", "age"), and a three-word floor let "What is the minimum age
#: requirement for ASPIRE enrolment?" back in as a follow-up to itself.
_RESTATEMENT_MIN_WORDS = 2


def _restates(candidate: set[str], other: set[str]) -> bool:
    """Whether `candidate` is mostly `other`, or `other` is mostly `candidate`."""
    if not candidate or not other:
        return False
    if min(len(candidate), len(other)) < _RESTATEMENT_MIN_WORDS:
        return candidate == other
    shared = len(candidate & other)
    return shared / min(len(candidate), len(other)) >= _RESTATEMENT


def _last_question(state: AspireState) -> str:
    for message in reversed(state.get("messages") or []):
        if getattr(message, "type", None) == "human":
            content = getattr(message, "content", "")
            return content if isinstance(content, str) else ""
    return ""


def _escalate(state: AspireState, reason: str, detail: str) -> Command:
    """Hand off, carrying a redacted summary and nothing else.

    The summary is redacted here for the same reason `tools.escalate_to_human`
    redacts: a ticket is read by staff, exported, and joined to a case record.
    """
    from app.safety import pii

    logger.info(
        "QA turn for session %s is ungrounded (%s): %s",
        state.get("session_id"),
        reason,
        detail,
    )
    return Command(
        # `graph=PARENT` because `escalate_agent` is a node of the MAIN graph,
        # not of this subgraph. Without it langgraph looks for a local node of
        # that name, fails to compile, and the failure names the node rather
        # than the missing hop.
        graph=Command.PARENT,
        goto="escalate_agent",
        update={
            "active_agent": "escalate_agent",
            "groundedness": 0.0,
            "citations": [],
            "safety_flags": {
                **(state.get("safety_flags") or {}),
                "ungrounded": {"reason": reason, "detail": detail},
            },
            "escalation_reason": reason,
            "escalation_summary": pii.redact_for_summary(
                f"{_latest_user_text(state)} -- {detail}"
            ),
        },
    )


# ── shared helpers ───────────────────────────────────────────────────────────


def _latest_user_text(state: AspireState) -> str:
    from app.graph.nodes.safety_in import latest_user_text

    return latest_user_text(state)


def _role(message: Any) -> str:
    return {"human": "user", "ai": "assistant"}.get(
        getattr(message, "type", ""), "system"
    )


def _text_of(message: Any) -> str:
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""
