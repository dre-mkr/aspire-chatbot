"""Resolution decides what a learning turn is about. Precedence is the test.

The bug this module closes is that there was no resolution at all: placement
chose a lesson from the spaced-repetition schedule and the learner's message was
never read, so "What is compound interest?" was answered with the next unmastered
lesson. The tests below therefore assert the ORDER of the four branches as much
as the branches themselves -- a resolver that gets semantic matching right and
continuation wrong reads a correct answer as a new question, which is worse than
not resolving at all.
"""

from __future__ import annotations

import pytest

from app.agents.learn.resolve import (
    CONTINUATION_MAX_TOKENS,
    is_continuation,
    resolve_concept,
)
from app.learning.concepts import ConceptStore, TeachingConcept


def concept(slug: str, *, band_min="5-8", band_max="adult", vector=None, **extra):
    return TeachingConcept(
        id=f"CON-{abs(hash(slug)) % 9000:04d}",
        slug=slug,
        locale=extra.pop("locale", "en"),
        title=slug.replace("_", " ").title(),
        domain=extra.pop("domain", "saving"),
        band_min=band_min,
        band_max=band_max,
        aliases=extra.pop("aliases", ()),
        bodies=extra.pop("bodies", {band_min: "A body long enough to teach from."}),
        embedding=vector,
        **extra,
    )


@pytest.fixture
def store():
    """Three concepts on orthogonal unit vectors, so similarity is exact.

    Unit vectors rather than real embeddings: the thing under test is the
    threshold arithmetic and the precedence order, and a fixture whose scores are
    exactly 1.0 and 0.0 makes a threshold bug visible instead of plausible.
    """
    holder = ConceptStore()
    holder.load(
        [
            concept("compound_interest", band_min="9-12", vector=[1.0, 0.0, 0.0]),
            concept("saving_goal", vector=[0.0, 1.0, 0.0]),
            concept("mortgage", band_min="adult", vector=[0.0, 0.0, 1.0]),
        ]
    )
    return holder


def embedder(vector):
    async def embed(_text):
        return vector

    return embed


class TestContinuation:
    """A reply is not a question, and telling them apart is the whole fix for L4."""

    @pytest.mark.parametrize(
        "text",
        ["yes", "ok", "more", "why?", "no", "sí", "d'accord", "i don't know", "got it"],
    )
    def test_bare_acknowledgements_continue(self, text):
        assert is_continuation(text)

    @pytest.mark.parametrize("text", ["4", "20", "EC$20", "20 dollars", "4 weeks", "$5"])
    def test_a_bare_number_continues(self, text):
        """The case the whole function exists for.

        A learner asked "how much after 4 weeks?" replies "20". That embeds close
        to nothing in the store, so every other branch gets it wrong -- and
        getting it wrong means grading a correct answer as a new topic.
        """
        assert is_continuation(text)

    @pytest.mark.parametrize(
        "text",
        [
            "what is inflation",
            "tell me about scams",
            "how does compound interest work",
            "can you explain budgeting",
        ],
    )
    def test_a_new_enquiry_does_not_continue(self, text):
        assert not is_continuation(text)

    def test_a_short_phrase_continues_and_a_long_one_does_not(self):
        assert is_continuation(" ".join(["word"] * CONTINUATION_MAX_TOKENS))
        assert not is_continuation(" ".join(["word"] * (CONTINUATION_MAX_TOKENS + 1)))

    def test_mid_check_a_whole_sentence_is_still_an_answer(self):
        """`awaiting_answer` widens the rule, and that is why it is a parameter.

        "because the bank adds a bit every year" is thirty characters of
        continuation when a question is outstanding, and a new topic when one is
        not.
        """
        sentence = "because the bank adds a bit every year"
        assert is_continuation(sentence, awaiting_answer=True)
        assert not is_continuation(sentence, awaiting_answer=False)

    def test_a_plain_new_question_mid_check_is_still_a_new_question(self):
        assert not is_continuation("what is inflation", awaiting_answer=True)


