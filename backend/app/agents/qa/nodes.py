"""The five nodes of the Q&A subgraph."""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable, Sequence
from typing import Any, Final, NamedTuple

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import Command

from app.config import get_settings
from app.context.session_context import conversation_reference
from app.graph.state import AspireState, Citation, KBChunk
from app.messages import text_of
from app.schemas.directives import CHIP_LABEL_CHARS, CITATION_ID

logger = logging.getLogger(__name__)


# ── rewrite_query ────────────────────────────────────────────────────────────

REWRITE_SYSTEM = (
    "Rewrite the last user message into a standalone search query. Resolve "
    "pronouns and anything left out, using the conversation for context. Keep "
    "the user's own words wherever you can -- you are preparing a search, not "
    "improving a question. Reply with the query and nothing else. If the "
    "message already stands alone, repeat it unchanged."
)

#: How many turns of context the rewriter sees.
REWRITE_WINDOW = 4


def _rewrite_system(locale: str) -> str:
    """The rewriter instruction, plus translation when the corpus cannot follow.

    `knowledge_base.csv` is English. A Spanish question embedded against English
    rows scores lower than the same question in English, and below
    `qa_relevance_floor` `ground_check` returns `no_context` -- so the bot says
    it has nothing, politely, in Spanish, with no error in the logs. It looks
    like an empty knowledge base and it is not.

    The standard answer for a corpus written in one language is to search in the
    corpus's language and answer in the reader's. Nothing about retrieval,
    embeddings or the floor changes; only the search string does.
    """
    if locale == "en":
        return REWRITE_SYSTEM
    return (
        REWRITE_SYSTEM
        + "\n\nThe material you are searching is written in English, so write "
        "the query in English however the message was written. This overrides "
        "keeping the reader's own words. It is a search string and nobody will "
        "see it -- the answer itself is written in the reader's language."
    )


def make_rewrite_query(invoke=None):
    """Resolve pronouns and ellipsis before embedding."""

    async def rewrite_query(state: AspireState) -> dict[str, Any]:
        messages = state.get("messages", [])
        original = _latest_user_text(state)
        if not original:
            return {}

        # An opening question has no context to resolve against, so the rewrite
        # call is skipped -- unless it also has to be translated. The FIRST
        # Spanish question is exactly how the demo starts, and skipping it there
        # searched the English corpus in Spanish and found nothing.
        needs_translation = str(state.get("locale") or "en") != "en"
        if invoke is None or (len(messages) <= 1 and not needs_translation):
            return {"qa_query": original}

        context = "\n".join(
            f"{_role(message)}: {text_of(message)}"
            for message in messages[-(REWRITE_WINDOW + 1) : -1]
        )
        try:
            rewritten = (
                await invoke(
                    _rewrite_system(str(state.get("locale") or "en")),
                    f"{context}\n\nuser: {original}",
                )
            ).strip()
        except Exception:
            logger.warning("Query rewrite failed; searching the original.", exc_info=True)
            rewritten = original

        # Empty, or vastly longer than the question, means the rewrite went wrong.
        if not rewritten or len(rewritten) > len(original) * 6 + 80:
            rewritten = original

        if rewritten != original:
            # Shape, not text.
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
    """Reciprocal rank fusion over several ranked id lists."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for position, identifier in enumerate(ranking, start=1):
            scores[identifier] = scores.get(identifier, 0.0) + 1.0 / (k + position)
    return scores


class CorpusRow(NamedTuple):
    """One knowledge-base row as the lexical side sees it.

    A tuple, and the first two fields are still `(kb_id, content)`, because that
    is the shape the eval harness and the tests hand in and there is no reason
    to make them carry provenance they do not have. `corpus_rows` widens either
    form to this one.
    """

    kb_id: str
    content: str
    #: The row's stored metadata, `source_url` included. Empty when the caller
    #: supplied the short form, which costs the citation its link and nothing else.
    metadata: dict[str, Any]


def corpus_rows(rows: Iterable[Any]) -> list[CorpusRow]:
    """`(id, text)` or `(id, text, metadata)` rows, widened to `CorpusRow`."""
    out: list[CorpusRow] = []
    for row in rows:
        stored = row[2] if len(row) > 2 else None
        out.append(CorpusRow(str(row[0]), str(row[1]), dict(stored or {})))
    return out


#: Built indexes, by whatever key the caller says identifies this corpus.
#:
#: Tokenising ~706 rows and constructing `BM25Okapi` ran on every question, on
#: the critical path. Measured on this machine: 114-200 ms warm, half a second
#: cold, for a corpus that changes only when `ingest` runs.
_INDEXES: dict[str, tuple[int, Any]] = {}


def _index_for(corpus: Sequence[Any], cache_key: str | None):
    """The BM25 index for this corpus, built once when the caller names it."""
    from rank_bm25 import BM25Okapi

    if cache_key is not None:
        # The row count guards against a key that outlives its corpus -- a
        # cheap check, and the failure it prevents is silent wrong answers.
        cached = _INDEXES.get(cache_key)
        if cached is not None and cached[0] == len(corpus):
            return cached[1]

    # Indexed positionally, so a row carrying metadata tokenises the same as one
    # that does not: only the id and the text have ever fed the index.
    tokenised = [_tokens(f"{row[0]} {row[1]}") for row in corpus]
    if not any(tokenised):
        return None

    index = BM25Okapi(tokenised)
    if cache_key is not None:
        _INDEXES[cache_key] = (len(corpus), index)
    return index


def forget_indexes() -> None:
    """Drop every built index. Called by `ingest` after it rewrites the table."""
    _INDEXES.clear()


def bm25_rank(
    query: str,
    corpus: Sequence[Any],
    top: int,
    *,
    cache_key: str | None = None,
) -> list[str]:
    """BM25 over `(id, text)` pairs, or over `CorpusRow`s.

    Without a `cache_key` the index is built fresh, which is what the offline
    eval harness wants: it drives this directly over a CSV sample and has no
    corpus identity to speak of.
    """
    if not corpus:
        return []

    index = _index_for(corpus, cache_key)
    if index is None:
        return []
    scores = index.get_scores(_tokens(query))
    ordered = sorted(
        range(len(corpus)), key=lambda position: scores[position], reverse=True
    )
    return [corpus[position][0] for position in ordered[:top] if scores[position] > 0]


_WORD = re.compile(r"[a-z0-9$]+")


def _tokens(text: str) -> list[str]:
    """Lowercase alphanumeric runs, keeping `$` so "EC$500" survives."""
    return _WORD.findall(text.lower())


def make_hybrid_retrieve(search=None, corpus=None):
    """Dense and BM25 together, fused by RRF."""

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
                # A dense failure is survivable BECAUSE there is a second retriever.
                logger.warning("Dense retrieval failed; BM25 only.", exc_info=True)

        rows: list[CorpusRow] = []
        if corpus is not None:
            try:
                rows = corpus_rows(await corpus(audience))
            except Exception:
                logger.warning("Could not load the corpus for BM25.", exc_info=True)

        dense = [chunk for chunk in dense if _permitted(chunk, audience)]
        by_id: dict[str, KBChunk] = {chunk.kb_id: chunk for chunk in dense}

        # BM25 searches the whole audience-permitted corpus, not a subset of the dense hits.
        # Keyed by audience and corpus fingerprint, so the index is built once
        # per corpus rather than once per question.
        from app.cache import corpus_fingerprint

        try:
            key: str | None = f"{audience}:{corpus_fingerprint()}"
        except Exception:  # pragma: no cover - no CSV on this box
            key = None
        lexical = bm25_rank(query, rows, settings.qa_retrieve_k, cache_key=key)
        # By row rather than by text: a lexical-only hit becomes a citation, and
        # a citation with no metadata is a source the reader cannot see. It used
        # to be built from the text alone, so every BM25 answer cited a row with
        # no question, no title and no link.
        row_by_id = {row.kb_id: row for row in rows}
        for identifier in lexical:
            if identifier in by_id:
                continue
            row = row_by_id.get(identifier)
            stored = dict(row.metadata) if row else {}
            by_id[identifier] = KBChunk(
                kb_id=identifier,
                title=str(stored.get("question") or stored.get("title") or ""),
                content=row.content if row else "",
                source="bm25",
                source_url=str(stored.get("source_url") or ""),
                metadata=stored,
            )

        rankings = [[chunk.kb_id for chunk in dense], lexical]
        fused = rrf_fuse(rankings, k=settings.qa_rrf_k)
        ranked = sorted(fused, key=lambda identifier: -fused[identifier])

        # The best RRF score this fusion could produce: rank one in every ranking.
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
                        # `relevance` is NOT touched.
                        "source": "fused",
                    }
                )
            )

        # The QUERY IS NOT LOGGED, and that is the point of this shape.
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
    """Which corpus slice this agent may see."""
    return {
        "qa_agent_limited": "youth",
        "qa_agent_public": "public",
    }.get(str(state.get("active_agent")), "all")


#: The corpus's own audience vocabulary, mapped onto the two filtered slices.
AUDIENCE_TAGS: dict[str, frozenset[str]] = {
    "public": frozenset({"general", "student", "child", "parent", "teacher"}),
    "youth": frozenset({"general", "student", "child", "parent", "teacher"}),
}


def _permitted(chunk: KBChunk, audience: str) -> bool:
    """Whether this chunk may be shown to this audience."""
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
    """Narrow the fused list to the few chunks the model actually reads."""

    async def rerank(state: AspireState) -> dict[str, Any]:
        chunks = list(state.get("retrieved") or [])
        if not chunks:
            return {}
        top = get_settings().qa_rerank_k

        if score is None:
            return {"retrieved": chunks[:top], "qa_related": chunks[top:]}

        query = state.get("qa_query") or _latest_user_text(state)
        try:
            scores = await score(query, chunks)
        except Exception:
            logger.warning("Reranking failed; keeping the fused order.", exc_info=True)
            return {"retrieved": chunks[:top], "qa_related": chunks[top:]}

        paired = sorted(zip(chunks, scores), key=lambda pair: -pair[1])
        return {
            "retrieved": [
                chunk.model_copy(update={"score": float(value)})
                for chunk, value in paired[:top]
            ],
            # What the cut dropped, still ranked -- the near-miss questions the chips offer.
            "qa_related": [chunk for chunk, _ in paired[top:]],
        }

    return rerank


# ── generate ─────────────────────────────────────────────────────────────────

#: The half of the role card that never varies. Grounding is not a style choice.
_QA_ROLE_HEAD = """YOUR JOB THIS TURN
Answer a factual question about the ASPIRE programme from what you have been
given with the question.

