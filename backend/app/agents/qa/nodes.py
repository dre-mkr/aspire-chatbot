"""The five nodes of the Q&A subgraph."""

from __future__ import annotations

from pathlib import Path

from functools import lru_cache

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

        # THE READER'S OWN AUDIENCE OUTRANKS SOMEBODY ELSE'S MATERIAL.
        #
        # `_permitted` decides what a reader MAY see and lets everything
        # through, and `_for_this_reader` sorted only the follow-up chips -- so
        # the extracts the ANSWER is written from were audience-blind. Observed
        # on the live site, 25 Aug: Zion, seventeen, asked for his story to star
        # a fisherman from Sandy Point and was told "After the story, STUDENTS
        # CAN ACT IT OUT and discuss what choice he made" -- a teacher's lesson
        # plan, read out to the child it was written about.
        #
        # A demotion rather than a filter, and deliberately: it is a tie-break
        # applied to the cross-encoder's score, so a row written for another
        # audience still wins when it is the only thing that answers. The chips
        # already work this way, for the same reason -- a thin corpus slice must
        # not leave a reader with nothing.
        audience = reader_audience(state)
        paired = sorted(
            zip(chunks, scores),
            key=lambda pair: (-(1 if _for_this_reader(pair[0], audience) else 0), -pair[1]),
        )
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
Answer a factual question about the ASPIRE programme from the knowledge-base
extracts supplied with the question.

GROUNDING (non-negotiable)
- Answer ONLY from the extracts. If they do not contain the answer, say so
  plainly and name who does -- never fill a gap from anything else you know.
- Every figure, date, amount and rule you state must appear in an extract. Do
  not round, convert, average or infer one.
- Cite the extracts you used by their [ASP-xxx] id, inline, right after the
  fact each one supports. An answer with no citation will not be served.

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
- If the question is how or why something works, join the extracts into one
  chain of cause and effect and show the arithmetic once. Three cited facts
  sitting next to each other is not an answer to a "how" question.
- One worked example in EC$ where the extracts support it.
- Four or five sentences. Bullets only for a genuine list of steps.""",
    "aurora": """DEPTH AND COMPLETENESS
- Open with the ANSWER, not with a verdict. Yes or no belongs first only when
  she asked a yes-or-no question: "What is ASPIRE?" does not open with "Yes",
  and "When can she access it?" does not open with "No" -- which reads as a
  refusal before she has been told anything.
- Lead with the answer she can act on. Then the documents, amounts, deadlines
  and next step the extracts support -- and stop.
- Where the answer IS a list of documents or steps, use `-` bullets and let the
  list be the whole answer.
- Do not explain a money concept unless she asked how something works.
- Name the exception only when it could apply to her.""",
    "nova": """DEPTH AND COMPLETENESS
- Be thorough. Use every extract that bears on the question: give the direct
  answer first, then the conditions, exceptions, amounts, deadlines and next
  steps the extracts support.
- When several extracts together answer the question, weave them into one
  coherent, complete answer rather than answering from only one.
- Explain any programme or money term the moment you use it.
- Structure a longer answer: a direct opening sentence, short paragraphs, and
  `-` bullets for lists of documents, steps or rules.
- Where a rule has an exception, state the exception -- this reader will be
  asked about it.
- Close with the one thing the reader should do next, when the extracts name
  one. Never pad; every sentence must carry information from an extract.""",
    "guest": """DEPTH AND COMPLETENESS
- Give the direct answer in the first sentence, then the one or two details that
  change what the reader does next.
- When several extracts bear on the question, join them into one answer rather
  than listing them separately.