class TestPrecedence:
    @pytest.mark.asyncio
    async def test_continuation_beats_a_perfect_semantic_match(self, store):
        """Precedence, asserted where it actually matters.

        The utterance embeds exactly onto `saving_goal`, and the learner is in
        the middle of `compound_interest`. Continuation wins.
        """
        active = store.by_slug("compound_interest")
        resolution = await resolve_concept(
            "yes",
            band="9-12",
            active_concept_id=active.id,
            store=store,
            embed=embedder([0.0, 1.0, 0.0]),
        )
        assert resolution.source == "continuation"
        assert resolution.concept_id == active.id

    @pytest.mark.asyncio
    async def test_a_strong_match_resolves_semantically(self, store):
        resolution = await resolve_concept(
            "what is compound interest",
            band="9-12",
            store=store,
            embed=embedder([1.0, 0.0, 0.0]),
        )
        assert resolution.source == "semantic"
        assert resolution.concept.slug == "compound_interest"
        assert resolution.similarity == pytest.approx(1.0)

    @pytest.mark.asyncio
    async def test_a_middling_match_is_disambiguated(self, store):
        """Between the thresholds, one cheap structured call settles it."""
        target = store.by_slug("saving_goal")
        seen: list[str] = []

        async def disambiguate(*, system, user):
            seen.append(user)
            return {"concept_id": target.id}

        # An utterance equidistant from every concept scores 1/sqrt(3) = 0.577
        # against each -- above the disambiguation floor (0.45) and below the
        # resolve threshold (0.62), which is exactly the band where the embedding
        # genuinely cannot tell and a cheap call can.
        resolution = await resolve_concept(
            "money things",
            band="9-12",
            store=store,
            embed=embedder([1.0, 1.0, 1.0]),
            disambiguate=disambiguate,
        )
        assert resolution.source == "disambiguated"
        assert resolution.concept_id == target.id
        assert seen, "the disambiguator must actually be consulted"

    @pytest.mark.asyncio
    async def test_a_null_disambiguation_falls_through(self, store):
        async def disambiguate(*, system, user):
            return {"concept_id": None}

        async def retrieve(_text):
            return []

        resolution = await resolve_concept(
            "money things",
            band="9-12",
            store=store,
            embed=embedder([1.0, 1.0, 1.0]),
            disambiguate=disambiguate,
            retrieve=retrieve,
        )
        assert resolution.source == "none"

    @pytest.mark.asyncio
    async def test_a_weak_match_falls_to_rag_teach(self, store):
        """No concept covers it, and the knowledge base still might.

        Teaching from rows beats declining: the corpus is 706 verified rows and
        the taxonomy is a few dozen concepts, so there is real material here that
        nobody has authored a concept around yet.
        """

        class Row:
            kb_id = "FIN-101"
            content = "Cryptocurrency is a digital asset with no central issuer."
            score = 0.81

        async def retrieve(_text):
            return [Row()]

        resolution = await resolve_concept(
            "what is cryptocurrency",
            band="13-15",
            store=store,
            embed=embedder([0.1, 0.1, 0.1]),
            retrieve=retrieve,
        )
        assert resolution.source == "rag"
        assert resolution.concept is None
        assert resolution.kb_rows
        assert resolution.teaches, "a RAG turn still teaches"

    @pytest.mark.asyncio
    async def test_nothing_above_the_floor_declines_with_offers(self, store):
        """The decline is not a dead end. Two concepts come back with it."""

        class Row:
            kb_id = "FIN-999"
            content = "unrelated"
            score = 0.10

        async def retrieve(_text):
            return [Row()]

        resolution = await resolve_concept(
            "what is a collateralised debt obligation",
            band="9-12",
            store=store,
            embed=embedder([0.05, 0.05, 0.05]),
            retrieve=retrieve,
        )
        assert resolution.source == "none"
        assert not resolution.teaches
        assert resolution.alternatives, "a decline must offer a way forward"


