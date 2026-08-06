"""The curriculum spine: what loads, what refuses to, and what each band gets."""

from __future__ import annotations

import os
import textwrap
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from app.curriculum.schema import (  # noqa: E402
    BANDS,
    Curriculum,
    band_index,
    for_band,
    load_all,
    load_module,
)
from app.safety import vocab  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
def curriculum():
    return load_all(refresh=True)


class TestModuleOneLoads:
    """The acceptance criterion: module 1 loads and validates."""

    def test_it_loads(self, curriculum):
        assert "module_01_saving" in curriculum.by_id
        assert len(curriculum.by_id["module_01_saving"].lessons) == 5

    def test_every_lesson_has_a_check_question(self, curriculum):
        for lesson in curriculum.lessons.values():
            assert lesson.check_questions

    def test_every_lesson_names_a_concept_that_exists(self, curriculum):
        for lesson in curriculum.lessons.values():
            assert lesson.concept_id in curriculum.concepts

    def test_prerequisites_resolve_and_do_not_point_upward(self, curriculum):
        """A 9-12 concept requiring a 13-15 one is unreachable, silently.

        Nothing at runtime reports it -- placement simply never selects that
        lesson -- which is why it is checked at load.
        """
        curriculum.validate_prerequisites()


class TestBandFiltering:
    """The acceptance criterion: a band filter returns band-appropriate content."""

    def test_a_five_to_eight_does_not_get_the_nine_to_twelve_lessons(self, curriculum):
        young = {lesson.id for lesson in curriculum.lessons_for_band("5-8")}
        older = {lesson.id for lesson in curriculum.lessons_for_band("9-12")}
        assert young < older
        assert "l04_needs_and_wants" not in young
        assert "l05_a_simple_plan" not in young

    def test_every_band_gets_teach_points_and_examples(self, curriculum):
        for band in BANDS:
            for lesson in curriculum.lessons_for_band(band):
                assert lesson.teach_for(band), f"{lesson.id} has no text for {band}"
                assert lesson.examples_for(band), f"{lesson.id} has no example for {band}"

    def test_inheritance_runs_downward_only(self):
        """An older band may inherit younger text. Never the reverse.

        Upward inheritance would hand a nine-year-old the thirteen-year-old's
        wording -- exactly what the vocabulary gate exists to prevent, arriving
        from content a human approved.
        """
        mapping = {"9-12": "middle"}
        assert for_band(mapping, "13-15") == "middle"
        assert for_band(mapping, "adult") == "middle"
        assert for_band(mapping, "5-8") is None

    def test_an_unknown_band_resolves_to_nothing(self):
        assert for_band({"5-8": "x"}, "42") is None
        assert band_index("42") == -1


class TestTheContentItself:
    """Properties of the authored text, checked as data rather than reviewed."""

    @pytest.mark.parametrize("band", ["5-8", "9-12", "13-15"])
    def test_no_teach_point_uses_a_word_the_band_has_not_met(self, curriculum, band):
        """The rule that makes authored content safe without a runtime gate.

        `safety_out` would catch a violation on a live turn -- by re-prompting a
        model to rewrite a sentence a human wrote, which is the wrong repair for
        the wrong problem. Catching it here means it never ships.
        """
        for lesson in curriculum.lessons_for_band(band):
            for text in lesson.teach_for(band):
                violations = vocab.check(text, band)
                assert not violations, f"{lesson.id} [{band}]: {violations} in {text!r}"

    @pytest.mark.parametrize("band", ["5-8", "9-12", "13-15"])
    def test_no_example_uses_a_word_the_band_has_not_met(self, curriculum, band):
        for lesson in curriculum.lessons_for_band(band):
            for text in lesson.examples_for(band):
                violations = vocab.check(text, band)
                assert not violations, f"{lesson.id} [{band}]: {violations} in {text!r}"

    @pytest.mark.parametrize("band", ["5-8", "9-12"])
    def test_no_abstract_percentage_below_thirteen(self, curriculum, band):
        """Never abstract percentages below age 13.

        `proportion` teaches the same fact as "three coins out of ten", which a
        nine-year-old already has the equipment to hold.
        """
        for lesson in curriculum.lessons_for_band(band):
            for text in lesson.teach_for(band) + lesson.examples_for(band):
                assert "%" not in text, f"{lesson.id} [{band}]: {text!r}"
                assert "percent" not in text.lower()

    def test_the_examples_are_local(self, curriculum):
        """Snow cones, patties, a bicycle, a Carnival costume, EC dollars.

        An example a child here has not seen teaches nothing, however clear.
        """
        corpus = " ".join(
            text
            for lesson in curriculum.lessons.values()
            for band in BANDS
            for text in lesson.examples_for(band)
        ).lower()
        for local in ("snow cone", "patties", "bicycle", "carnival", "ec$", "christmas"):
            assert local in corpus, f"no example mentions {local!r}"

    def test_hints_never_contain_a_negative_word(self, curriculum):
        from app.agents.learn.nodes.hint_ladder import contains_negative

        for lesson in curriculum.lessons.values():
            for question in lesson.check_questions:
                for band, rungs in question.hints.items():
                    for text in rungs:
                        assert not contains_negative(text), (
                            f"{question.id} [{band}]: {text!r}"
                        )

    def test_every_graded_question_has_three_rungs_for_its_bands(self, curriculum):
        for lesson in curriculum.lessons.values():
            for question in lesson.check_questions:
                if not question.graded:
                    continue
                for band, rungs in question.hints.items():
                    assert len(rungs) == 3, f"{question.id} [{band}] has {len(rungs)}"


