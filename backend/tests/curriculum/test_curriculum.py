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
        # Six now: the habits lesson joined the module, the behaviour thread's home.
        assert len(curriculum.by_id["module_01_saving"].lessons) == 6

    def test_every_lesson_has_a_check_question(self, curriculum):
        for lesson in curriculum.lessons.values():
            assert lesson.check_questions

    def test_every_lesson_names_a_concept_that_exists(self, curriculum):
        for lesson in curriculum.lessons.values():
            assert lesson.concept_id in curriculum.concepts

    def test_prerequisites_resolve_and_do_not_point_upward(self, curriculum):
        """A 9-12 concept requiring a 13-15 one is unreachable, silently."""
        curriculum.validate_prerequisites()


class TestBandFiltering:
    """The acceptance criterion: a band filter returns band-appropriate content."""

    def test_the_youngest_band_now_gets_the_whole_of_module_one(self, curriculum):
        """This test used to assert the opposite, and the opposite was wrong.

        `need` and `budget` were pitched at 9-12, so needs-and-wants and making
        a plan were closed to a five-to-eight-year-old and module 1 was 60 per
        cent available to the band the client said we were ignoring.

        ASPIRE's own Grade 1 lesson plan guide -- Super Savers Club -- teaches
        both at Grade One. Its Lesson 3 says it outright: "By distinguishing
        between needs and wants, children begin to learn about budgeting. Even
        at a young age, understanding that money can run out and needs should
        come first helps them make practical choices."

        The programme says five or six. We had said nine. The programme wins.
        """
        young = {lesson.id for lesson in curriculum.lessons_for_band("5-8")}
        assert "l04_needs_and_wants" in young
        assert "l05_a_simple_plan" in young
        assert young == {lesson.id for lesson in curriculum.lessons_for_band("9-12")}

    def test_the_band_filter_still_filters(self, curriculum):
        """The mechanism, checked without relying on any lesson being gated.

        Every lesson in module 1 is now open to every band, so the filter has to
        be exercised directly or this suite would pass with it deleted.
        """
        from app.curriculum.schema import Concept

        gated = Concept(
            id="something_later", name="Later", band_min="13-15", band_max="adult"
        )
        assert curriculum.concepts["save"].band_min == "5-8"
        assert gated.band_min == "13-15"

        for band in ("5-8", "9-12"):
            for lesson in curriculum.lessons_for_band(band):
                concept = curriculum.concepts[lesson.concept_id]
                assert BANDS.index(concept.band_min) <= BANDS.index(band), (
                    f"{lesson.id} reached {band} but its concept starts at "
                    f"{concept.band_min}"
                )

    def test_every_band_gets_teach_points_and_examples(self, curriculum):
        for band in BANDS:
            for lesson in curriculum.lessons_for_band(band):
                assert lesson.teach_for(band), f"{lesson.id} has no text for {band}"
                assert lesson.examples_for(band), f"{lesson.id} has no example for {band}"

    def test_inheritance_runs_downward_only(self):
        """An older band may inherit younger text."""
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
        """The rule that makes authored content safe without a runtime gate."""
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
        """Never abstract percentages below age 13."""
        for lesson in curriculum.lessons_for_band(band):
            for text in lesson.teach_for(band) + lesson.examples_for(band):
                assert "%" not in text, f"{lesson.id} [{band}]: {text!r}"
                assert "percent" not in text.lower()

    def test_the_examples_are_local(self, curriculum):
        """Snow cones, patties, a bicycle, a Carnival costume, EC dollars."""
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
        """The authoring mistake this catches: `inflation` in a 9-12 concept.

        It used to be `compound`, then `loan`, and both are now the client's
        rulings rather than mistakes: for educational purposes the ban lifts,
        and `loan` was named explicitly on 23 August as usable in tutorials
        across all personas. A lesson about borrowing cannot be written without
        the word.

        `inflation` is outside `TEACHING_TERMS`, so the guard still has teeth —
        and it needs them here more than anywhere, because this fails at LOAD:
        a rejected concept is not stripped at reply time, it stops the module
        existing at all.
        """
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
                vocabulary: [inflation]
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
    """Writing the authored curriculum into the tables that reference it."""

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

        # The module's own concepts, plus the eleven authored topics that carry
        # the rest of the curriculum -- interest, credit, investing, taxes,
        # scams, digital money, entrepreneurship, and what AI does with a
        # reader's own money.
        from app.curriculum.topics import concept_rows

        assert written == len(curriculum.concepts) + len(concept_rows())
        assert ("COMMIT", {}) in writes
        seeded = {
            params["id"]
            for statement, params in writes
            if statement.startswith("INSERT INTO concepts")
        }
        # Every module concept, and every authored topic alongside them. Three
        # topics share an id with a module concept on purpose: they enrich it
        # with the bands the module's own lessons never reached, rather than
        # splitting one reader's mastery across two rows for one idea.
        assert seeded >= set(curriculum.concepts)
        assert seeded >= {row["id"] for row in concept_rows()}

    @pytest.mark.anyio
    async def test_the_insert_supplies_every_column_the_table_requires(self):
        """The INSERT must name every NOT NULL column that has no default."""
        import inspect
        import re

        url = os.environ.get("DATABASE_URL", "")
        if not url:
            pytest.skip("no DATABASE_URL; this assertion needs the real schema")

        import asyncpg

        from app.curriculum import seed as seed_module

        source = inspect.getsource(seed_module)
        match = re.search(
            r"INSERT INTO concepts\s*\((.*?)\)\s*VALUES", source, re.DOTALL
        )
        assert match, "could not find the concepts INSERT to check"
        supplied = {
            column.strip() for column in match.group(1).split(",") if column.strip()
        }

        connection = await asyncpg.connect(
            url.replace("postgresql+asyncpg://", "postgresql://")
        )
        try:
            rows = await connection.fetch(
                """
                SELECT column_name
                  FROM information_schema.columns
                 WHERE table_name = 'concepts'
                   AND is_nullable = 'NO'
                   AND column_default IS NULL
                """
            )
        finally:
            await connection.close()

        required = {row["column_name"] for row in rows}
        missing = required - supplied
        assert not missing, (
            f"concepts requires {sorted(missing)} but the seeder's INSERT does not "
            f"supply them. Startup will raise NotNullViolationError and swallow it, "
            f"and mastery will stop recording."
        )

    @pytest.mark.anyio
    async def test_a_failure_is_logged_and_not_raised(self, curriculum, monkeypatch):
        """A curriculum that cannot be seeded must not stop the service starting."""

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