GROUNDING (non-negotiable)
- Answer ONLY from what you were given. If it does not contain the answer, say
  so plainly and name who does -- never fill a gap from anything else you know.
- Every figure, date, amount and rule you state must be there in front of you.
  Do not round, convert, average or infer one.
- Cite what you used by its [ASP-xxx] id, inline, right after the fact it
  supports. An answer with no citation will not be served.
- State facts, never your source. The reader cannot see what you were given and
  does not know it exists, so any sentence describing what it does or does not
  say reads as a report on a search rather than an answer. Where something is
  missing, the honest sentence is "I do not have that" followed by who does --
  never a description of what you looked at.

"""

#: How much of what was retrieved actually belongs in the answer, per persona.
#:
#: This block used to be one persona-blind instruction telling every reader's
#: answer to be thorough, use every bearing extract and structure a longer
#: answer. It is the strongest length instruction in the QA prompt, so it was
#: arguing with Stella's "about eight words" from a stronger position and
#: winning: the persona cards differed and the answers did not. The grounding
#: rules above are identical for everyone; only the shape below moves.
_QA_DEPTH: dict[str, str] = {
    "stella": """DEPTH AND COMPLETENESS
- Answer the one thing she asked. Not the conditions, not the exceptions, not
  what happens if. Those are true and they are not for her.
- Two or three short sentences. No bullets and no headings -- a list is a form,
  and she is having a conversation.
- If a money word is unavoidable, say what it means in the same breath.
- If the honest answer needs a grown-up, say so kindly and stop.""",
    # A row of his own, because the default here is `nova` -- the fullest block,
    # written for a teacher. Without this line Kaleb takes his key to the
    # `.get`, misses, and a nine-year-old is answered in an educator's register.
    # He is between Skye and Zion and belongs to neither: more than her two or
    # three sentences, and none of Zion's conditions.
    "kaleb": """DEPTH AND COMPLETENESS
- Answer what he asked, then the one thing that would change it. Not every
  condition -- he will stop reading, and the one that matters gets lost.
- Three or four sentences. Show the arithmetic when there is arithmetic: he is
  the reader who wants to see how the number was reached.
- Say what a money word means the first time it appears, then use it plainly.
- If the honest answer needs a grown-up, say so and say why, without softening
  it into something he can tell is softened.""",
    "orion": """DEPTH AND COMPLETENESS
- Give the direct answer first, then only the conditions that would actually
  change what he does. Leave the rest out.
- If the question is how or why something works, join what you have into one
  chain of cause and effect and show the arithmetic once. Three cited facts
  sitting next to each other is not an answer to a "how" question.
- One worked example in EC$ where you have the figures for it.
- Four or five sentences. Bullets only for a genuine list of steps.""",
    "aurora": """DEPTH AND COMPLETENESS
- Lead with the answer she can act on. Then the documents, amounts, deadlines
  and next step you can support -- and stop.
- Where the answer IS a list of documents or steps, use `-` bullets and let the
  list be the whole answer.
- Do not explain a money concept unless she asked how something works.
- Name the exception only when it could apply to her.""",
    "nova": """DEPTH AND COMPLETENESS
- Be thorough. Use everything you were given that bears on the question: give
  the direct answer first, then the conditions, exceptions, amounts, deadlines
  and next steps you can support.
- When several facts together answer the question, weave them into one
  coherent, complete answer rather than answering from only one.
- Explain any programme or money term the moment you use it.
- Structure a longer answer: a direct opening sentence, short paragraphs, and
  `-` bullets for lists of documents, steps or rules.
- Where a rule has an exception, state the exception -- this reader will be
  asked about it.
- Close with the one thing the reader should do next, where you have one.
  Never pad; every sentence must carry a fact you were given.""",
    "guest": """DEPTH AND COMPLETENESS
- Give the direct answer in the first sentence, then the one or two details that
  change what the reader does next.
- When several facts bear on the question, join them into one answer rather
  than listing them separately.