class TestValidationFailsLoudly:
    """A malformed lesson must not be discovered by a child mid-sentence."""

    def _write(self, tmp_path: Path, body: str) -> Path:
        path = tmp_path / "bad.yaml"
        path.write_text(textwrap.dedent(body), encoding="utf-8")
        return path

    def test_a_concept_may_not_teach_a_word_its_band_cannot_hear(self, tmp_path):
        """The authoring mistake this catches: "compound" in a 9-12 concept."""
        path = self._write(
            tmp_path,
            """
            id: bad_module
            title: Bad
            order: 1
            band_min: "9-12"
            concepts:
              - id: growth
                name: Growth
                band_min: "9-12"
                vocabulary: [compound]
            lessons:
              - id: l1
                module_id: bad_module
                concept_id: growth
                order: 1
                objective: x
                teach_points: {"9-12": [a]}
                examples: {"9-12": [b]}
                check_questions:
                  - id: q1
                    prompt: {"9-12": "?"}
                    options: [a, b]
                    answer: 0
            """,
        )
        with pytest.raises(ValueError, match="banned at 9-12"):
            load_module(path)

    def test_lesson_orders_must_have_no_gaps(self, tmp_path):
        path = self._write(
            tmp_path,
            """
            id: gappy
            title: Gappy
            order: 1
            band_min: "9-12"
            concepts:
              - {id: c1, name: C, band_min: "9-12"}
            lessons:
              - id: l1
                module_id: gappy
                concept_id: c1
                order: 1
                objective: x
                teach_points: {"9-12": [a]}
                examples: {"9-12": [b]}
                check_questions: [{id: q1, prompt: {"9-12": "?"}, options: [a, b], answer: 0}]
              - id: l3
                module_id: gappy
                concept_id: c1
                order: 3
                objective: x
                teach_points: {"9-12": [a]}
                examples: {"9-12": [b]}
                check_questions: [{id: q2, prompt: {"9-12": "?"}, options: [a, b], answer: 0}]
            """,
        )
        with pytest.raises(ValueError, match="no gaps"):
            load_module(path)

    def test_an_unknown_band_key_is_refused(self, tmp_path):
        path = self._write(
            tmp_path,
            """
            id: mod_x
            title: M
            order: 1
            band_min: "9-12"
            concepts: [{id: c1, name: C, band_min: "9-12"}]
            lessons:
              - id: l1
                module_id: mod_x
                concept_id: c1
                order: 1
                objective: x
                teach_points: {"8-9": [a]}
                examples: {"9-12": [b]}
                check_questions: [{id: q1, prompt: {"9-12": "?"}, options: [a, b], answer: 0}]
            """,
        )
        with pytest.raises(ValueError, match="unknown age band"):
            load_module(path)

    def test_an_answer_index_outside_the_options_is_refused(self, tmp_path):
        path = self._write(
            tmp_path,
            """
            id: mod_x
            title: M
            order: 1
            band_min: "9-12"
            concepts: [{id: c1, name: C, band_min: "9-12"}]
            lessons:
              - id: l1
                module_id: mod_x
                concept_id: c1
                order: 1
                objective: x
                teach_points: {"9-12": [a]}
                examples: {"9-12": [b]}
                check_questions: [{id: q1, prompt: {"9-12": "?"}, options: [a, b], answer: 5}]
            """,
        )
        with pytest.raises(ValueError, match="does not index"):
            load_module(path)

    def test_a_lesson_naming_an_undefined_concept_is_refused(self, tmp_path):
        path = self._write(
            tmp_path,
            """
            id: mod_x
            title: M
            order: 1
            band_min: "9-12"
            concepts: [{id: c1, name: C, band_min: "9-12"}]
            lessons:
              - id: l1
                module_id: mod_x
                concept_id: missing
                order: 1
                objective: x
                teach_points: {"9-12": [a]}
                examples: {"9-12": [b]}
                check_questions: [{id: q1, prompt: {"9-12": "?"}, options: [a, b], answer: 0}]
            """,
        )
        with pytest.raises(ValueError, match="not defined"):
            load_module(path)

    def test_an_empty_content_directory_refuses_rather_than_serving_nothing(
        self, tmp_path
    ):
        """A learning agent with nothing to teach must say so at startup."""
        with pytest.raises(ValueError, match="nothing to teach"):
            load_all(tmp_path)

    def test_an_upward_prerequisite_is_refused(self):
        from app.curriculum.schema import Concept, Lesson, Module

        module = Module(
            id="mod_x",
            title="M",
            order=1,
            band_min="9-12",
            concepts=[
                Concept(id="early", name="E", band_min="9-12", prerequisites=["late"]),
                Concept(id="late", name="L", band_min="13-15"),
            ],
            lessons=[
                Lesson(
                    id="l1",
                    module_id="mod_x",
                    concept_id="early",
                    order=1,
                    objective="x",
                    teach_points={"9-12": ["a"]},
                    examples={"9-12": ["b"]},
                    check_questions=[
                        {"id": "q1", "prompt": {"9-12": "?"}, "options": ["a", "b"], "answer": 0}
                    ],
                )
            ],
        )
        with pytest.raises(ValueError, match="which starts at 13-15"):
            Curriculum([module])


