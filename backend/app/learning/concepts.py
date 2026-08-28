"""A teachable unit: what the tutor actually teaches from."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)

#: Bands youngest first.
BANDS: tuple[str, ...] = ("5-8", "9-12", "13-15", "16-18", "adult")

#: Band to the column holding its body.
BODY_COLUMNS: dict[str, str] = {
    "5-8": "body_5_8",
    "9-12": "body_9_12",
    "13-15": "body_13_15",
    "16-18": "body_16_18",
    "adult": "body_adult",
}

#: Statuses a learning turn may resolve to.
SERVABLE_STATUSES: frozenset[str] = frozenset({"draft", "approved"})


def band_index(band: str) -> int:
    try:
        return BANDS.index(band)
    except ValueError:
        return -1


@dataclass(frozen=True, slots=True)
class CheckItem:
    """One check-for-understanding question, with its three-rung hint ladder."""

    id: str
    band: str
    type: str
    question: str
    answer: str
    accept: tuple[str, ...] = ()
    hints: tuple[str, ...] = ()
    explanation_on_correct: str = ""
    explanation_on_wrong: str = ""

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "CheckItem | None":
        """One bank entry, or None if it is unusable."""
        question = str(data.get("question") or "").strip()
        if not question:
            return None
        return cls(
            id=str(data.get("id") or "chk"),
            band=str(data.get("band") or "9_12").replace("-", "_"),
            type=str(data.get("type") or "short_answer"),
            question=question,
            answer=str(data.get("answer") or "").strip(),
            accept=tuple(str(a).strip() for a in (data.get("accept") or []) if str(a).strip()),
            hints=tuple(str(h).strip() for h in (data.get("hints") or []) if str(h).strip()),
            explanation_on_correct=str(data.get("explanation_on_correct") or "").strip(),
            explanation_on_wrong=str(data.get("explanation_on_wrong") or "").strip(),
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "band": self.band,
            "type": self.type,
            "question": self.question,
            "answer": self.answer,
            "accept": list(self.accept),
            "hints": list(self.hints),
            "explanation_on_correct": self.explanation_on_correct,
            "explanation_on_wrong": self.explanation_on_wrong,
        }


#: The band key a check item carries, as the seeder writes it.
def band_key(band: str) -> str:
    return band.replace("-", "_")


@dataclass(frozen=True, slots=True)
class Misconception:
    wrong: str
    right: str


@dataclass(slots=True)
class TeachingConcept:
    """One idea, teachable at the bands that have a body for it."""

    id: str
    slug: str
    locale: str
    title: str
    domain: str
    band_min: str
    band_max: str
    aliases: tuple[str, ...] = ()
    bodies: dict[str, str] = field(default_factory=dict)
    local_example: str = ""
    misconceptions: tuple[Misconception, ...] = ()
    check_bank: tuple[CheckItem, ...] = ()
    numeric_anchors: dict[str, Any] = field(default_factory=dict)
    widget_hints: tuple[str, ...] = ()
    source_kb_ids: tuple[str, ...] = ()
    status: str = "draft"
    #: Present only when the store loaded embeddings.
    embedding: list[float] | None = None

    # ── reading ─────────────────────────────────────────────────────────────

    def body_for(self, band: str) -> str | None:
        """The body this band receives, inheriting downward."""
        index = band_index(band)
        if index < 0:
            return None
        for step in range(index, -1, -1):
            body = (self.bodies.get(BANDS[step]) or "").strip()
            if body:
                return body
        return None

    def teachable_at(self, band: str) -> bool:
        """Whether this concept may be taught to this band."""
        if band_index(band) < 0:
            return False
        if not band_index(self.band_min) <= band_index(band) <= band_index(self.band_max):
            return False
        return self.body_for(band) is not None

    def checks_for(self, band: str) -> tuple[CheckItem, ...]:
        """The check items written for this band, inheriting downward like a body."""
        index = band_index(band)
        for step in range(index, -1, -1):
            wanted = band_key(BANDS[step])
            found = tuple(item for item in self.check_bank if item.band == wanted)
            if found:
                return found
        return tuple(self.check_bank)

    @property
    def is_servable(self) -> bool:
        return self.status in SERVABLE_STATUSES

    def summary(self) -> str:
        """One line, for a log or a disambiguation menu."""
        return f"{self.id} {self.slug} ({self.domain}, {self.band_min}..{self.band_max})"

    # ── construction ────────────────────────────────────────────────────────

    @classmethod
    def from_row(cls, row: Any) -> "TeachingConcept":
        """One database row into a concept."""
        get = row.get if hasattr(row, "get") else lambda key, default=None: row[key]

        bodies: dict[str, str] = {}
        for band, column in BODY_COLUMNS.items():
            value = get(column, None)
            if value and str(value).strip():
                bodies[band] = str(value).strip()

        raw_checks = _as_json_list(get("check_bank", None))
        checks = tuple(
            item for item in (CheckItem.from_json(entry) for entry in raw_checks) if item
        )

        raw_misconceptions = _as_json_list(get("misconceptions", None))
        misconceptions = tuple(
            Misconception(
                wrong=str(entry.get("wrong") or "").strip(),
                right=str(entry.get("right") or "").strip(),
            )
            for entry in raw_misconceptions
            if str(entry.get("wrong") or "").strip() and str(entry.get("right") or "").strip()
        )

        anchors = get("numeric_anchors", None)
        if isinstance(anchors, str):
            anchors = _loads_or(anchors, {})

        embedding = get("embedding", None)
        if embedding is not None and not isinstance(embedding, list):
            # pgvector arrives as a string without a codec, or as a numpy array; coerce either.
            embedding = _as_vector(embedding)

        return cls(
            id=str(get("id", "")),
            slug=str(get("slug", "") or get("id", "")),
            locale=str(get("locale", "en") or "en"),
            title=str(get("title", "") or get("name", "") or ""),
            domain=str(get("domain", "saving") or "saving"),
            band_min=str(get("band_min", "5-8") or "5-8"),
            band_max=str(get("band_max", "adult") or "adult"),
            aliases=tuple(str(a) for a in (get("aliases", None) or [])),
            bodies=bodies,
            local_example=str(get("local_example", "") or ""),
            misconceptions=misconceptions,
            check_bank=checks,
            numeric_anchors=dict(anchors or {}),
            widget_hints=tuple(str(k) for k in (get("widget_hints", None) or [])),
            source_kb_ids=tuple(str(k) for k in (get("source_kb_ids", None) or [])),
            status=str(get("status", "draft") or "draft"),
            embedding=list(embedding) if embedding is not None else None,
        )

    def embedding_text(self) -> str:
        """What gets embedded for semantic resolution."""
        parts = [self.title, " ".join(self.aliases)]
        body = self.bodies.get("9-12") or self.bodies.get("13-15") or self.body_for("adult")
        if body:
            parts.append(body)
        return "\n".join(part.strip() for part in parts if part and part.strip())


# ── helpers ──────────────────────────────────────────────────────────────────


def _loads_or(text: str, fallback: Any) -> Any:
    import json

    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return fallback


def _as_json_list(value: Any) -> list[dict[str, Any]]:
    """A JSONB column as a list of objects, whatever the driver handed back."""
    if value is None:
        return []
    if isinstance(value, str):
        value = _loads_or(value, [])
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


#: Words that carry no topic.
_STOPWORDS: frozenset[str] = frozenset(
    "a an the is are was were what whats how why when who which do does did can "
    "could would should i me my mine you your yours we us our it its that this "
    "these those of to for in on at by with about from and or but if then than "
    "so as be been being have has had get got tell show teach explain know learn "
    "understand mean means please thanks thank want need like".split()
)

_WORDS = __import__("re").compile(r"[a-z0-9]+")


def _content_words(text: str) -> frozenset[str]:
    return frozenset(
        word
        for word in _WORDS.findall((text or "").lower())
        if word not in _STOPWORDS and len(word) > 2
    )


def _as_vector(value: Any) -> list[float] | None:
    """A pgvector column as a list of floats, or None."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip().lstrip("[").rstrip("]")
        if not text:
            return None
        try:
            return [float(part) for part in text.split(",")]
        except ValueError:
            return None
    try:
        return [float(part) for part in value]
    except (TypeError, ValueError):
        return None