- Explain any programme or money term in half a clause the first time you use it.
- Two to four sentences. `-` bullets only for a real list of documents or steps.
- Close with the next step when the extracts name one.""",
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
1. Answer ONLY from the numbered knowledge-base extracts below. If they do not
   contain the answer, say so plainly -- do not fill the gap from anything you
   know.
2. Every figure, date, amount and rule in your answer must appear in an extract.
   Do not round, convert, average or infer one.
3. Cite the extracts you used by their [ASP-xxx] id, inline.
4. Write for the reader described below. Be thorough and complete: use every
   extract that bears on the question, explain terms as you use them, and
   structure longer answers with short paragraphs and `-` bullets. No links.

Knowledge-base extracts:
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

        if not chunks and not (state.get("story_topic") or "").strip():
            # No context means nothing to ground on, so never generate here.
            #
            # A STORY IS THE EXCEPTION. Fiction has no extracts, and refusing
            # here meant the model was never asked to write it: `generate`
            # returned no message, so `ground_check` found none and declined.
            # Observed on production, 25 Aug -- Zion, asked for a story about
            # "Saving up for something", answered with contact details.
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
    # Which page of the story this is. Beat one opens, the middle carries on
    # from what the reader has already been told, and the last one has to land:
    # a story with no ending is a treadmill with a character on it.
    arc = state.get("story_arc") or {}
    beat = int(arc.get("beat") or 1)
    from app.graph.nodes.cards import STORY_BEATS

    if beat == 1:
        page = ""
    elif beat >= STORY_BEATS:
        page = (
            "This is the LAST part. The reader has stayed with this story, so "
            "finish it: resolve what the character was deciding and end on the "
            "money idea it turned on. Do not leave it open.\n"
        )
    else:
        page = (
            f"This is part {beat}. Carry on the SAME story, with the same "
            "character and the same situation the reader has already been "
            "told about -- do not restart it or introduce a new character. "
            "Move it on: something happens, and it follows from the decision "
            "before it.\n"
        )

    # What the reader asked the story to become. Carried on the arc by
    # `cards._story_turn`, which now keeps a steering instruction rather than
    # dropping the story on the floor when it is not a choice or a "next".
    direction = str(arc.get("direction") or "").strip()
    steer = (
        f"The reader has asked for the story to change: {direction}\n"
        "Honour it from this beat on -- the same story, moved the way they "
        "asked. Do not restart it, do not explain the change, and do not "
        "treat the request as a question to answer.\n"
        if direction
        else ""
    )

    # The adventure block: the deterministic state the model must honour.
    adventure = ""
    if "wallet" in arc:
        wallet = int(arc.get("wallet") or 0)
        inventory = ", ".join(arc.get("inventory") or []) or "nothing yet"
        picked = str(arc.get("last_choice") or "")
        outcome = ""
        if picked:
            outcome = (
                f"Last beat the reader chose: {picked} -- and "
                + ("they could afford it. Weave the purchase in.\n"
                   if arc.get("afforded", True)
                   else "they could NOT afford it. The story shows that "
                        "consequence now, kindly and without a lecture.\n")
            )
        choices = (
            ""
            if beat >= STORY_BEATS
            else "End the beat with 2 or 3 choices for the reader, each on its "
                 "own line, each formatted exactly like \"Buy the rope (EC$30)\" "
                 "or \"Walk on (free)\" -- written in the story's own language, with the free option marked (free), (gratis) or (gratuit) to match -- at least one free, every price within "
                 "or near the wallet, and the trade-off real: what they buy or "
                 "skip must matter in the next beat.\n"
        )
        adventure = (
            f"THIS IS A PLAYABLE STORY. The reader's story-wallet holds EC${wallet} "
            f"and their inventory is: {inventory}. These numbers are the game "
            "state -- never change them yourself, never contradict them.\n"
            f"{outcome}{choices}"
        )

    return (
        f"The reader has asked for a story about: {topic}\n"
        f"{page}"
        f"{steer}"
        f"{adventure}"
        f"{shape}\n"
        "Set it in Saint Kitts and Nevis and use EC dollars. Invent the "
        "characters freely; do NOT invent anything about the ASPIRE programme "
        "itself -- no amounts, ages, dates or rules that are not in the "
        "material you were given. Do not add a quiz, a game or a question at "
        "the end unless the shape above asks for one.\n"
        # The rule this has to beat is the right rule everywhere else. NEVER
        # INVENT tells the model to refuse a premise it has no record of, and a
        # story about saving up is exactly that -- so the model applied it and
        # answered a child's request for a story with ASPIRE's phone number.
        # Fiction is not a premise to check; it is the thing that was asked for.
        "THIS TURN IS A STORY, not a knowledge answer. Any knowledge-base "
        "extracts are background, not the subject, and having none is normal: "
        "a story about a girl and a bicycle is not in the knowledge base and "
        "was never going to be. Do NOT say you have no record, no information "
        "or nothing in the supplied material, do not offer contact details, "
        "and do not ask what they meant. Write the story."
    )


#: What each role came for, in the register the spine sets for them.
#:
#: `Azuri · Teachers & Educators` is one persona key holding two jobs, and an
#: answer written for one lands wrong on the other. A classroom teacher asks
#: what to do Monday, period 3, with 28 Form 2s. A principal asks whether this
#: belongs in their school and what they are taking on. Same corpus rows, and
#: the wrong shape costs a collapsed lesson in one case and a commitment made
#: on a false premise in the other.
_ROLE_INSTRUCTION: dict[str, str] = {
    "teacher": (
        "The reader is a classroom teacher, speaking as one. Answer for "
        "DELIVERY: what they do, with which band, using what. Colleague to "
        "colleague, practical. If a resource, activity or lesson exists, name "
        "it. Do not open with the programme's rules unless they asked about "
        "them."
    ),
    "educator": (
        "The reader is responsible beyond one classroom -- a principal, a head "
        "of department, a coordinator or an officer. Answer for STEWARDSHIP: "
        "what this commits the school to, who stands behind it, what it costs "
        "and what it asks of staff. Colleague to colleague, accountable. Be "
        "plain about what you do not know: a commitment made on a false "
        "premise is the expensive mistake here."
    ),
    "parent": (
        "The reader is a parent or guardian speaking about their own child. "
        "Answer for THEIR child, not for children in general, and say what "
        "they can do next. Never guess at their account."
    ),
    # The Adult Learner spine. NOT the educator: a teacher asks what to do with
    # a class, an adult learner asks what to do with their own money. The
    # register is andragogy, not pedagogy -- an adult who missed this the first
    # time is not a child, and being quizzed like one is why they leave.
    #
    # Four moves, and they are the difference between teaching a grown reader
    # and talking down to one:
    #  - START FROM THE PROBLEM they brought, not from a definition. An adult
    #    learns what they have a use for now, this month, this pay.
    #  - CREDIT WHAT THEY ALREADY DO. They have run a household, a hustle, a
    #    light bill. Name the thing they already do right and build the idea
    #    onto it, rather than starting them at zero.
    #  - ONE STEP THEY CAN TAKE, concrete and this-week, in EC dollars and the
    #    Federation's own seasons -- Sugar Mas, the September bills, the good
    #    month and the thin one.
    #  - OFFER, NEVER GATE. You may offer a check or a worked example; you must
    #    never make them pass a quiz to be answered, and never grade a plain
    #    question as a wrong answer. A defended choice is worth more than a
    #    right one.
    "learner": (
        "The reader is an adult learning this for themselves -- not a teacher, "
        "not asking about a child. Answer as one adult to another. Start from "
        "the money problem they actually have, not from a definition. Credit "
        "what they already do well and build onto it rather than starting them "
        "at zero. Give ONE concrete step they could take this week, in EC "
        "dollars and set in the Federation. Offer a check or an example if it "
        "helps -- never require them to pass a quiz, and never grade an "
        "ordinary question as if it were a wrong answer.\n"
        "For an adult the gap is usually BEHAVIOUR, not knowledge -- they "
        "already know they should save. Speak to the habit and the pattern: "
        "what triggers the spend, the automatic move that beats willpower "
        "(keep-first on payday, a standing transfer), the small routine repeated "
        "over the grand plan attempted once. Name the habit to build, not just "
        "the fact to know."
    ),
}


def _role_instruction(state: AspireState) -> str | None:
    """The register this reader's role earns, or None if they have not said."""
    role = speaking_as(state)
    if not role:
        return None
    return _ROLE_INSTRUCTION.get(role)