# ── the seed ─────────────────────────────────────────────────────────────────


class TestTheSeed:
    """Writing the authored curriculum into the tables that reference it.

    The gap this closes was invisible from every test in this file. The YAML
    loaded, validated and served lessons perfectly — and `concepts` was empty,
    so `mastery.concept_id` had nothing to reference and every attempt to record
    what a child had learned raised a foreign-key violation.

    The learning tests could not see it either: they use the in-memory store,
    which has no foreign keys to violate. Found by running one widget
    interaction against the real database.
    """

    @pytest.mark.anyio
    async def test_it_writes_every_concept(self, curriculum, monkeypatch):
        writes: list[tuple[str, dict]] = []

        class _Db:
            async def execute(self, statement, params=None):
                writes.append((str(statement).strip()[:24], params or {}))

            async def commit(self):
                writes.append(("COMMIT", {}))

        @asynccontextmanager
        async def _session():
            yield _Db()

        from app.curriculum import seed

        import app.db as db_module

        monkeypatch.setattr(db_module, "database_enabled", lambda: True)
        monkeypatch.setattr(db_module, "session", _session)

        written = await seed.seed_curriculum(curriculum)

        assert written == len(curriculum.concepts)
        assert ("COMMIT", {}) in writes
        seeded = {
            params["id"]
            for statement, params in writes
            if statement.startswith("INSERT INTO concepts")
        }
        assert seeded == set(curriculum.concepts)

    @pytest.mark.anyio
    async def test_a_failure_is_logged_and_not_raised(self, curriculum, monkeypatch):
        """A curriculum that cannot be seeded must not stop the service starting.

        It runs in the lifespan. Raising would mean refusing to answer anybody's
        questions because a scheduling hint could not be recorded.
        """

        @asynccontextmanager
        async def _broken():
            raise RuntimeError("no database")
            yield  # pragma: no cover

        import app.db as db_module
        from app.curriculum import seed

        monkeypatch.setattr(db_module, "database_enabled", lambda: True)
        monkeypatch.setattr(db_module, "session", _broken)

        assert await seed.seed_curriculum(curriculum) == 0

    @pytest.mark.anyio
    async def test_no_database_writes_nothing(self, curriculum, monkeypatch):
        import app.db as db_module
        from app.curriculum import seed

        monkeypatch.setattr(db_module, "database_enabled", lambda: False)
        assert await seed.seed_curriculum(curriculum) == 0
