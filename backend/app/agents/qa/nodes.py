"""The five nodes of the Q&A subgraph."""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Final

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import Command

from app.config import get_settings
from app.graph.state import AspireState, Citation, KBChunk
from app.messages import text_of
from app.schemas.directives import CHIP_LABEL_CHARS

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


def make_rewrite_query(invoke=None):
    """Resolve pronouns and ellipsis before embedding."""

    async def rewrite_query(state: AspireState) -> dict[str, Any]:
        messages = state.get("messages", [])
        original = _latest_user_text(state)
        if not original:
            return {}

        if invoke is None or len(messages) <= 1:
            # An opening question has no context to resolve against, so skip the rewrite call.
            return {"qa_query": original}

        context = "\n".join(
            f"{_role(message)}: {text_of(message)}"
            for message in messages[-(REWRITE_WINDOW + 1) : -1]
        )
        try:
            rewritten = (await invoke(REWRITE_SYSTEM, f"{context}\n\nuser: {original}")).strip()
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


def bm25_rank(query: str, corpus: list[tuple[str, str]], top: int) -> list[str]:
    """BM25 over `(id, text)` pairs."""
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

        rows: list[tuple[str, str]] = []
        if corpus is not None:
            try:
                rows = await corpus(audience)
            except Exception:
                logger.warning("Could not load the corpus for BM25.", exc_info=True)

        dense = [chunk for chunk in dense if _permitted(chunk, audience)]
        by_id: dict[str, KBChunk] = {chunk.kb_id: chunk for chunk in dense}

        # BM25 searches the whole audience-permitted corpus, not a subset of the dense hits.
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

#: The QA agent's role card.
QA_AGENT_ROLE = """YOUR JOB THIS TURN
Answer a factual question about the ASPIRE programme from the knowledge-base
extracts supplied with the question.

GROUNDING (non-negotiable)
- Answer ONLY from the extracts. If they do not contain the answer, say so
  plainly and name who does -- never fill a gap from anything else you know.
- Every figure, date, amount and rule you state must appear in an extract. Do
  not round, convert, average or infer one.
- Cite the extracts you used by their [ASP-xxx] id, inline, right after the
  fact each one supports. An answer with no citation will not be served.

DEPTH AND COMPLETENESS
- Be thorough. Use every extract that bears on the question: give the direct
  answer first, then the conditions, exceptions, amounts, deadlines and next
  steps the extracts support.
- When several extracts together answer the question, weave them into one
  coherent, complete answer rather than answering from only one.
- Explain any programme or money term the moment you use it.
- Structure a longer answer: a direct opening sentence, short paragraphs, and
  `-` bullets for lists of documents, steps or rules.
- Close with the one thing the reader should do next, when the extracts name
  one. Never pad; every sentence must carry information from an extract."""

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
                agent_role=QA_AGENT_ROLE,
                user_text=question,
                retrieved=chunks,
            )
    except Exception:
        # A broken context must not cost the answer; fall through to the plain prompt.
        logger.warning("Could not build the layered QA prompt; using the plain one.", exc_info=True)

    block = "\n\n".join(f"[{chunk.kb_id}] {chunk.content}" for chunk in chunks)
    system = GENERATE_SYSTEM.format(context=block)
    audience = (
        f"Reader: age band {state.get('age_band')}, persona "
        f"{state.get('persona')}, language {state.get('locale')}."
    )
    return [
        SystemMessage(content=f"{system}\n{audience}"),
        HumanMessage(content=question),
    ]


# ── ground_check ─────────────────────────────────────────────────────────────

#: Numbers and money amounts in an answer.
_FIGURE = re.compile(r"(?:EC\$|US\$|\$)?\d[\d,]*(?:\.\d+)?%?")

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


def unattributed_figures(answer: str, chunks: list[KBChunk]) -> list[str]:
    """Figures in the answer that appear in no chunk."""
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

        # ── the primary floor: the dense retriever's real cosine relevance ──
        best = max((chunk.relevance for chunk in chunks), default=0.0)
        dense_seen = any(chunk.relevance > 0.0 for chunk in chunks)
        if dense_seen and best < floor:
            return _ungrounded(
                state,
                "below_relevance_floor",
                f"The closest chunk scored {best:.3f}, below the {floor:.3f} floor.",
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

        missing = unattributed_figures(answer, chunks)
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
        known = {chunk.kb_id for chunk in chunks}
        cited = {
            match.group(1)
            for match in re.finditer(r"\[([A-Za-z]{2,6}-\d+)\]", answer)
        }
        grounded_citations = cited & known

        if not grounded_citations:
            return _ungrounded(
                state,
                "uncited",
                "The answer cites no retrieved extract, so nothing supports it.",
            )

        # A citation to something not retrieved is worse than none: it is fabricated.
        invented = cited - known
        if invented:
            return _ungrounded(
                state,
                "invented_citation",
                f"The answer cited {sorted(invented)}, which was not retrieved.",
            )

        # Inline markers are stripped from the prose, so this panel is the only provenance.
        citations = [
            Citation(
                kb_id=chunk.kb_id,
                title=chunk.title,
                question=str(chunk.metadata.get("question") or "").strip(),
                snippet=snippet_of(chunk.content),
            )
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
    text = (_latest_user_text(state) or "").strip()
    # A length guard on top of the anchoring: no phrase in the closed list comes near 64.
    if not text or len(text) > 64:
        return None

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