#: Where this reader stands in the ASPIRE journey, which nothing was reading.
#:
#: `account_status` is signed into the session token and used for access
#: control, and then thrown away. It is the difference between four different
#: people asking the same words: "how does ASPIRE work" from someone deciding
#: whether to apply is a different question from the same words typed by a
#: parent whose child has been enrolled for two years.
#:
#: Shaping only. It cannot widen what a reader may see -- `allowed_agents` has
#: already settled that -- and it must never be used to assert a fact about an
#: individual account, which this system cannot see.
_STAGE_INSTRUCTION: dict[str, str] = {
    "prospect": (
        "This reader has not applied. They are deciding whether ASPIRE is for "
        "them, so answer what it is and what joining would mean, and end with "
        "the next step rather than assuming they have taken it."
    ),
    "applicant": (
        "This reader has applied and is waiting. Answer what happens next and "
        "in what order. Do not tell them to apply -- they have. You cannot see "
        "their application, so never state where it has got to."
    ),
    "beneficiary": (
        "This reader is already in the programme. Answer how to USE it rather "
        "than how to join it, and do not re-explain eligibility unless asked."
    ),
    "guardian": (
        "This reader manages a child's participation. Answer what they can do "
        "on the child's behalf and where that has to happen."
    ),
}


def _pledge_instruction(state: AspireState) -> str | None:
    """The standing pledge, kept in view. The journey rung's memory."""
    pledge = state.get("pledge")
    if not isinstance(pledge, dict) or not pledge.get("amount_line"):
        return None
    goal = f" towards {pledge['goal']}" if pledge.get("goal") else ""
    return (
        f"The reader has PLEDGED to save {pledge['amount_line']}{goal}. Keep it "
        "in view: where it is natural, connect the answer to their pledge or ask "
        "how it is going. Never scold about it, and never bring it up twice in a row."
    )


def _stage_instruction(state: AspireState) -> str | None:
    """Where in the journey this reader is standing, or None."""
    return _STAGE_INSTRUCTION.get(str(state.get("account_status") or ""))


def _shaping_instructions(state: AspireState) -> str | None:
    """Every extra system line this turn earns, joined. None when there are none."""
    lines = [
        line
        for line in (
            _simple_mode_instruction(state),
            _role_instruction(state),
            _pledge_instruction(state),
            _stage_instruction(state),
            _story_instruction(state),
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

        # ── a story the reader asked for is not a corpus answer ─────────────
        #
        # Every gate below grades an answer as a claim about the programme:
        # retrieval floors, citations, figures. A story is none of that -- the
        # reader asked for fiction, `_story_instruction` already forbids it
        # from inventing programme facts, and a playable beat MUST state
        # figures no extract contains ("Buy the rope (EC$30)" is the game).
        # Graded as a factual answer, every story lost: observed on production,
        # 25 Aug -- Skye asked what the story should be about, was told
        # "Earning your own money" (one of this file's own suggested topics),
        # and answered the child with the decline copy. A promise made by the
        # cards node and broken by this gate.
        #
        # A story with no text still declines below: the model produced
        # nothing, and nothing is not a story. And the text has to be the
        # MODEL'S -- with no generation, `messages[-1]` is the reader's own
        # message, and serving a child their words back as the tale is worse
        # than declining.
        story_told = (
            bool((state.get("story_topic") or "").strip())
            and bool(messages)
            and isinstance(messages[-1], AIMessage)
            and bool(answer.strip())
        )
        if story_told:
            return Command(
                update={
                    # Fiction has no sources; the panel stays empty rather than
                    # dressing a tale in citations.
                    "citations": [],
                    "groundedness": 1.0,
                    "active_agent": state.get("active_agent"),
                    "quick_replies": follow_up_chips(state, [], set(), answer),
                    "decline_streak": {},
                }
            )

        if not chunks or not answer.strip():
            return _ungrounded(state, "no_context", "Nothing in the knowledge base matched.")

        query = state.get("qa_query") or _latest_user_text(state)

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
        # "Where this came from", in the language the reader is reading.
        #
        # Same problem as the chips and the same answer: what a citation SAYS
        # is corpus text, and the corpus is English. A Spanish answer opened a
        # source panel written in English. What a citation POINTS AT is not
        # translated -- a site's name, its host and its URL are what they are.
        citations = await localise_citations(citations, str(state.get("locale") or "en"))
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
                "quick_replies": follow_up_chips(state, chunks, grounded_citations, answer),
                # A resolved turn ends any run of unresolved ones.
                "decline_streak": {},
            }
        )

    return ground_check