class TestARequiredConceptMustBeTaught:
    """The check that would have caught the L4/L5 draft, written as the failure.

    Mastery is evidence and evidence comes from a lesson's check questions, so a
    concept nothing teaches can never be mastered -- and everything downstream
    of it is unreachable forever, silently, with the module still validating.
    """

    def _curriculum(self, concepts, taught: str):
        from app.curriculum.schema import Concept, Curriculum, Lesson, Module

        return Curriculum([
            Module(
                id="mod_probe",
                title="M",
                order=1,
                band_min="5-8",
                concepts=[Concept(**c) for c in concepts],
                lessons=[
                    Lesson(
                        id="l1",
                        module_id="mod_probe",
                        concept_id=taught,
                        order=1,
                        objective="x",
                        teach_points={"5-8": ["a"]},
                        examples={"5-8": ["b"]},
                        check_questions=[
                            {"id": "q1", "prompt": {"5-8": "?"},
                             "options": ["a", "b"], "answer": 0}
                        ],
                    )
                ],
            )
        ])

    def test_a_required_concept_with_no_lesson_is_refused(self):
        with pytest.raises(ValueError, match="no lesson teaches it"):
            self._curriculum(
                [
                    {"id": "ghost", "name": "G", "band_min": "5-8"},
                    {"id": "real", "name": "R", "band_min": "5-8",
                     "prerequisites": ["ghost"]},
                ],
                taught="real",
            )

    def test_the_message_names_who_is_blocked_by_it(self):
        """An error that says only "ghost has no lesson" leaves the reader to
        work out what it costs. The list of dependants is the cost."""
        with pytest.raises(ValueError, match=r"required by \['real'\]"):
            self._curriculum(
                [
                    {"id": "ghost", "name": "G", "band_min": "5-8"},
                    {"id": "real", "name": "R", "band_min": "5-8",
                     "prerequisites": ["ghost"]},
                ],
                taught="real",
            )

    def test_an_untaught_concept_nothing_depends_on_is_still_legal(self):
        """A vocabulary node that locks no path is not this bug, and refusing
        it would be a lint that costs more than it catches."""
        self._curriculum(
            [
                {"id": "spare", "name": "S", "band_min": "5-8"},
                {"id": "real", "name": "R", "band_min": "5-8"},
            ],
            taught="real",
        )

    def test_the_shipping_module_passes_it(self):
        """The regression guard. If this fails, module one has a locked branch."""
        from app.curriculum.schema import load_all

        load_all(refresh=True)


