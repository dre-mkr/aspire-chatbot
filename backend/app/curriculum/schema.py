"""The shape of a lesson, and the loader that refuses to start without one."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.safety import vocab

logger = logging.getLogger(__name__)

Band = Literal["5-8", "9-12", "13-15", "16-18", "adult"]

#: Bands youngest first.
BANDS: tuple[Band, ...] = ("5-8", "9-12", "13-15", "16-18", "adult")

CONTENT_DIR = Path(__file__).resolve().parent / "content"


def band_index(band: str) -> int:
    try:
        return BANDS.index(band)  # type: ignore[arg-type]
    except ValueError:
        return -1


def for_band(mapping: dict[str, Any], band: str) -> Any | None:
    """The entry for `band`, falling back to the nearest YOUNGER band."""
    index = band_index(band)
    if index < 0:
        return None
    for step in range(index, -1, -1):
        if BANDS[step] in mapping:
            return mapping[BANDS[step]]
    return None


class _Node(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Concept(_Node):
    """One idea, with the bands that may meet it and the words it introduces."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    name: str = Field(max_length=80)
    band_min: Band
    band_max: Band = "adult"
    prerequisites: list[str] = Field(default_factory=list)
    #: The words this concept teaches.
    vocabulary: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _bands_are_ordered(self) -> "Concept":
        if band_index(self.band_min) > band_index(self.band_max):
            raise ValueError(f"{self.id}: band_min is above band_max")
        return self

    @model_validator(mode="after")
    def _vocabulary_is_permitted_at_band_min(self) -> "Concept":
        """A concept may not teach a word its youngest band cannot hear."""
        for word in self.vocabulary:
            if vocab.check(word, self.band_min):
                raise ValueError(
                    f"{self.id}: vocabulary {word!r} is banned at {self.band_min}"
                )
        return self