async def localise_citations(citations: list[Citation], locale: str) -> list[Citation]:
    """Translate the reader-facing half of each citation. Never raises.

    Three fields carry corpus prose -- the row's title, the question it answers
    and the extract shown under it. The rest is provenance: `site`, `page`,
    `domain`, `source_url` and `updated` are the identity of a document, and
    translating those would be a different kind of wrong, so they are passed
    through untouched.

    Batched into one call for the whole panel and cached by exact text, like
    the chips, so a source a hundred readers see is paid for once.
    """
    if locale == "en" or not citations:
        return citations

    from app.agent import localise_lines

    fields = ("title", "question", "snippet")
    originals = [
        value
        for citation in citations
        for name in fields
        if (value := (getattr(citation, name, "") or "").strip())
    ]
    if not originals:
        return citations

    try:
        translated = await localise_lines(originals, locale)
    except Exception:
        logger.warning("Could not localise the source panel; leaving it as it is.", exc_info=True)
        return citations

    by_original = dict(zip(originals, translated, strict=True))
    return [
        citation.model_copy(
            update={
                name: by_original.get(value, value)
                for name in fields
                if (value := (getattr(citation, name, "") or "").strip())
            }
        )
        for citation in citations
    ]


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


#: Where a story goes next, per locale, while the arc is still open.
#:
#: A story used to end and stop. The shapes in `_STORY_BY_PERSONA` tell the
#: model not to add a question at the end -- rightly, because an invented quiz
#: about ASPIRE is exactly the failure this product cannot have -- but nothing
#: took the conversation on from there either. Maya saved for a laptop, and
#: then nothing.
#:
#: Chips rather than prose, for the same reason the instruction exists: these
#: are written here, so a story can invite the next turn without the model
#: being free to invent a programme fact on the way out.
#:
#: Every line has to be a phrase the intent it triggers actually matches --
#: `story_continues` for the first, `story_ends` for the last. Tested, because
#: a chip that reads well and routes nowhere is worse than no chip.
_STORY_FOLLOW_UPS: dict[str, list[str]] = {
    "en": ["What happens next?", "What would you do?", "That's enough"],
    "es": ["¿Qué pasa después?", "¿Qué harías tú?", "Ya basta"],
    "fr": ["Et après ?", "Que ferais-tu ?", "Ça suffit"],
}

#: And at the last beat, where "what happens next" would be a lie.
_STORY_ENDED: dict[str, list[str]] = {
    "en": ["Tell me another story", "What does it teach?"],
    "es": ["Cuéntame otra historia", "¿Qué nos enseña?"],
    "fr": ["Raconte-moi une autre histoire", "Qu'est-ce que ça apprend ?"],
}


def follow_up_chips(
    state: AspireState, chunks: list[KBChunk], cited: set[str], answer: str = ""
) -> list[str]:
    """More questions the corpus can answer, drawn from the reranked chunks then `qa_related`."""
    # A story earns its own, because corpus questions do not follow from one.
    # "Is the ASPIRE application always open?" is a fine chip after a policy
    # answer and a non-sequitur after a story about a girl and a laptop.
    if state.get("story_topic"):
        from app.graph.nodes.cards import STORY_BEATS

        locale = str(state.get("locale") or "en")
        arc = state.get("story_arc") or {}
        beat = int(arc.get("beat") or 1)
        # A playable story's chips ARE its choices, read off the beat the
        # model just wrote, so the tap sends exactly the priced line the
        # cards node knows how to score.
        if "wallet" in arc and beat < STORY_BEATS and answer:
            choices = [
                line.strip("-* \t")
                for line in answer.splitlines()
                if re.search(r"\((?:EC\$\s?\d+|free|gratis|gratuit)\)\s*$", line.strip(), re.IGNORECASE)
            ]
            if choices:
                return choices[:3]
        table = _STORY_ENDED if beat >= STORY_BEATS else _STORY_FOLLOW_UPS
        return list(table.get(locale, table["en"]))

    asked = _asked_questions(state)
    # What the answer covered, by question not by id: two rows can ask the same thing.
    covered = [
        _words(str(chunk.metadata.get("question") or chunk.title or ""))
        for chunk in chunks
        if chunk.kb_id in cited
    ]
    seen: list[set[str]] = []
    # Two buckets, filled in one pass and drained in order.
    #
    # `_permitted` already decided what this reader MAY see, which is a safety
    # question and answers a different one: everything is permitted to everyone,
    # so it sorts nothing. This sorts by whether the question is FOR them.
    #
    # An educator asking how to prepare a lesson was offered "Is a phone a need
    # or a want?" -- a nine-year-old's question, correct, permitted, and absurd
    # in front of a teacher. The corpus already tags every row with its
    # audience; nothing was reading the tag.
    audience = reader_audience(state)
    mine: list[str] = []
    theirs: list[str] = []

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
        (mine if _for_this_reader(chunk, audience) else theirs).append(question)
        if len(mine) == FOLLOW_UP_CHIPS:
            break

    # Anything tagged for someone else is a fallback, not a filter: a thin
    # corpus slice must not leave a reader with no follow-ups at all.
    return [*mine, *theirs][:FOLLOW_UP_CHIPS]