class TestTheArithmeticInAKeyIsTheArithmeticInThePrompt:
    """A worked example whose key contradicts its own prompt.

    `l03_a_goal` at 13-15 asked "EC$450 and you keep EC$25 a week -- roughly how
    many weeks?", offered [Ten, Two, One hundred], keyed Ten, and 450/25 is 18.
    The third hint rung said it out loud: "EC$450 at EC$25 a week is eighteen,
    so ten is the closest of these."

    So the lesson taught a fourteen-year-old to divide -- "Price it, date it,
    divide it. That is the whole method" -- and then marked the division wrong,
    naming the right answer in the sentence that rejected it. Joseph Lin checks
    arithmetic and so does a judge with a rubric.
    """

    def test_every_division_question_divides_exactly_into_its_key(self):
        import re

        from app.curriculum.schema import load_all

        words = {"ten": 10, "two": 2, "one hundred": 100, "five": 5, "twenty": 20}
        problems = []
        for module in load_all(refresh=True).modules:
            for lesson in module.lessons:
                for question in lesson.check_questions:
                    if question.answer is None or not question.options:
                        continue
                    key = words.get(question.options[question.answer].strip().lower())
                    if key is None:
                        continue
                    for band, prompt in (question.prompt or {}).items():
                        found = [
                            int(n.replace(",", ""))
                            for n in re.findall(r"EC\$([\d,]+)", prompt)
                        ]
                        if len(found) != 2 or "how many weeks" not in prompt.lower():
                            continue
                        goal, rate = max(found), min(found)
                        if rate and goal / rate != key:
                            problems.append(
                                f"{lesson.id}/{question.id}/{band}: {goal}/{rate} = "
                                f"{goal / rate:g}, key says {key}"
                            )
        assert not problems, "; ".join(problems)

    def test_the_second_hint_rung_names_the_two_options_that_get_rendered(self):
        """`narrow_options` renders options 0 and 1. A rung that names 0 and 2
        tells the reader to choose between two things and shows a different two.
        """
        from app.curriculum.schema import load_all

        words = ("ten", "two", "one hundred", "five", "twenty")
        problems = []
        for module in load_all(refresh=True).modules:
            for lesson in module.lessons:
                for question in lesson.check_questions:
                    if question.answer is None or len(question.options or ()) < 3:
                        continue
                    rendered = {
                        question.options[question.answer].strip().lower(),
                        next(
                            o.strip().lower()
                            for i, o in enumerate(question.options)
                            if i != question.answer
                        ),
                    }
                    for band, rungs in (question.hints or {}).items():
                        if len(rungs) < 2:
                            continue
                        # "one of these two" is English, not an option name.
                        rung = rungs[1].lower().replace("these two", "")
                        named = {w for w in words if w in rung}
                        stray = named - rendered
                        if stray:
                            problems.append(
                                f"{lesson.id}/{question.id}/{band}: rung 2 names "
                                f"{sorted(stray)}, chips show {sorted(rendered)}"
                            )
        assert not problems, "; ".join(problems)