# ── the in-memory store ──────────────────────────────────────────────────────


SELECT_COLUMNS = (
    "id, slug, locale, title, domain, band_min, band_max, aliases, "
    "body_5_8, body_9_12, body_13_15, body_16_18, body_adult, "
    "local_example, misconceptions, check_bank, numeric_anchors, "
    "widget_hints, source_kb_ids, status, embedding"
)


class ConceptStore:
    """Every servable concept, in memory, with its embeddings as one matrix."""

    def __init__(self) -> None:
        self._by_id: dict[str, TeachingConcept] = {}
        self._matrix: Any = None
        self._matrix_ids: list[str] = []
        self._loaded = False

    # ── population ──────────────────────────────────────────────────────────

    def load(self, concepts: Iterable[TeachingConcept]) -> None:
        """Replace the store's contents. Synchronous, and the tests' entry point."""
        self._by_id = {concept.id: concept for concept in concepts}
        self._rebuild_matrix()
        self._loaded = True

    async def reload(self) -> int:
        """Read every servable concept from Postgres."""
        try:
            rows = await _fetch_concepts()
        except Exception:
            logger.warning("Could not reload concepts; keeping %d.", len(self._by_id), exc_info=True)
            return len(self._by_id)

        concepts = [TeachingConcept.from_row(row) for row in rows]
        servable = [concept for concept in concepts if concept.is_servable]
        self.load(servable)
        logger.info(
            "Concepts loaded: %d servable of %d, %d with embeddings.",
            len(servable),
            len(concepts),
            len(self._matrix_ids),
        )
        return len(servable)

    def _rebuild_matrix(self) -> None:
        """The embedding matrix, L2-normalised so cosine is a dot product."""
        vectors = [
            (concept.id, concept.embedding)
            for concept in self._by_id.values()
            if concept.embedding
        ]
        if not vectors:
            self._matrix = None
            self._matrix_ids = []
            return

        import numpy as np

        self._matrix_ids = [concept_id for concept_id, _ in vectors]
        matrix = np.asarray([vector for _, vector in vectors], dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        # A zero vector would divide by zero and poison every other concept's score with NaN.
        norms[norms == 0] = 1.0
        self._matrix = matrix / norms

    # ── reading ─────────────────────────────────────────────────────────────

    @property
    def loaded(self) -> bool:
        return self._loaded

    def __len__(self) -> int:
        return len(self._by_id)

    def get(self, concept_id: str | None) -> TeachingConcept | None:
        return self._by_id.get(concept_id or "")

    #: What a reader falls back to when nothing is authored in their language.
    #:
    #: The corpus is English and always has been: `ground_check` localises what
    #: a citation SAYS and leaves what it POINTS AT alone, and an answer is
    #: written in the reader's language from English source. The concept store
    #: was the one place that did not follow that rule -- it filtered strictly
    #: on locale, and since every authored row is English, `teachable` returned
    #: NOTHING for a Spanish or French reader. They could not be taught a
    #: single concept in either language.
    #:
    #: So the filter prefers the reader's language and falls back to English
    #: rather than to silence. The guide still answers in their language; only
    #: the source material is English, exactly as it is everywhere else.
    FALLBACK_LOCALE = "en"

    def _in_locale(
        self, locale: str, predicate
    ) -> list[TeachingConcept]:
        """Concepts matching `predicate`, in this language or in English."""
        wanted = [
            concept
            for concept in self._by_id.values()
            if concept.locale == locale and predicate(concept)
        ]
        if wanted or locale == self.FALLBACK_LOCALE:
            return wanted
        return [
            concept
            for concept in self._by_id.values()
            if concept.locale == self.FALLBACK_LOCALE and predicate(concept)
        ]

    def by_slug(self, slug: str, locale: str = "en") -> TeachingConcept | None:
        found = self._in_locale(locale, lambda c: c.slug == slug)
        return found[0] if found else None

    def all(self) -> list[TeachingConcept]:
        return list(self._by_id.values())

    def teachable(self, band: str, locale: str = "en") -> list[TeachingConcept]:
        return self._in_locale(locale, lambda c: c.teachable_at(band))

    def rank(
        self, vector: Sequence[float], *, band: str, locale: str = "en", top: int = 3
    ) -> list[tuple[TeachingConcept, float]]:
        """The best-matching teachable concepts and their cosine similarities."""
        if self._matrix is None or not vector:
            return []

        import numpy as np

        query = np.asarray(vector, dtype=np.float32)
        norm = float(np.linalg.norm(query))
        if norm == 0:
            return []
        scores = self._matrix @ (query / norm)

        # Same fallback as `teachable`: prefer the reader's language, and use
        # English rather than rank nothing at all.
        allowed = {c.id for c in self.teachable(band, locale)}

        ranked: list[tuple[TeachingConcept, float]] = []
        for position, concept_id in enumerate(self._matrix_ids):
            concept = self._by_id.get(concept_id)
            if concept is None or concept.id not in allowed:
                continue
            ranked.append((concept, float(scores[position])))

        ranked.sort(key=lambda pair: pair[1], reverse=True)
        return ranked[:top]

    def rank_lexical(
        self, utterance: str, *, band: str, locale: str = "en", top: int = 3
    ) -> list[tuple[TeachingConcept, float]]:
        """The same ranking, by word overlap, for concepts with no vector."""
        words = _content_words(utterance)
        if not words:
            return []

        ranked: list[tuple[TeachingConcept, float]] = []
        for concept in self._by_id.values():
            if concept.locale != locale or not concept.teachable_at(band):
                continue

            score = 0.0
            lowered = utterance.lower()
            for alias in (*concept.aliases, concept.title):
                alias_words = _content_words(alias)
                if not alias_words:
                    continue
                # A whole alias in the utterance is this method's strongest signal.
                if alias.lower() in lowered:
                    score = max(score, 0.90)
                    continue
                overlap = len(alias_words & words) / len(alias_words)
                # Peaks at 0.72: full alias overlap clears the resolve threshold, partial does not.
                score = max(score, overlap * 0.72)

            slug_words = _content_words(concept.slug.replace("_", " "))
            if slug_words and slug_words <= words:
                score = max(score, 0.85)

            if score > 0:
                ranked.append((concept, score))

        ranked.sort(key=lambda pair: pair[1], reverse=True)
        return ranked[:top]

    @property
    def has_embeddings(self) -> bool:
        """Whether semantic ranking is available at all."""
        return self._matrix is not None


async def _fetch_concepts() -> list[Any]:
    """Every concept row, servable or not. The store filters."""
    from sqlalchemy import text

    from app.db.engine import get_sessionmaker

    maker = get_sessionmaker()
    async with maker() as session:
        result = await session.execute(text(f"SELECT {SELECT_COLUMNS} FROM concepts"))
        return [dict(row) for row in result.mappings()]


#: Process-wide store.
_store: ConceptStore | None = None


def get_store() -> ConceptStore:
    global _store
    if _store is None:
        _store = ConceptStore()
    return _store


def set_store(store: ConceptStore | None) -> None:
    """Replace the process-wide store. For tests and for the seeder."""
    global _store
    _store = store