class TestBandFiltering:
    @pytest.mark.asyncio
    async def test_a_concept_above_the_band_is_not_offered(self, store):
        """Filtered BEFORE ranking, not after.

        Ranking first would let `mortgage` occupy a slot in the top three and
        push out a concept the child can actually be taught -- and the observable
        effect is "I do not know that yet" about something the store holds a body
        for.
        """
        ranked = store.rank([0.0, 0.0, 1.0], band="9-12", top=3)
        assert all(candidate.slug != "mortgage" for candidate, _ in ranked)

    @pytest.mark.asyncio
    async def test_an_adult_gets_the_adult_concept(self, store):
        ranked = store.rank([0.0, 0.0, 1.0], band="adult", top=3)
        assert ranked and ranked[0][0].slug == "mortgage"

    def test_a_concept_with_no_body_for_the_band_is_not_teachable(self):
        """Both halves of `teachable_at` matter, and this is the second.

        A concept inside the band range with nothing written at or below that
        band is not teachable, and saying so here stops the resolver returning
        something the renderer would have to apologise for.
        """
        bodiless = concept("x", band_min="5-8", bodies={"adult": "adult only"})
        assert not bodiless.teachable_at("5-8")
        assert bodiless.teachable_at("adult")


class TestDegradation:
    """Every collaborator is optional and none of them may raise into a turn."""

    @pytest.mark.asyncio
    async def test_no_collaborators_at_all_declines_rather_than_raising(self, store):
        resolution = await resolve_concept("anything", band="9-12", store=store)
        assert resolution.source == "none"

    @pytest.mark.asyncio
    async def test_an_embedder_that_raises_falls_back_to_lexical(self, store):
        """An embeddings outage costs recall, not the lesson.

        The store still holds complete teaching material; what it has lost is the
        index. Word overlap over titles and aliases is a poor index and an
        enormously better answer than declining every question -- so a learner
        asking about a concept BY NAME is still taught during an outage.
        """
        async def explode(_text):
            raise RuntimeError("embeddings are down")

        async def retrieve(_text):
            return []

        resolution = await resolve_concept(
            "what is compound interest",
            band="9-12",
            store=store,
            embed=explode,
            retrieve=retrieve,
        )
        assert resolution.concept is not None
        assert resolution.concept.slug == "compound_interest"

    @pytest.mark.asyncio
    async def test_lexical_matching_does_not_invent_a_match(self, store):
        """The fallback must decline on a topic it does not hold, like the real path."""
        async def explode(_text):
            raise RuntimeError("embeddings are down")

        async def retrieve(_text):
            return []

        resolution = await resolve_concept(
            "what is a collateralised debt obligation",
            band="9-12",
            store=store,
            embed=explode,
            retrieve=retrieve,
        )
        assert resolution.source == "none"

    @pytest.mark.asyncio
    async def test_a_retriever_that_raises_declines(self, store):
        async def explode(_text):
            raise RuntimeError("pgvector is down")

        resolution = await resolve_concept(
            "what is cryptocurrency",
            band="9-12",
            store=store,
            embed=embedder([0.1, 0.1, 0.1]),
            retrieve=explode,
        )
        assert resolution.source == "none"

    @pytest.mark.asyncio
    async def test_an_active_concept_that_vanished_does_not_break_the_turn(self, store):
        """A reseed between turns removes the concept the learner was on."""
        resolution = await resolve_concept(
            "yes", band="9-12", active_concept_id="CON-9999", store=store
        )
        assert resolution.source == "none"

    def test_a_zero_vector_concept_poisons_nothing(self):
        """One bad row costs itself and not the matrix.

        Normalising a zero vector divides by zero, and a NaN row takes every
        OTHER concept's score with it -- so the store would resolve nothing at
        all because one concept embedded badly.
        """
        holder = ConceptStore()
        holder.load(
            [
                concept("good", vector=[1.0, 0.0, 0.0]),
                concept("broken", vector=[0.0, 0.0, 0.0]),
            ]
        )
        ranked = holder.rank([1.0, 0.0, 0.0], band="5-8", top=2)
        assert ranked[0][0].slug == "good"
        assert ranked[0][1] == pytest.approx(1.0)