def _for_this_reader(chunk: KBChunk, audience: str) -> bool:
    """Whether this row's audience is the one the reader is in.

    `general` counts for everyone -- it is the corpus saying "anyone", not a
    fourth audience. An untagged row counts too, for the same reason.
    """
    tags = chunk.metadata.get("audience")
    if not tags:
        return True
    if isinstance(tags, str):
        tags = [tags]
    have = {str(tag).strip().lower() for tag in tags}
    return bool(have & _AUDIENCE_FAMILY.get(audience, {audience, "general"}))


#: Above this overlap, two questions are the same question.
_RESTATEMENT = 0.75

#: Words that carry no topic.
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


#: Which corpus audience a reader's own words put them in.
#:
#: The persona is a starting point, not a fact about the person. The same adult
#: is a teacher on Monday and a parent on Tuesday, and can say so in the middle
#: of a conversation -- so the role they STATE wins over the one they picked
#: from a menu, and it can change again on the next turn.
_ROLE_SAID: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\bas\s+(?:an?|the)\s+(?:teacher|educator|tutor|instructor|head\s*teacher)\b"
            r"|\bmy\s+(?:own\s+)?(?:class(?:es|room)?|students|pupils|school)\b"
            r"|\bmy\s+(?:form|grade|year)\s*\d+\w*"
            r"|\bi\s+teach\b"
            r"|\bcomo\s+(?:docente|maestra?|profesora?)\b|\bmis?\s+(?:alumnos?|clase)\b"
            r"|\ben\s+tant\s+qu(?:e|')\s*(?:enseignant|professeur)\b|\bmes?\s+(?:[eé]l[eè]ves|classe)\b",
            re.IGNORECASE,
        ),
        "teacher",
    ),
    # Educator AFTER teacher on purpose. The spine's rule for a principal who
    # also teaches: "answer the Teacher first and offer the Educator half" --
    # the practical answer is never wrong to give, and the stewardship answer
    # is unwelcome when unasked. First match wins, so "my Form 2s" beats "our
    # school" when both are in one message.
    (
        re.compile(
            r"\bour\s+school\b|\bmy\s+staff\b|\bthe\s+department\b|\bthe\s+cohort\b"
            r"|\broll(?:ing)?\s+(?:it\s+)?out\b|\badopt(?:ing)?\b|\bacross\s+the\s+school\b"
            r"|\bwho\s+is\s+accountable\b|\bwhat\s+does\s+it\s+cost\s+(?:us|the\s+school)\b"
            r"|\bas\s+(?:an?|the)\s+(?:principal|deputy|head|hod|counsellor|facilitator"
            r"|youth\s+worker|librarian|officer)\b"
            r"|\bnuestra\s+escuela\b|\bmi\s+personal\b|\bcomo\s+(?:director|directora)\b"
            r"|\bnotre\s+[eé]cole\b|\bmon\s+personnel\b|\ben\s+tant\s+qu(?:e|')\s*directeur\b",
            re.IGNORECASE,
        ),
        "educator",
    ),
    (
        re.compile(
            r"\bas\s+(?:an?|the)\s+(?:parent|guardian|mother|father|mum|mom|dad)\b"
            r"|\bmy\s+(?:own\s+)?(?:child|children|son|daughter|kid|kids)\b"
            r"|\bi\s+have\s+(?:a|\d+|two|three|four)\s+(?:child|children|kids?|sons?|daughters?)\b"
            r"|\bcomo\s+(?:madre|padre)\b|\bmis?\s+(?:propios?\s+)?hijos?\b|\btengo\s+\d+\s+hijos?\b"
            r"|\ben\s+tant\s+qu(?:e|')\s*(?:parent|m[eè]re|p[eè]re)\b|\bmes?\s+(?:propres?\s+)?(?:enfants?|fils|filles?)\b"
            r"|\bj'ai\s+(?:un|une|deux|trois|\d+)\s+(?:enfants?|fils|filles?)\b",
            re.IGNORECASE,
        ),
        "parent",
    ),
)

#: Where each persona starts, before the reader says otherwise.
_AUDIENCE_BY_PERSONA: dict[str, str] = {
    "nova": "teacher",
    "aurora": "parent",
    "stella": "child",
    "kaleb": "student",
    "orion": "student",
    "guest": "general",
}


#: Which corpus tags each reader counts as their own.
#:
#: `general` is in every one: it is the corpus saying "anyone", not a fourth
#: audience. `child` and `student` share a family because they are the same
#: reader at different ages, and the word caps -- not the tag -- are what keep
#: a nine-year-old's answer at nine years old. Splitting them would demote half
#: a learner's follow-ups for no gain.
_AUDIENCE_FAMILY: dict[str, set[str]] = {
    "teacher": {"teacher", "general"},
    "parent": {"parent", "general"},
    "student": {"student", "child", "general"},
    "child": {"child", "student", "general"},
    "general": {"general", "student", "child", "parent", "teacher"},
}


def stated_role(state: AspireState) -> str | None:
    """The role this reader has told us they are in, latest first, or None."""
    for message in reversed(state.get("messages") or []):
        if getattr(message, "type", None) != "human":
            continue
        text = getattr(message, "content", "")
        if not isinstance(text, str) or not text.strip():
            continue
        for pattern, role in _ROLE_SAID:
            if pattern.search(text):
                return role
    return None