- Explain any programme or money term in half a clause the first time you use it.
- Two to four sentences. `-` bullets only for a real list of documents or steps.
- Close with the next step when you have one.""",
}

#: Which block an unrecognised persona gets: the fullest one, which is what this
#: card said for every reader before it was split. Keeps the constant below
#: byte-identical to what shipped.
_QA_DEPTH_DEFAULT = "nova"


def qa_agent_role(persona: str | None) -> str:
    """The QA role card for this reader: fixed grounding, persona-shaped depth."""
    key = (persona or "").strip().lower()
    return _QA_ROLE_HEAD + _QA_DEPTH.get(key, _QA_DEPTH[_QA_DEPTH_DEFAULT])


#: The QA agent's role card, for callers that do not know the persona.
QA_AGENT_ROLE = qa_agent_role(None)

#: What "Explain it simply" adds to a FACTUAL turn, on top of the shared text.
#:
#: The shared instruction protects the substance; this protects the two things
#: that are specific to a grounded answer and that a simplifying pass is most
#: likely to throw away. `ground_check` declines an answer with no citation, so
#: dropping the markers does not produce a simpler answer -- it produces no
#: answer at all.
_SIMPLE_MODE_QA_EXTRA = (
    " Keep every [ASP-xxx] citation marker exactly where it belongs, and keep "
    "every figure, date and amount as written. Simplifying means shorter "
    "sentences and plainer words, not fewer facts and not rounder numbers."
)

#: Legacy single-string prompt, kept for callers that build their own messages.
GENERATE_SYSTEM = """You answer questions about the ASPIRE savings programme.

Rules, in order of importance:
1. Answer ONLY from the numbered reference material below. If it does not
   contain the answer, say so plainly -- do not fill the gap from anything you
   know.
2. Every figure, date, amount and rule in your answer must be there in front of
   you. Do not round, convert, average or infer one.
3. Cite what you used by its [ASP-xxx] id, inline.
4. Write for the reader described below. Be thorough and complete: use
   everything that bears on the question, explain terms as you use them, and
   structure longer answers with short paragraphs and `-` bullets. No links.
5. State facts, never your source. The reader cannot see any of this and does
   not know it exists, so a sentence about what it does or does not say reads
   as a report on a search rather than an answer. Where something is missing,
   say "I do not have that" and name who does.