class CheckQuestion(_Node):
    """One check-for-understanding question."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_]{1,63}$")
    prompt: dict[str, str]
    options: list[str] = Field(default_factory=list, max_length=4)
    #: Index into `options`. None for a free-text question.
    answer: int | None = None
    #: Concept words that count as a correct free-text answer, lowercase.
    accept: list[str] = Field(default_factory=list)
    graded: bool = True
    #: The three rungs, band-keyed.
    hints: dict[str, list[str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _an_answer_indexes_an_option(self) -> "CheckQuestion":
        if self.answer is not None and not 0 <= self.answer < len(self.options):
            raise ValueError(f"{self.id}: answer does not index an option")
        if self.graded and self.answer is None and not self.accept:
            raise ValueError(
                f"{self.id}: a graded question needs either an answer index or "
                "an accept list"
            )
        return self


class Misconception(_Node):
    """What learners get wrong, and the sentence to say when they do."""

    wrong: str = Field(max_length=200)
    say: str = Field(max_length=200)


class EducatorGuide(_Node):
    """One lesson, rendered for somebody who will teach it."""

    timing_minutes: int = Field(ge=5, le=120)
    materials: list[str] = Field(default_factory=list)
    misconceptions: list[Misconception] = Field(default_factory=list)
    extension: str = Field(default="", max_length=240)


class GuardianGuide(_Node):
    """One lesson, rendered for somebody who will do it alongside a child."""

    doing: str = Field(max_length=200)
    do_together: str = Field(max_length=300)
    ask_them: str = Field(max_length=200)
    got_it_sounds_like: str = Field(max_length=200)


class Guide(_Node):
    """The adult renderings of a lesson.

    BOTH MAPS ARE KEYED BY THE BAND OF THE CHILD, not of the reader. A guardian
    and an educator both read at `adult`; what changes is the age of the learner
    they are asking about. Pass the child's band to `for_band`, never the
    reader's, or every lookup resolves to nothing.
    """

    educator: dict[str, EducatorGuide] = Field(default_factory=dict)
    guardian: dict[str, GuardianGuide] = Field(default_factory=dict)


class Lesson(_Node):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    module_id: str
    concept_id: str
    order: int = Field(ge=1)
    objective: str = Field(max_length=200)
    #: Band-keyed. Each entry is the ordered sequence of things to say.
    teach_points: dict[str, list[str]]
    #: Band-keyed.
    examples: dict[str, list[str]]
    check_questions: list[CheckQuestion] = Field(min_length=1)
    suggested_widget_kind: str | None = None
    #: Band-keyed by the CHILD's band. See `Guide`.
    guide: Guide = Field(default_factory=Guide)

    @field_validator("guide")
    @classmethod
    def _guide_bands_are_real(cls, value: "Guide") -> "Guide":
        for name, mapping in (("educator", value.educator), ("guardian", value.guardian)):
            unknown = set(mapping) - set(BANDS)
            if unknown:
                raise ValueError(f"guide.{name}: unknown age band(s): {sorted(unknown)}")
        return value

    def educator_guide(self, child_band: str) -> "EducatorGuide | None":
        """The teaching notes for a class at this band."""
        return for_band(self.educator_map(), child_band)

    def guardian_guide(self, child_band: str) -> "GuardianGuide | None":
        """What to say to the adult of a child at this band."""
        return for_band(self.guide.guardian, child_band)

    def educator_map(self) -> dict[str, "EducatorGuide"]:
        return self.guide.educator

    @field_validator("teach_points", "examples")
    @classmethod
    def _bands_are_real(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        unknown = set(value) - set(BANDS)
        if unknown:
            raise ValueError(f"unknown age band(s): {sorted(unknown)}")
        return value

    def teach_for(self, band: str) -> list[str]:
        return list(for_band(self.teach_points, band) or [])

    def examples_for(self, band: str) -> list[str]:
        return list(for_band(self.examples, band) or [])


class Module(_Node):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    title: str = Field(max_length=120)
    order: int = Field(ge=1)
    band_min: Band
    band_max: Band = "adult"
    concepts: list[Concept] = Field(default_factory=list)
    lessons: list[Lesson] = Field(min_length=1)

    @model_validator(mode="after")
    def _lessons_are_consistent(self) -> "Module":
        orders = [lesson.order for lesson in self.lessons]
        if sorted(orders) != list(range(1, len(orders) + 1)):
            raise ValueError(
                f"{self.id}: lesson orders must be 1..n with no gaps, got {sorted(orders)}"
            )

        known = {concept.id for concept in self.concepts}
        for lesson in self.lessons:
            if lesson.module_id != self.id:
                raise ValueError(f"{lesson.id}: module_id does not match {self.id}")
            if lesson.concept_id not in known:
                raise ValueError(
                    f"{lesson.id}: concept {lesson.concept_id!r} is not defined in "
                    f"this module"
                )

        for concept in self.concepts:
            for prerequisite in concept.prerequisites:
                # Only intra-module prerequisites are checked here.
                if prerequisite in known and prerequisite == concept.id:
                    raise ValueError(f"{concept.id}: depends on itself")
        return self

    def lessons_in_order(self) -> list[Lesson]:
        return sorted(self.lessons, key=lambda lesson: lesson.order)


class Curriculum:
    """Every module, loaded and cross-checked."""

    def __init__(self, modules: list[Module]) -> None:
        self.modules = sorted(modules, key=lambda module: module.order)
        self.by_id = {module.id: module for module in self.modules}
        self.concepts = {
            concept.id: concept for module in self.modules for concept in module.concepts
        }
        self.lessons = {
            lesson.id: lesson for module in self.modules for lesson in module.lessons
        }
        self.validate_prerequisites()

    def validate_prerequisites(self) -> None:
        """Every prerequisite exists and is not above the band that needs it."""
        for concept in self.concepts.values():
            for prerequisite in concept.prerequisites:
                required = self.concepts.get(prerequisite)
                if required is None:
                    raise ValueError(
                        f"{concept.id}: prerequisite {prerequisite!r} is not defined "
                        "in any module"
                    )
                if band_index(required.band_min) > band_index(concept.band_min):
                    raise ValueError(
                        f"{concept.id} is available from {concept.band_min} but "
                        f"requires {prerequisite}, which starts at "
                        f"{required.band_min}"
                    )

    def lessons_for_band(self, band: str) -> list[Lesson]:
        """Every lesson a learner in this band may be given, in course order."""
        out: list[Lesson] = []
        for module in self.modules:
            if not band_index(module.band_min) <= band_index(band) <= band_index(
                module.band_max
            ):
                continue
            for lesson in module.lessons_in_order():
                concept = self.concepts[lesson.concept_id]
                if (
                    band_index(concept.band_min)
                    <= band_index(band)
                    <= band_index(concept.band_max)
                ):
                    out.append(lesson)
        return out

    def first_lesson_for(self, band: str) -> Lesson | None:
        lessons = self.lessons_for_band(band)
        return lessons[0] if lessons else None


def load_module(path: Path) -> Module:
    """One YAML file into a validated `Module`."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError(f"{path.name} is not valid YAML: {error}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} does not contain a module object")
    try:
        return Module.model_validate(data)
    except Exception as error:
        raise ValueError(f"{path.name}: {error}") from None


_cache: Curriculum | None = None


def load_all(directory: Path | None = None, *, refresh: bool = False) -> Curriculum:
    """Every module in the content directory, validated together."""
    global _cache
    if _cache is not None and not refresh and directory is None:
        return _cache

    root = directory or CONTENT_DIR
    files = sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml"))
    if not files:
        raise ValueError(
            f"No curriculum files in {root}. The learning agent has nothing to "
            "teach; refusing to pretend otherwise."
        )

    curriculum = Curriculum([load_module(path) for path in files])
    logger.info(
        "Curriculum loaded: %d module(s), %d lesson(s), %d concept(s).",
        len(curriculum.modules),
        len(curriculum.lessons),
        len(curriculum.concepts),
    )
    if directory is None:
        _cache = curriculum
    return curriculum