#: A role, as the corpus tags its rows.
#:
#: `educator` collapses onto `teacher` because the corpus has no administrator
#: tag -- a principal and a classroom teacher read the same rows. The two are
#: kept apart for the REGISTER of the answer, which `speaking_as` carries, not
#: for which rows they may see.
_ROLE_TO_AUDIENCE: dict[str, str] = {
    "teacher": "teacher",
    "educator": "teacher",
    "parent": "parent",
    "learner": "student",
}


def routed_role(state: AspireState) -> str:
    """The role the router read off this turn's message, or empty.

    The router is a model call that already happens on every routed turn, so
    this costs nothing and understands phrasings no pattern list will hold.
    It only ever sees the CURRENT message, which is the point: a role stated
    now is the one that counts.
    """
    route = (state.get("safety_flags") or {}).get("route") or {}
    role = str(route.get("role") or "").strip().lower()
    return role if role in _ROLE_TO_AUDIENCE else ""


def speaking_as(state: AspireState) -> str | None:
    """Which role this reader is in, by the best evidence available.

    A ladder, most authoritative first:

    1. What the ROUTER read off this message. Open-ended, and current.
    2. What the PATTERNS find in the thread. Narrower, but it reaches back --
       a role stated three turns ago still holds, and the router never saw it.
    3. Nothing, and the persona's default stands.

    Two is not redundant with one. The router is skipped entirely on a
    single-option turn, on a widget continuation, and whenever no API key is
    configured -- and on those turns the patterns are all there is.
    """
    return routed_role(state) or stated_role(state) or _purpose_role(state)


#: The learn-vs-teach clarifier's remembered answer, as a role.
#:
#: Ranks BELOW what this turn's message says -- an Azuri who answered "for
#: myself" last week and asks "how do I teach compound interest to my Form 2s"
#: today is a teacher today. It ranks ABOVE the persona default, which is the
#: whole point: the persona could not tell learning from teaching, and now the
#: reader has said which.
_PURPOSE_ROLE: dict[str, str] = {"self": "learner", "students": "teacher", "child": "parent"}


def _purpose_role(state: AspireState) -> str:
    """The role implied by a remembered clarifier answer, or empty."""
    return _PURPOSE_ROLE.get(str(state.get("learner_purpose") or ""), "")


def reader_audience(state: AspireState) -> str:
    """The corpus audience whose questions belong in front of this reader."""
    role = speaking_as(state)
    if role:
        return _ROLE_TO_AUDIENCE.get(role, role)
    return _AUDIENCE_BY_PERSONA.get(str(state.get("persona") or "guest"), "general")


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
    # A CLOSING, not just the word. "thanks, that helps" is how a conversation
    # ends, and the anchoring below -- which is right, and stops "yo what is
    # aspire" being read as a greeting -- meant those three extra words turned
    # the last turn of a demo into a decline with a phone number in it.
    # Observed on production, 26 Aug, on the twenty-fourth turn.
    #
    # Widened by a CLOSED set of appreciations rather than by loosening the
    # anchor: "thanks, but what about my brother?" is still a question.
    ("thanks", r"((?:ok(?:ay)?|alright|cool|great)[,!.\s]+)?"
               r"(thanks|thank\s+you|ty|cheers|gracias|merci)"
               r"(\s+(so|very)\s+much|\s+a\s+lot)?"
               r"([,!.\s]+(that|this|it)\s+(helps|helped|is\s+(really\s+)?(helpful|useful)"
               r"|was\s+(really\s+)?(helpful|useful)|makes\s+sense))?"
               r"([,!.\s]+(eso|esto)\s+(ayuda|me\s+sirve|tiene\s+sentido))?"
               r"([,!.\s]+([cç]a\s+(aide|m'?aide)|c'?est\s+(utile|clair)))?"),
    ("ack", r"(ok|okay|k|sure|got\s+it|cool|nice|yes|no|yeah|yep|vale|d'accord)"),
    # "what is your name" was missing, which is the phrasing most people
    # actually use -- so the persona could say its name only to somebody who
    # asked "who are you". The short-circuit sits above the response cache, so
    # the miss did not just skip the reply: it fell through to a cached refusal.
    ("identity", r"(who\s+are\s+you|what\s+are\s+you"
                 r"|what(\s+is|'?s)\s+your\s+name|what\s+do\s+(i|we)\s+call\s+you"
                 r"|do\s+you\s+have\s+a\s+name|tell\s+me\s+your\s+name"
                 r"|qui\s+es-tu|qui\s+[eê]tes-vous|comment\s+t[ue]\s+t'?appelles"
                 r"|quel\s+est\s+ton\s+nom"
                 r"|qui[eé]n\s+eres|c[oó]mo\s+te\s+llamas|cu[aá]l\s+es\s+tu\s+nombre)"),
    ("repeat", r"((can|could)\s+you\s+)?(say\s+that\s+again|repeat\s+that|explain\s+that\s+(again|more\s+simply)|"
               r"sorry,?\s+(can|could)\s+you\s+explain\s+that\s+more\s+simply|"
               r"wait,?\s+i\s+don'?t\s+understand|i\s+don'?t\s+understand|"
               r"what\s+did\s+i\s+(just\s+)?ask(\s+you)?)"),
    ("bye", r"(bye|goodbye|see\s+you|adios|adi[oó]s|au\s+revoir)"),
    # A reader trying to get OUT. Closed class, and it belongs here rather than
    # in the router for the same reason a greeting does: "cancel" alone was
    # classified as a topic and answered with advice about cancelling unused
    # subscriptions, which is the assistant not listening at the exact moment
    # somebody asked it to stop.
    ("stop", r"(stop|cancel|never\s*mind|nevermind|forget\s+it|start\s+over|"
             r"go\s+back|d[eé]jalo|olv[ií]dalo|cancelar|annuler|laisse\s+tomber)"),
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
    # The generic form, used only when the reader has no named guide -- see
    # `_IDENTITY_NAMED` and `_identity_reply` below.
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
    "stop": {
        "en": "No problem — we can leave that. What would you like to do instead? I can tell you about ASPIRE, or start again whenever you are ready.",
        "es": "Sin problema, lo dejamos ahí. ¿Qué te gustaría hacer? Puedo contarte sobre ASPIRE, o empezamos de nuevo cuando quieras.",
        "fr": "Pas de souci, on laisse ça. Que veux-tu faire à la place ? Je peux te parler d'ASPIRE, ou on recommence quand tu veux.",
    },
    "bye": {
        "en": "Bye for now! Come back any time you have a question about ASPIRE.",
        "es": "¡Hasta pronto! Vuelve cuando tengas una pregunta sobre ASPIRE.",
        "fr": "À bientôt ! Reviens quand tu as une question sur ASPIRE.",
    },
}