{context}
"""


def make_generate(invoke=None):
    """Write the answer from the retrieved chunks and nothing else."""

    async def generate(state: AspireState) -> dict[str, Any]:
        chunks = list(state.get("retrieved") or [])
        question = _latest_user_text(state)

        # An aside needs no context and no generation; `ground_check` emits it.
        if _small_talk_reply(state) is not None:
            return {"groundedness": 1.0}

        if not chunks:
            # No context means nothing to ground on, so never generate here.
            logger.info("Nothing retrieved; escalating rather than answering.")
            return {"groundedness": 0.0}

        if invoke is None:
            return {"groundedness": 0.0}

        messages = _generation_messages(state, question, chunks)
        text = await invoke(messages)
        return {"messages": [AIMessage(content=text)]}

    return generate


def _simple_mode_instruction(state: AspireState) -> str | None:
    """The extra system line for a turn the reader asked to have simplified."""
    if not state.get("simple_mode"):
        return None
    from app.prompts import SIMPLE_MODE_INSTRUCTIONS

    return f"{SIMPLE_MODE_INSTRUCTIONS.strip()}{_SIMPLE_MODE_QA_EXTRA}"


#: What a story has to be, per persona. The reader asked for this, so it is
#: allowed to be a story -- but it is still ASPIRE, and it still cannot invent
#: programme facts.
_STORY_BY_PERSONA: dict[str, str] = {
    "stella": (
        "Tell a SHORT story, five or six sentences, for a child aged five to "
        "twelve. One child, one problem about money, one thing they decide. "
        "Simple words and short sentences. End with the one idea it teaches, in "
        "a single line."
    ),
    "kaleb": (
        # Same reason as the depth block: the fallback here is `guest`, the
        # mixed-audience shape, which is nobody's voice in particular.
        "Tell a short story, six to eight sentences, for a child aged nine to "
        "twelve. One character, one money decision, and a consequence that "
        "follows from it rather than being announced. Plain words, and show the "
        "sums if there are sums. End with what it cost or earned them."
    ),
    "orion": (
        "Tell a story for a teenager: eight to twelve sentences, a character "
        "with a real decision to make and a consequence that follows from it. "
        "Name the money idea it turns on and end by saying what it cost or "
        "earned them."
    ),
    "aurora": (
        "Tell a short, plain story a guardian could read aloud to their child, "
        "and follow it with one line on what to talk about afterwards."
    ),
    "nova": (
        "Write a short teaching story an educator could use with a class, then "
        "add one line naming the concept and one discussion question."
    ),
    "guest": (
        "Tell a short story, six to ten sentences, with one clear money idea in "
        "it. End by naming that idea in a line."
    ),
}


def _story_instruction(state: AspireState) -> str | None:
    """The extra system line for the one turn that tells a story.

    Set only by `cards._story_turn`, which is reached only when the reader typed
    a request for one. There is no path here from the planner or the tutor, so
    the assistant cannot start a story at somebody who was asking a question.
    """
    topic = (state.get("story_topic") or "").strip()
    if not topic:
        return None
    persona = str(state.get("persona") or "guest")
    shape = _STORY_BY_PERSONA.get(persona, _STORY_BY_PERSONA["guest"])
    return (
        f"The reader has asked for a story about: {topic}\n"
        f"{shape}\n"
        "Set it in Saint Kitts and Nevis and use EC dollars. Invent the "
        "characters freely; do NOT invent anything about the ASPIRE programme "
        "itself -- no amounts, ages, dates or rules that are not in the "
        "material you were given. Do not add a quiz, a game or a question at "
        "the end unless the shape above asks for one."
    )


#: What a self-contained sum adds to the prompt.
#:
#: Added ONLY on a turn `is_self_contained_sum` recognised, so the standing
#: grounding rules are byte-identical on every programme question. This cannot
#: loosen an ASPIRE answer because it is never in the prompt for one.
_SELF_CONTAINED_INSTRUCTION = (
    "This question carries its own figures and is not about the ASPIRE "
    "programme, so the reference material below cannot answer it and is not "
    "meant to. Work it out from the numbers the reader gave you, show the "
    "steps briefly, and give the answer. Do not decline it, and do not cite "
    "anything for it. The grounding rules still hold for anything you say "
    "about ASPIRE itself."
)


def _self_contained_instruction(state: AspireState) -> str | None:
    """The extra system line for a sum the reader set up themselves.

    Guarded on retrieval exactly as `ground_check` is, and for the same reason:
    a question whose premise the corpus DOES state -- "if the minimum deposit is
    EC$25, what do 4 of them cost?" -- must still be answered with its citation.
    Telling the model not to cite here and then requiring a citation there would
    put the two halves of this fix in disagreement on the same turn.
    """
    question = _latest_user_text(state)
    query = state.get("qa_query") or question
    if not is_self_contained_sum(question, query):
        return None
    chunks = list(state.get("retrieved") or [])
    best = max((chunk.relevance for chunk in chunks), default=0.0)
    if best >= get_settings().qa_relevance_floor:
        return None
    return _SELF_CONTAINED_INSTRUCTION


def _shaping_instructions(state: AspireState) -> str | None:
    """Every extra system line this turn earns, joined. None when there are none."""
    lines = [
        line
        for line in (
            _simple_mode_instruction(state),
            _story_instruction(state),
            _self_contained_instruction(state),
        )
        if line
    ]
    return "\n\n".join(lines) or None


def _generation_messages(
    state: AspireState, question: str, chunks: list[KBChunk]
) -> list[Any]:
    """The full prompt: GLOBAL + persona card + role, history, then the question with extracts."""
    context = state.get("context")
    try:
        from app.context.session_context import SessionContext

        if isinstance(context, SessionContext):
            from app.prompting.builder import build_messages

            # History already carries this turn's question; drop it so the model reads it once.
            turns = list(context.recent_turns)
            if turns and turns[-1].role == "user" and turns[-1].text.strip() == question.strip():
                turns = turns[:-1]
            return build_messages(
                context=context.model_copy(update={"recent_turns": turns}),
                agent_role=qa_agent_role(context.persona),
                user_text=question,
                retrieved=chunks,
                extra_instruction=_shaping_instructions(state),
            )
    except Exception:
        # A broken context must not cost the answer; fall through to the plain prompt.
        logger.warning("Could not build the layered QA prompt; using the plain one.", exc_info=True)

    # Same scrubbing as the layered prompt: this fallback is reached when the
    # layered one could not be built, which is no reason to start showing the
    # model the URLs the other path takes off.
    from app.sources import without_provenance

    block = "\n\n".join(
        f"[{chunk.kb_id}] {without_provenance(chunk.content)}" for chunk in chunks
    )
    system = GENERATE_SYSTEM.format(context=block)
    audience = (
        f"Reader: age band {state.get('age_band')}, persona "
        f"{state.get('persona')}, language {state.get('locale')}."
    )
    # The fallback is reached when the layered prompt could not be built, which
    # is no reason for the reader's own request to be the thing that gets lost.
    shaping = _shaping_instructions(state)
    if shaping:
        audience = f"{audience}\n{shaping}"
    return [
        SystemMessage(content=f"{system}\n{audience}"),
        HumanMessage(content=question),
    ]


# ── ground_check ─────────────────────────────────────────────────────────────

#: Numbers and money amounts in an answer.
_FIGURE = re.compile(r"(?:EC\$|US\$|\$)?\d[\d,]*(?:\.\d+)?%?")

#: A bracketed reference -- `[ASP-042]`, `[FIN-007]`. The same shape
#: `ground_check` reads to decide which rows an answer cited.
_CITATION_MARKER = re.compile(rf"\[{CITATION_ID}\]")

#: Small integers used as counts or ordinals; never a factual claim needing attribution.
_INNOCUOUS = frozenset({"1", "2", "3", "4", "5", "6", "7", "8", "9", "10"})

#: Phrases that assert a rule. A sentence containing one must cite something.
_POLICY = re.compile(
    r"\b(?:must|required|not allowed|cannot|may not|is eligible|are eligible"
    r"|deadline|minimum|maximum|entitled|guaranteed)\b",
    re.IGNORECASE,
)


def normalise_figure(text: str) -> str:
    """A figure reduced to its digits, so `EC$1,200.00` matches `1200`."""
    digits = re.sub(r"[^\d.]", "", text)
    if "." in digits:
        digits = digits.rstrip("0").rstrip(".")
    return digits.lstrip("0") or "0"


# ── questions that carry their own arithmetic ────────────────────────────────
#
# A word problem the reader supplied every figure for is not a claim about
# ASPIRE, will never appear in a row, and is declined by every gate below that
# asks "which row says this?".
#
# Measured, `qa/battle-plan/evidence/rsn-01-logic.md`: four of five word
# problems declined -- notebooks at 3 for EC$12, a bus leaving at 07:40,
# EC$500 at 2% simple interest -- each one replaced whole by "I do not have an
# answer for that. The ASPIRE team can answer it". The model had done the sum
# correctly; `_ungrounded` threw the answer away and served a decline instead.
#
# The predicate is the whole safety of this and is conservative on both sides.
# The question must carry at least two figures of its own AND an arithmetic
# cue AND name nothing of ASPIRE's. Anything that fails one of those three is
# an ordinary programme question and keeps every gate it has today.

#: Words that mean the reader is asking for a calculation, not a rule.
_ARITHMETIC_CUE = re.compile(
    r"\b(?:how\s+much|how\s+many|how\s+long|how\s+old|how\s+far|what\s+time"
    r"|altogether|in\s+total|sum\s+of|left\s+over|left|cost|costs|each|per"
    r"|apiece|add|plus|minus|times|twice|half|double|multiply|divide|split"
    r"|share[sd]?\s+between|average|grows?\s+by|older|younger"
    r"|interest\s+a\s+year|percent|%)\b",
    re.IGNORECASE,
)

#: Anything that makes a question ASPIRE's rather than arithmetic's.
#:
#: Deliberately wide. A false positive here costs nothing -- the question keeps
#: exactly the gates it has today -- while a false negative lets a programme
#: claim through ungrounded, which is the one outcome this file exists to stop.
_NAMES_THE_PROGRAMME = re.compile(
    r"\b(?:aspire|programme|program|eligib\w*|enrol\w*|enroll\w*|registrat\w*"
    r"|register|apply|applicant|application|qualify|qualifie[sd]|document\w*"
    r"|passport|birth\s+certificate|national\s+id|deadline|branch|office"
    r"|hotline|contact|st\.?\s*kitts|nevis|anguilla|government|ministry"
    r"|my\s+account|my\s+child|my\s+application|the\s+scheme)\b",
    re.IGNORECASE,
)


def is_self_contained_sum(*questions: str) -> bool:
    """Whether the reader set up a sum that no row was ever going to answer.

    True only when the question carries its own figures, asks for a
    calculation, and names nothing of the programme's. Every one of the three
    is required, and each is tested against BOTH the reader's own words and the
    rewritten `qa_query` -- the rewrite is a model call, and a rewrite that
    drags ASPIRE into an arithmetic question must not be able to unlock this,
    nor a rewrite that drops ASPIRE out of a programme one.
    """
    asked = [text for text in questions if text and text.strip()]
    if not asked:
        return False

    # Naming the programme anywhere disqualifies the turn.
    if any(_NAMES_THE_PROGRAMME.search(text) for text in asked):
        return False

    # The reader's own words are what the figures must come from; a rewrite
    # cannot manufacture the premises that make a question self-contained.
    reader = asked[0]
    if len(_FIGURE.findall(reader)) < 2:
        return False
    return bool(_ARITHMETIC_CUE.search(reader))


def _figures_in_our_own_contacts() -> set[str]:
    """The digits of ASPIRE's own phone number, hotline and opening hours.

    They reach the model from the prompt rather than from a retrieved extract,
    so `unattributed_figures` reads `+1 (869) 667-5566` as three inventions --
    `869`, `667`, `5566` -- and declines the answer for offering the number the
    prompt just told it to offer. Measured: three declines in one thirteen-turn
    run, every one of them an answer that had correctly given the contact
    details, each then having a decline welded onto the end of it.

    The same shape as the PII exemption in `safety/pii.py`, and for the same
    reason: these are the programme's own published facts, not a model's
    invention, and a check that cannot tell the difference turns a correct
    answer into a refusal.
    """
    from app.config import get_settings

    settings = get_settings()
    supplied = " ".join(
        (
            settings.aspire_contact_phone,
            settings.aspire_contact_phone_alt,
            settings.aspire_contact_office,
            settings.aspire_contact_website,
        )
    )
    return {normalise_figure(match.group(0)) for match in _FIGURE.finditer(supplied)}


#: How far a figure may be from the ones it was given. One operation, no more.
#:
#: A worked example is arithmetic ON the extracts, not a claim about the
#: programme, and a gate that cannot tell the two apart declines the answer for
#: doing the sum it was asked for. Measured on "if the minimum deposit is EC$25,
#: what do 4 of them cost?": the answer cited the row correctly, stated EC$100,
#: and was thrown away whole.
#:
#: The exemption is bounded three ways, and all three matter.
#:
#: ONE operation. Not a chain, so a search cannot wander to an arbitrary value.
#:
#: Both operands must be QUANTITIES the reader was actually given -- stated in a
#: retrieved extract, or written in their own question. A figure from nowhere
#: has nothing to be built out of.
#:
#: And at least one operand must come from the QUESTION. This is what keeps the
#: exemption to the case it exists for. "What do 4 deposits cost?" is a reader
#: asking for a calculation on a figure they supplied; "how much does ASPIRE
#: pay?" is a factual question, and there an amount the corpus does not contain
#: is exactly as suspect as it was before -- the exemption does not apply to it
#: at all. Without this clause a four-chunk retrieval yields enough operands to
#: derive several hundred values, and a fabricated amount could land on one.
#:
#: None of it is a substitute for grounding: the answer must still cite a
#: retrieved extract to be served, which is checked separately and not relaxed.
#: A runaway guard, not a policy. `_derivation` is |asked| x |given| and |asked|
#: is one or two figures from a question, so this is never the binding
#: constraint on a real turn -- `ground_check` reads the four reranked chunks,
#: which yield a dozen or so quantities once the bookkeeping is scrubbed off.
_DERIVATION_OPERAND_CAP = 64

#: Money is stated to the cent, so a derived figure has to land on one.
_DERIVATION_TOLERANCE = 0.005


def _numeric(value: str) -> float | None:
    """A normalised figure as a number, or None when it will not parse."""
    try:
        return float(value)
    except ValueError:
        return None


def _operands(values: set[str]) -> list[float]:
    """Figures as numbers, smallest first, capped.

    Ordered numerically rather than by their string form -- sorting `{"1000",
    "25"}` as text puts "1000" first for no reason anybody chose -- and
    ASCENDING, so that if the cap ever bites it drops the largest figures
    rather than the small counts a worked example multiplies by. Losing the `4`
    from "what do 4 of them cost?" would break the exemption at exactly the
    case it exists for.
    """
    numbers = sorted(
        n for n in (_numeric(value) for value in values) if n is not None
    )
    return numbers[:_DERIVATION_OPERAND_CAP]


def _derivation(
    target: float, asked: list[float], given: list[float]
) -> tuple[float, float] | None:
    """The pair of figures one arithmetic step lands on `target` from, or None.

    `asked` is figures from the reader's question, `given` is every figure
    available. One operand is drawn from each, so the reader's own number is
    always part of the sum.

    A derivation must produce a NUMBER THAT IS NOT ONE OF ITS OWN OPERANDS.
    Without that clause the identity operations hand back whatever they were
    given -- `9999 * 1` is 9999, and a corpus row containing a `1` anywhere
    would make any figure the reader named "derivable" from itself. That is not
    a calculation; it is the check agreeing with the question.

    The operands are returned rather than a bare yes, because which figures did
    the work decides which of them the answer may restate. See
    `unattributed_figures`.
    """
    for a in asked:
        for b in given:
            if a == b:
                # `given` contains `asked`, so without this a reader's single
                # figure is both operands and licenses its own double and its
                # own square as programme facts.
                continue
            candidates = [a + b, a - b, b - a, a * b, a * b / 100.0]
            if b:
                candidates.append(a / b)
            if a:
                candidates.append(b / a)
            for candidate in candidates:
                if abs(candidate - target) >= _DERIVATION_TOLERANCE:
                    continue
                if (
                    abs(candidate - a) < _DERIVATION_TOLERANCE
                    or abs(candidate - b) < _DERIVATION_TOLERANCE
                ):
                    continue
                return a, b
    return None


def unattributed_figures(
    answer: str,
    chunks: list[KBChunk],
    conversation_ref: str = "",
    question: str = "",
) -> list[str]:
    """Figures in the answer that appear in no chunk and follow from nothing given.

    `conversation_ref` is the `ASP-#####` the persona cards ask the reader to
    quote. It reaches the model from the prompt rather than from an extract, so
    without it here the five digits of a reference the prompt just supplied read
    as an invention -- the same shape as the contact-number exemption above, and
    a decline welded onto an answer that had done exactly as it was told.

    `question` is the reader's own words, and figures in it are theirs to
    COMPUTE WITH -- not to have asserted back. "If I save EC$10 every week for
    5 weeks, how much will I have?" is answered from what they supplied and
    from arithmetic; the corpus was never going to contain EC$50, and a gate
    that demanded it declined the answer. "Does ASPIRE pay EC$9,999?" answered
    "yes, EC$9,999" is the same figure making a claim it has not earned, and
    that one is still caught.
    """
    from app.sources import without_provenance

    # Measured against what the model was SHOWN, not against the stored row.
    # `ingest` appends the CSV's bookkeeping columns to a row's text, so the raw
    # content ends `as_of: 2026-07-30` -- putting 7, 30 and 2026 into nearly
    # every retrieval as figures the model never actually saw. The prompt is
    # built from the scrubbed text; so is this.
    corpus = " ".join(without_provenance(chunk.content) for chunk in chunks)

    # Quantities: what the extracts state, and what the reader put in their own
    # question. `_INNOCUOUS` is deliberately not among them -- with 1 to 10 in
    # the operand pool, 9 divided by 2 makes 4.5 and the gate stops catching
    # anything. Nor are the contact numbers: a phone number is not a quantity,
    # and its digits would derive half the number line.
    stated = {normalise_figure(m.group(0)) for m in _FIGURE.finditer(corpus)}
    asked = (
        {normalise_figure(m.group(0)) for m in _FIGURE.finditer(question)}
        if question
        else set()
    )

    # `asked` is NOT part of `known`, and that distinction is the whole safety
    # of it. A figure the reader typed may be COMPUTED WITH; it may not be
    # asserted back as fact. Otherwise "ASPIRE pays EC$9,999, right?" answered
    # "Yes, EC$9,999" passes a gate whose entire job is to catch exactly that.
    known = stated | _figures_in_our_own_contacts()
    if conversation_ref:
        known |= {
            normalise_figure(match.group(0))
            for match in _FIGURE.finditer(conversation_ref)
        }

    from_question = _operands(asked)
    every_quantity = _operands(stated | asked)

    # A citation marker is not a figure.
    #
    # `_FIGURE` matches the digits inside `[ASP-011]`, and the role card
    # REQUIRES the model to write that marker -- so the gate was reading the
    # answer's own citation as an invented number. It never surfaced before
    # because `known` was built from the raw row text, whose `id: ASP-011`
    # bookkeeping line happened to license the marker; scrubbing that line for
    # the prompt took the accident away with it. Measured across all 706 corpus
    # rows, feeding each row's own answer back verbatim with a correct
    # citation: 684 of 706 were declined. Removed here rather than licensed,
    # because the marker is punctuation and never a claim.
    answer = _CITATION_MARKER.sub(" ", answer)

    # Pass one: which figures stand on their own, and which figures of the
    # reader's the answer actually WORKED WITH.
    unexplained: list[str] = []
    echoed: list[tuple[str, float | None]] = []
    #: Figures that were an operand of a derivation that landed.
    worked_with: list[float] = []

    for match in _FIGURE.finditer(answer):
        raw = match.group(0)
        value = normalise_figure(raw)
        target = _numeric(value)

        # Tested FIRST, and for every figure, because it answers a different
        # question from "may this be here": it answers "was this worked out".
        # "20% of EC$25 is EC$5" works out a five, and five is an innocuous
        # small integer -- so checking only the figures that had nowhere else
        # to come from would find no working in a worked example.
        pair = (
            _derivation(target, from_question, every_quantity)
            if target is not None and from_question
            else None
        )
        if pair is not None:
            worked_with.extend(pair)

        if value in _INNOCUOUS or value in known or pair is not None:
            continue
        if value in asked:
            # The reader's own figure, said back to them. Held aside rather
            # than allowed: see below.
            echoed.append((raw, target))
            continue
        unexplained.append(raw)

    # Pass two: an echo is licensed by having been PART OF the working.
    #
    # "20% of EC$50 is EC$10" restates two figures the reader supplied, and it
    # restates them as the working for a third the answer computed. That is not
    # a claim about the programme, and declining it would decline every worked
    # example a reader sets up.
    #
    # "Does ASPIRE pay EC$9,999?" answered "Yes, ASPIRE pays EC$9,999" restates
    # one figure and computes nothing with it. There the echo IS the claim, and
    # a gate that let a reader put a number into an answer by naming it in the
    # question would be worse than no gate at all.
    #
    # Per figure rather than per turn, so a turn that legitimately works one
    # sum out does not thereby license every other number the reader mentioned.
    for raw, target in echoed:
        if target is not None and any(
            abs(target - operand) < _DERIVATION_TOLERANCE for operand in worked_with
        ):
            continue
        unexplained.append(raw)
    return unexplained


#: English function words, removed before measuring coverage.
_STOPWORDS = frozenset(
    "a an and are as at be by can could do does did for from had has have how i "
    "if in is it its me my of on or our so than that the their them there they "
    "this to us was we were what when where which who whom why will with would "
    "you your".split()
)


#: How many DISTINCT content words must appear, on top of the fraction floor.
MIN_MATCHED_TERMS = 2


def matched_terms(query: str, chunks: list[KBChunk]) -> int:
    """How many distinct content words from the question appear in the chunks."""
    terms = {token for token in _tokens(query) if token not in _STOPWORDS}
    if not terms:
        return MIN_MATCHED_TERMS
    corpus = set(_tokens(" ".join(chunk.content for chunk in chunks)))
    return len(terms & corpus)


def required_terms(query: str) -> int:
    """How many matches this question needs."""
    terms = {token for token in _tokens(query) if token not in _STOPWORDS}
    return min(MIN_MATCHED_TERMS, len(terms)) if terms else 0


def lexical_coverage(query: str, chunks: list[KBChunk]) -> float:
    """What fraction of the question's content words the retrieved text contains."""
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
        # BEFORE every floor, not just the no-context one.
        aside = _small_talk_reply(state)
        if aside is not None:
            return aside

        chunks = list(state.get("retrieved") or [])
        messages = state.get("messages") or []
        answer = text_of(messages[-1]) if messages else ""

        if not chunks or not answer.strip():
            return _ungrounded(state, "no_context", "Nothing in the knowledge base matched.")

        query = state.get("qa_query") or _latest_user_text(state)

        # ── a sum the reader set up, and that the corpus has nothing to say to ──
        #
        # Sited after the empty-answer check, so a turn that generated nothing
        # still declines, and before all four grounding gates below, because
        # every one of them asks the same question -- which row says this? -- and
        # a sum of the reader's own numbers has no row and never will.
        #
        # BOTH conditions are required, and the second is what keeps this off
        # the turns that already work. "If the minimum deposit is EC$25, what do
        # 4 of them cost?" carries its own figures and names nothing of ASPIRE's
        # by vocabulary alone -- but retrieval finds the row that states the
        # EC$25, and that row IS the answer's source. `unattributed_figures`
        # already licenses the EC$100 as arithmetic on a retrieved quantity, so
        # the ordinary path serves it correctly WITH its citation. Bypassing
        # would have thrown that citation away; two tests in `test_citations`
        # say so by name.
        #
        # So the bypass fires only where the corpus genuinely has nothing:
        # retrieval below the floor AND a question the reader supplied every
        # premise for. That is the notebook question, and not the deposit one.
        #
        # This is the ONLY path that skips `unattributed_figures`, so it is
        # deliberately the narrowest gate in the file.
        best_relevance = max((chunk.relevance for chunk in chunks), default=0.0)
        if best_relevance < floor and is_self_contained_sum(
            _latest_user_text(state), query
        ):
            logger.info(
                "Session %s asked a self-contained sum and retrieval found "
                "nothing above %.3f; answering it rather than declining for "
                "want of a row.",
                state.get("session_id"),
                floor,
            )
            return Command(
                update={
                    "citations": [],
                    "groundedness": 1.0,
                    "active_agent": state.get("active_agent"),
                    "decline_streak": {},
                }
            )

        # ── direct evidence of grounding, read BEFORE the proxies for it ──
        #
        # The two floors below score the RETRIEVAL. Whether the answer is
        # actually grounded is a different question, and the checks further down
        # measure it: does it cite a retrieved extract, does it invent one, does
        # it state a figure no extract contains. Those are evidence; a cosine
        # score is a stand-in for evidence.
        #
        # Ordered floors-first, the stand-in overruled the real thing. Measured
        # across 27 turns, 5 declined on a retrieval score of 0.457-0.542 against
        # a 0.550 floor while carrying correct, cited answers -- including
        # "What is compound interest?" and a recall of something the reader had
        # said earlier in the same conversation, which is not a corpus question
        # at all and can never score against it. Each of those answers was
        # delivered with "I do not have an answer for that" welded onto the end.
        #
        # But a citation is not a licence: "how do I renew a fishing licence"
        # answered "At the fisheries office [ASP-006]" cites a retrieved id and
        # is wholly invented, and a hedge like "Probably [ASP-006]" against a
        # 0.05 chunk is not grounded in anything. Both have tests.
        #
        # So the dense floor splits in two. Below the HARD floor retrieval found
        # nothing and no citation rescues it. Between the hard floor and the
        # ordinary one the score is marginal -- 0.457 and 0.542 against 0.550 are
        # the same decision as 0.550, not a different one -- and there the direct
        # evidence decides. The lexical floor is untouched: it only runs when the
        # dense side never ran at all, which is the fishing-licence case.
        known = {chunk.kb_id for chunk in chunks}
        cited = {
            match.group(1)
            for match in re.finditer(rf"\[({CITATION_ID})\]", answer)
        }
        grounded_citations = cited & known

        # ── the primary floor: the dense retriever's real cosine relevance ──
        best = max((chunk.relevance for chunk in chunks), default=0.0)
        dense_seen = any(chunk.relevance > 0.0 for chunk in chunks)
        hard_floor = settings.qa_relevance_hard_floor
        if dense_seen and best < floor and (best < hard_floor or not grounded_citations):
            return _ungrounded(
                state,
                "below_relevance_floor",
                f"The closest chunk scored {best:.3f}, below the {floor:.3f} floor"
                + ("." if best < hard_floor else " and the answer cites no retrieved extract."),
            )

        # ── the lexical floor: English only, and only when the dense side never ran ──
        if str(state.get("locale") or "en") == "en":
            coverage = lexical_coverage(query, chunks)
            matched = matched_terms(query, chunks)
            needed = required_terms(query)
            if not dense_seen and (coverage < coverage_floor or matched < needed):
                return _ungrounded(
                    state,
                    "below_relevance_floor",
                    f"Only {coverage:.0%} of the question's words appear in the "
                    f"corpus ({matched} distinct term(s)); the floor is "
                    f"{coverage_floor:.0%} and {needed} term(s).",
                )

        reference = conversation_reference(str(state.get("session_id") or ""))
        # `_latest_user_text`, NOT `query`. `query` is `qa_query`, which
        # `rewrite_query` produced with a model call -- so passing it here would
        # let the LLM put a figure into the set the gate treats as supplied by
        # the reader, which is the model handing itself a licence. The reader's
        # own words are the only thing they can be said to have supplied.
        missing = unattributed_figures(
            answer, chunks, reference, _latest_user_text(state)
        )
        if missing:
            logger.warning(
                "Ungrounded figures %s in an answer for session %s; escalating.",
                missing[:5],
                state.get("session_id"),
            )
            return _ungrounded(
                state,
                "unattributed_figure",
                f"The answer stated {', '.join(missing[:3])}, which no extract contains.",
            )

        # ── attribution: an answer citing no retrieved extract is ungrounded ──
        # `known`, `cited` and `grounded_citations` are read above, before the
        # floors, because they decide whether those floors apply at all.
        if not grounded_citations:
            return _ungrounded(
                state,
                "uncited",
                "The answer cites no retrieved extract, so nothing supports it.",
            )

        # A citation to something not retrieved is worse than none: it is fabricated.
        #
        # The conversation reference is subtracted first. It wears the same
        # `ASP-` prefix as a knowledge-base row because the cards ask the reader
        # to quote it that way, and a model that brackets it out of habit was
        # having a correct answer thrown away as a fabricated citation.
        invented = cited - known - {reference}
        if invented:
            return _ungrounded(
                state,
                "invented_citation",
                f"The answer cited {sorted(invented)}, which was not retrieved.",
            )

        # Inline markers are stripped from the prose, so this panel is the only provenance.
        #
        # Built from the chunks the answer CITED, in retrieval order -- not from
        # everything retrieved. Ten rows can come back for a question that three
        # of them answer, and the seven the model did not use are not sources.
        citations = [
            citation_for(chunk)
            for chunk in chunks
            if chunk.kb_id in grounded_citations
        ]
        # The best chunk's calibrated relevance, or the fused score when dense never ran.
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
                # A resolved turn ends any run of unresolved ones.
                "decline_streak": {},
            }
        )

    return ground_check


def citation_for(chunk: KBChunk) -> Citation:
    """One retrieved row, as the reference a reader is shown.

    The only place a `Citation` is built from a chunk, so the naming and the
    URL validation happen once. Nothing here reads the answer: the model chose
    WHICH rows are cited, and the application decides what each one says about
    itself. That split is what stops a URL from ever being invented -- there is
    no path by which the model could supply one.
    """
    ref = chunk.provenance()
    if ref is None:
        # An answer can be perfectly grounded in a row whose source is missing
        # or unusable. It still cites, by id and by its own words; it just has
        # nothing to link to. `app.sources` has already logged why.
        logger.info(
            "Row %s was cited with no usable source; the citation carries no link.",
            chunk.kb_id,
        )
    return Citation(
        kb_id=chunk.kb_id,
        title=chunk.title,
        question=str(chunk.metadata.get("question") or "").strip(),
        snippet=snippet_of(chunk.content),
        source_url=ref.url if ref else "",
        site=ref.site if ref else "",
        page=ref.page if ref else "",
        domain=ref.domain if ref else "",
        updated=ref.updated if ref else "",
    )


#: How much of a cited row the sources panel shows.
SNIPPET_MAX_CHARS = 240

#: The `Answer:` line `ingest.row_to_document` writes, and any other column line.
_ANSWER_LINE = re.compile(r"^\s*answer\s*:\s*", re.IGNORECASE)
_FIELD_LINE = re.compile(r"^\s*[A-Za-z][A-Za-z0-9_ ]{0,30}\s*:\s")