#: "Who are you?" answered by the guide who is actually speaking.
#:
#: THE LINE ABOVE IS PERSONA-BLIND, and it was the whole answer for every reader.
#: Measured on production 23 August 2026: all seven persona/band pairs returned
#: the byte-identical "I'm the ASPIRE assistant" to "Who are you?" -- Skye,
#: Kaleb, Zion, Imani and Azuri included. Six named guides, commissioned with
#: their own cards, artwork and voices, and not one of them said its own name.
#:
#: They can, and always could: "Are you Kaleb?" returns "Yes. I'm Kaleb" from
#: the card. Only the OPEN question was hard-coded, so the one phrasing a reader
#: is most likely to use was the one phrasing that lost the persona.
#:
#: `guest` is deliberately absent. It has no character to introduce -- "Guest" is
#: the absence of a name, not one -- so the generic line is not a fallback for
#: that reader, it is the correct answer.
_IDENTITY_NAMED: Final[dict[str, str]] = {
    "en": "I'm {name}, your ASPIRE guide. I can tell you about the programme — saving, the accounts, and how to join. What would you like to know?",
    "es": "Soy {name}, tu guía de ASPIRE. Puedo contarte sobre el programa: el ahorro, las cuentas y cómo unirte. ¿Qué te gustaría saber?",
    "fr": "Je suis {name}, ton guide ASPIRE. Je peux te parler du programme : l'épargne, les comptes et comment s'inscrire. Que veux-tu savoir ?",
}


#: Personas with no name to give, which answer the generic line instead.
#:
#: A DECISION, not an oversight, and named here so the next reader can tell.
#: "Guest" is the absence of a name rather than one -- the persona exists
#: precisely for the reader who has not said who they are -- so "I'm Guest,
#: your ASPIRE guide" would be introducing a character that does not exist.
#: The generic line is not a fallback for that reader; it is the correct answer.
#:
#: Anything else in `Persona` must have a name. `test_four_persona_fixes` walks
#: the enum rather than a list, so adding a persona without one fails the build
#: instead of quietly rejoining the six that used to say "I'm the ASPIRE
#: assistant" whoever they were.
_NO_NAME_TO_GIVE: Final[frozenset[str]] = frozenset({"guest"})


def _identity_reply(state: AspireState, locale: str) -> str:
    """The identity line, named where there is a name to give.

    NORMALISED FIRST, because a token minted before the split is still valid.
    `TOKEN_TTL` is seven days, so for a week after `kaleb.9-12.md` took that
    band there are live sessions whose token still says `stella` at 9-12.
    Access already migrates them -- `allowed_agents` calls
    `normalise_persona_band` before it does anything else -- but state carries
    the raw claim, so the identity line looked it up unmigrated and answered
    "I'm Skye" to a reader being served Kaleb's card, Kaleb's agents and
    Kaleb's game bank.

    The name has to agree with the card, or the split is only half applied in
    the one place a reader would actually notice it.
    """
    from app.domain import normalise_persona_band
    from app.prompting.personas.names import display_name

    band = str(state.get("age_band") or "")
    persona = normalise_persona_band(
        str(state.get("persona") or "").strip().lower(), band
    )
    if persona and persona not in _NO_NAME_TO_GIVE:
        name = display_name(persona, band)
        if name:
            named = _copy()["__identity_named__"]
            template = named.get(locale) or named.get("en") or _IDENTITY_NAMED["en"]
            return template.format(name=name)
    return reply_for("identity", locale)


_SMALL_TALK_RE: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple(
    # Anchored, and the only permitted extras are leading/trailing punctuation and whitespace.
    (kind, re.compile(rf"^[\s\W]*{pattern}[\s\W]*$", re.I))
    for kind, pattern in _SMALL_TALK
)


#: Where the words live. The behaviour stays in code; the copy does not.
COPY_PATH: Final[Path] = (
    Path(__file__).resolve().parents[3] / "data" / "small_talk.yaml"
)