def answer_text(content: str) -> str:
    """A row's answer without the column scaffolding, or the whole text if not QA-shaped."""
    lines = (content or "").splitlines()
    for index, line in enumerate(lines):
        if not _ANSWER_LINE.match(line):
            continue
        body = [_ANSWER_LINE.sub("", line).strip()]
        for following in lines[index + 1 :]:
            if _FIELD_LINE.match(following):
                break
            body.append(following.strip())
        text = " ".join(part for part in body if part).strip()
        if text:
            return text
    return " ".join((content or "").split())


def snippet_of(content: str) -> str:
    """The cited row's answer, cut at a word boundary rather than mid-syllable."""
    text = " ".join(answer_text(content).split())
    if len(text) <= SNIPPET_MAX_CHARS:
        return text
    cut = text[:SNIPPET_MAX_CHARS]
    space = cut.rfind(" ")
    return (cut[:space] if space > SNIPPET_MAX_CHARS // 2 else cut).rstrip(" ,;:-") + "…"


#: How many chips go under an answer: enough to offer a direction, few enough to scan.
FOLLOW_UP_CHIPS = 3

#: A chip's character cap, set from the corpus: 72 keeps 96% of the authored questions.
#: Taken from the wire schema rather than restated, so the builder and the thing that
#: validates it can never drift apart again.
CHIP_MAX_CHARS = CHIP_LABEL_CHARS


def follow_up_chips(
    state: AspireState, chunks: list[KBChunk], cited: set[str]
) -> list[str]:
    """More questions the corpus can answer, drawn from the reranked chunks then `qa_related`."""
    asked = _asked_questions(state)
    # What the answer covered, by question not by id: two rows can ask the same thing.
    covered = [
        _words(str(chunk.metadata.get("question") or chunk.title or ""))
        for chunk in chunks
        if chunk.kb_id in cited
    ]
    seen: list[set[str]] = []
    chips: list[str] = []

    for chunk in [*chunks, *(state.get("qa_related") or [])]:
        if chunk.kb_id in cited:
            continue
        question = str(chunk.metadata.get("question") or chunk.title or "").strip()
        if not question or len(question) > CHIP_MAX_CHARS:
            continue

        words = _words(question)
        if not words:
            continue
        # Near-duplicates too: against the thread, the answer's coverage, and this turn's chips.
        if any(_restates(words, other) for other in (*asked, *covered, *seen)):
            continue

        seen.append(words)
        chips.append(question)
        if len(chips) == FOLLOW_UP_CHIPS:
            break

    return chips


#: Above this overlap, two questions are the same question.
_RESTATEMENT = 0.75

#: Words that carry no topic, for telling one follow-up chip from another.
#:
#: Named apart from `_STOPWORDS` above, and that is a fix rather than a tidy-up.
#: Both were bound to the bare name `_STOPWORDS` at module level, so this one --
#: the later assignment -- won for the whole module, and `lexical_coverage`,
#: `matched_terms` and `required_terms` silently measured the coverage floor
#: with the chip list instead of the sixty-word list written for them. "have",
#: "if", "that", "they", "with" and "would" were all being counted as content
#: words a corpus row had to contain.
_CHIP_STOPWORDS = frozenset(
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
        if word.strip("?.!,;:'\"") and word.strip("?.!,;:'\"") not in _CHIP_STOPWORDS
    }


#: Below this many content words, containment stops meaning anything and only an exact match counts.
_RESTATEMENT_MIN_WORDS = 2


def _restates(candidate: set[str], other: set[str]) -> bool:
    """Whether `candidate` is mostly `other`, or `other` is mostly `candidate`."""
    if not candidate or not other:
        return False
    if min(len(candidate), len(other)) < _RESTATEMENT_MIN_WORDS:
        return candidate == other
    shared = len(candidate & other)
    return shared / min(len(candidate), len(other)) >= _RESTATEMENT


def _asked_questions(state: AspireState) -> list[set[str]]:
    """Every question asked in the whole thread, as word sets, not just the last turn."""
    asked: list[set[str]] = []
    for message in state.get("messages") or []:
        if getattr(message, "type", None) != "human":
            continue
        content = getattr(message, "content", "")
        if not isinstance(content, str) or not content.strip():
            continue
        words = _words(content)
        if words:
            asked.append(words)
    return asked


# ── small talk: a greeting is not an ungrounded question, so it never opens a ticket ──
_SMALL_TALK: Final[tuple[tuple[str, str], ...]] = (
    ("greeting", r"(hi|hey|hello|good\s+(morning|afternoon|evening)|hola|buenos\s+d[ií]as|bonjour|salut)"),
    ("thanks", r"(thanks|thank\s+you|ty|cheers|gracias|merci)"),
    ("ack", r"(ok|okay|k|sure|got\s+it|cool|nice|yes|no|yeah|yep|vale|d'accord)"),
    ("identity", r"(who\s+are\s+you|what\s+are\s+you|qui\s+es-tu|qui[eé]n\s+eres)"),
    ("repeat", r"((can|could)\s+you\s+)?(say\s+that\s+again|repeat\s+that|explain\s+that\s+(again|more\s+simply)|"
               r"sorry,?\s+(can|could)\s+you\s+explain\s+that\s+more\s+simply|"
               r"wait,?\s+i\s+don'?t\s+understand|i\s+don'?t\s+understand|"
               r"what\s+did\s+i\s+(just\s+)?ask(\s+you)?)"),
    ("bye", r"(bye|goodbye|see\s+you|adios|adi[oó]s|au\s+revoir)"),
)

#: What to say instead of opening a ticket.
_SMALL_TALK_REPLIES: Final[dict[str, dict[str, str]]] = {
    "greeting": {
        "en": "Hello! I can tell you about ASPIRE — saving money, and how the programme works. What would you like to know?",
        "es": "¡Hola! Puedo contarte sobre ASPIRE: cómo ahorrar dinero y cómo funciona el programa. ¿Qué te gustaría saber?",
        "fr": "Bonjour ! Je peux te parler d'ASPIRE : comment épargner et comment le programme fonctionne. Que veux-tu savoir ?",
    },
    "thanks": {
        "en": "You're welcome! Ask me anything else about ASPIRE.",
        "es": "¡De nada! Pregúntame lo que quieras sobre ASPIRE.",
        "fr": "Avec plaisir ! Pose-moi d'autres questions sur ASPIRE.",
    },
    "ack": {
        "en": "Got it. What else would you like to know about ASPIRE?",
        "es": "Entendido. ¿Qué más te gustaría saber sobre ASPIRE?",
        "fr": "D'accord. Que veux-tu savoir d'autre sur ASPIRE ?",
    },
    "identity": {
        "en": "I'm the ASPIRE assistant. I answer questions about the programme — saving, the accounts, and how to join. What would you like to know?",
        "es": "Soy el asistente de ASPIRE. Respondo preguntas sobre el programa: el ahorro, las cuentas y cómo unirte. ¿Qué te gustaría saber?",
        "fr": "Je suis l'assistant ASPIRE. Je réponds aux questions sur le programme : l'épargne, les comptes et comment s'inscrire. Que veux-tu savoir ?",
    },
    "repeat": {
        "en": "Of course — ask me again and I'll explain it a different way.",
        "es": "Claro, pregúntamelo otra vez y te lo explico de otra manera.",
        "fr": "Bien sûr — repose-moi la question et je l'expliquerai autrement.",
    },
    "bye": {
        "en": "Bye for now! Come back any time you have a question about ASPIRE.",
        "es": "¡Hasta pronto! Vuelve cuando tengas una pregunta sobre ASPIRE.",
        "fr": "À bientôt ! Reviens quand tu as une question sur ASPIRE.",
    },
}

_SMALL_TALK_RE: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple(
    # Anchored, and the only permitted extras are leading/trailing punctuation and whitespace.
    (kind, re.compile(rf"^[\s\W]*{pattern}[\s\W]*$", re.I))
    for kind, pattern in _SMALL_TALK
)


def _small_talk_reply(state: AspireState) -> Command | None:
    """A conversational reply for a conversational turn, or None."""
    raw = (_latest_user_text(state) or "").strip()
    # A length guard on top of the anchoring: no phrase in the closed list comes near 64.
    if not raw or len(raw) > 64:
        return None

    # Matched against the tidied form, so "helo", "hiiiiii", "yo" and "thanks!!
    # lol" reach the same reply "hello" does. The list is anchored, so a real
    # question that merely opens with a greeting -- "yo what is aspire" -- still
    # misses it and goes to the router, which is the intended behaviour.
    from app.casual import casual_fold

    text = casual_fold(raw) or raw

    for kind, pattern in _SMALL_TALK_RE:
        if pattern.match(text):
            locale = str(state.get("locale") or "en")
            replies = _SMALL_TALK_REPLIES[kind]
            logger.info(
                "Answering a %s turn conversationally rather than opening a ticket.",
                kind,
            )
            return Command(
                update={
                    "messages": [AIMessage(content=replies.get(locale) or replies["en"])],
                    "groundedness": 1.0,
                    "citations": [],
                }
            )
    return None


def _ungrounded(state: AspireState, reason: str, detail: str) -> Command:
    """An ungrounded turn: decline, and fetch a person only on the third try."""
    from app.agents.escalation import counter, decline
    from app.agents.escalation.contract import EscalationReason

    question = _latest_user_text(state)
    streak = counter.bump(state.get("decline_streak"), question)
    chunks = list(state.get("retrieved") or [])

    if not counter.at_limit(streak, question):
        logger.info(
            "QA turn for session %s declined (%s, attempt %d of %d): %s",
            state.get("session_id"),
            reason,
            next(iter(streak.values()), 0),
            counter.LIMIT,
            detail,
        )
        return Command(
            update={
                **decline.decline_update(state, chunks),
                "decline_streak": streak,
                # WHICH gate declined this, carried in state rather than only in the log.
                "safety_flags": {
                    **(state.get("safety_flags") or {}),
                    "declined": {"reason": reason, "detail": detail},
                },
            }
        )

    logger.info(
        "QA turn for session %s unresolved %d times on one intent (%s); escalating.",
        state.get("session_id"),
        counter.LIMIT,
        reason,
    )
    return _escalate(
        state,
        EscalationReason.REPEATED_FAILURE.value,
        f"Unresolved {counter.LIMIT} turns running. Last gate: {reason} -- {detail}",
        # Reset on the way out.
        extra={"decline_streak": {}},
    )


def _escalate(
    state: AspireState,
    reason: str,
    detail: str,
    *,
    extra: dict[str, Any] | None = None,
) -> Command:
    """Hand off, carrying a redacted summary and nothing else."""
    from app.safety import pii

    logger.info(
        "QA turn for session %s is ungrounded (%s): %s",
        state.get("session_id"),
        reason,
        detail,
    )
    return Command(
        # `graph=PARENT` because `escalate_agent` is a node of the MAIN graph, not of this subgraph.
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
            **(extra or {}),
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