@lru_cache(maxsize=1)
def _copy() -> dict[str, dict[str, str]]:
    """The small-talk wording, read once per process.

    PER-KEY FALLBACK, not all-or-nothing. A missing file, broken YAML, a
    language somebody forgot or a mistyped placeholder each cost the wording of
    ONE reply; every other key still comes from the file, and the missing one
    comes from the table below. Losing a greeting because one line was
    mis-indented would be the worse failure, and this is the shape that stops
    it -- the same choice `app.sources.registry` makes for the same reason.

    Merged over the in-code table rather than replacing it, so the built-in
    wording is always the floor.
    """
    merged: dict[str, dict[str, str]] = {
        kind: dict(langs) for kind, langs in _SMALL_TALK_REPLIES.items()
    }
    merged["__identity_named__"] = dict(_IDENTITY_NAMED)

    try:
        import yaml

        raw = yaml.safe_load(COPY_PATH.read_text(encoding="utf-8")) or {}
        # Valid YAML that is not a mapping -- a list, a bare string -- parses
        # cleanly and then has no `.get`. Checked rather than caught, so the log
        # says what is actually wrong with the file.
        if not isinstance(raw, dict):
            logger.error(
                "%s is valid YAML but not a mapping (%s); using the built-in "
                "wording.", COPY_PATH.name, type(raw).__name__,
            )
            return merged
    except FileNotFoundError:
        logger.warning("No small-talk copy at %s; using the built-in wording.", COPY_PATH)
        return merged
    except Exception:
        logger.error(
            "%s could not be read; using the built-in wording.", COPY_PATH.name,
            exc_info=True,
        )
        return merged

    replies = raw.get("replies")
    if not isinstance(replies, dict):
        if replies is not None:
            logger.error(
                "%s: `replies` is %s, not a mapping; using the built-in wording.",
                COPY_PATH.name, type(replies).__name__,
            )
        replies = {}
    for kind, langs in replies.items():
        if kind in merged and isinstance(langs, dict):
            for lang, text in langs.items():
                if isinstance(text, str) and text.strip():
                    merged[kind][lang] = text.strip()

    named = raw.get("identity_named")
    if not isinstance(named, dict):
        if named is not None:
            logger.error(
                "%s: `identity_named` is %s, not a mapping; using the built-in "
                "wording.", COPY_PATH.name, type(named).__name__,
            )
        named = {}
    for lang, template in named.items():
        if not isinstance(template, str) or not template.strip():
            continue
        # A template that cannot render is worse than no template: it would
        # raise on a live turn. Proven here, once, at load.
        try:
            rendered = template.format(name="Test")
        except (KeyError, IndexError, ValueError):
            logger.error(
                "small_talk.yaml identity_named[%s] does not render with {name}; "
                "keeping the built-in wording for that language.", lang,
            )
            continue
        if "Test" not in rendered:
            logger.error(
                "small_talk.yaml identity_named[%s] never uses {name}; keeping "
                "the built-in wording for that language.", lang,
            )
            continue
        merged["__identity_named__"][lang] = template.strip()

    return merged


def reply_for(kind: str, locale: str) -> str:
    """One conversational reply, in the reader's language where there is one."""
    langs = _copy().get(kind) or _SMALL_TALK_REPLIES.get(kind) or {}
    return langs.get(locale) or langs.get("en") or ""


def small_talk_kind(text: str) -> str | None:
    """Which closed small-talk class this message is, or None.

    Split out of `_small_talk_reply` so the stream layer can ask the same
    question WITHOUT building a graph state. See `small_talk_answer`.
    """
    raw = (text or "").strip()
    if not raw or len(raw) > 64:
        return None

    from app.casual import casual_fold

    folded = casual_fold(raw) or raw
    for kind, pattern in _SMALL_TALK_RE:
        if pattern.match(folded):
            return kind
    return None


def small_talk_answer(
    text: str, *, locale: str, persona: str | None, age_band: str | None
) -> str | None:
    """The conversational reply for a conversational turn, or None.

    ANSWERED BEFORE THE CACHE IS CONSULTED, and that ordering is the whole
    point. The cache is keyed on the question, so a turn that was once
    misrouted is served from the shelf for ever after -- and a greeting is the
    single most likely thing to be asked twice.

    It was not hypothetical. On 23 August 2026 a FRESH session on production
    answered "hi" with "And how are you related to the child?", and "thanks",
    "ok" and "bye" with "Pick the closest one -- mother, father, grandmother".
    All four came back from the cache in under 130ms, so this short-circuit --
    which exists precisely to answer "hi" -- never ran at all.

    `cacheable` no longer shelves a registration turn, which stops it recurring.
    This stops the whole class: a greeting, a thank-you or a goodbye is now
    answered from a closed list before anything is looked up, so no cache entry
    for one can ever be consulted, whatever put it there.
    """
    kind = small_talk_kind(text)
    if kind is None:
        return None
    if kind == "identity":
        return _identity_reply(
            {"persona": persona, "age_band": age_band}, locale
        )
    return reply_for(kind, locale)


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
            reply = (
                _identity_reply(state, locale)
                if kind == "identity"
                else reply_for(kind, locale)
            )
            logger.info(
                "Answering a %s turn conversationally rather than opening a ticket.",
                kind,
            )
            return Command(
                update={
                    "messages": [AIMessage(content=reply)],
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

