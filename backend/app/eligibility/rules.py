"""The audited eligibility rules, as data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.eligibility.models import Criterion, Verdict

# Every question the flow can ask, in order. The plan is a subset of these.
QUESTION_ORDER = ("age", "age_exact", "citizenship", "residence", "school", "registrant")

# What the progress indicator counts.
COUNTED = ("age", "citizenship", "residence", "school", "registrant")


def counted_position(question_id: str) -> int:
    """Which of the five steps a question belongs to. `age_exact` shares age's."""
    if question_id == "age_exact":
        question_id = "age"
    return COUNTED.index(question_id) + 1

# Valid tokens per question.
OPTIONS: dict[str, tuple[str, ...]] = {
    "age": ("under5", "5to18", "19to21", "22plus", "unsure"),
    "age_exact": ("0", "1", "2", "3", "4", "unsure"),
    "citizenship": ("born_skn", "by_descent", "neither", "unsure"),
    "residence": ("st_kitts", "nevis", "abroad", "unsure"),
    "school": ("in_school", "home_school", "not_in_school", "unsure"),
    "registrant": ("guardian", "self", "unsure"),
}

# The source rows behind each criterion, carried so the reasoning is checkable from the code rather than from a…
SOURCES: dict[str, tuple[str, ...]] = {
    "citizenship": ("ASP-027", "ASP-028", "ASP-038", "ASP-039", "ASP-240", "ASP-245"),
    "age_minimum": ("ASP-029", "ASP-041", "ASP-042", "ASP-241"),
    "age_cohort": ("ASP-030", "ASP-031", "ASP-043", "ASP-242"),
    "residence": ("ASP-032", "ASP-133", "ASP-243"),
    "school": ("ASP-033", "ASP-034", "ASP-249"),
    "island_is_not_a_gate": ("ASP-044", "ASP-247"),
    "registrant": ("ASP-049", "ASP-050", "ASP-295"),
}


@dataclass(frozen=True, slots=True)
class Decision:
    """What the answers add up to. Copy is chosen from this, never inside it."""

    verdict: Verdict
    criterion: Criterion
    # Every criterion the answers left open, in the order they were asked.
    unresolved: tuple[str, ...] = ()
    # Which result copy to render.
    copy_key: str = "likely_eligible"


def plan(answers: dict[str, str]) -> tuple[str, ...]:
    """Which questions this person gets, given what they have said so far."""
    questions = ["age"]
    if answers.get("age") == "under5":
        questions.append("age_exact")
    questions += ["citizenship", "residence", "school", "registrant"]
    return tuple(questions)


def reminder_year(answers: dict[str, str], today: date) -> int | None:
    """Roughly which year an under-5 child can register."""
    if answers.get("age") != "under5":
        return None
    raw = answers.get("age_exact")
    if raw is None or raw == "unsure":
        return None
    try:
        current = int(raw)
    except ValueError:
        return None
    return today.year + max(0, 5 - current)


def decide(answers: dict[str, str]) -> Decision:
    """Turn a complete set of answers into one of the three outcomes."""
    unresolved: list[str] = []

    # ASP-039, ASP-245. The one firm no.
    if answers.get("citizenship") == "neither":
        return Decision(
            verdict=Verdict.NOT_YET,
            criterion=Criterion.CITIZENSHIP,
            copy_key="citizenship",
        )

    age = answers.get("age")

    # ASP-029, ASP-041, ASP-042. A real "not yet", with a year attached.
    if age == "under5":
        # An unknown exact age does not block the result; it only costs the year.
        if answers.get("age_exact") == "unsure":
            unresolved.append("age_minimum")
        return Decision(
            verdict=Verdict.NOT_YET,
            criterion=Criterion.AGE_MINIMUM,
            unresolved=tuple(unresolved),
            copy_key="age_minimum",
        )

    # ASP-030 vs ASP-043/ASP-242.
    if age == "22plus":
        return Decision(
            verdict=Verdict.NOT_YET,
            criterion=Criterion.AGE_COHORT,
            unresolved=("age_cohort",),
            copy_key="age_cohort_past",
        )

    # The audit's finding A: never a flat no on this band.
    if age == "19to21" or age == "unsure":
        unresolved.append("age_cohort" if age == "19to21" else "age_minimum")

    if answers.get("citizenship") == "unsure":
        unresolved.append("citizenship")

    # Audit finding B.
    residence = answers.get("residence")
    if residence in ("abroad", "unsure"):
        unresolved.append("residence")

    # Audit finding C.
    school = answers.get("school")
    if school in ("not_in_school", "unsure"):
        unresolved.append("school")

    # `registrant` is deliberately absent from every branch above.

    if unresolved:
        first = unresolved[0]
        return Decision(
            verdict=Verdict.NEEDS_CONFIRMATION,
            criterion={
                "age_cohort": Criterion.AGE_COHORT,
                "age_minimum": Criterion.AGE_MINIMUM,
                "citizenship": Criterion.CITIZENSHIP,
                "residence": Criterion.RESIDENCE,
                "school": Criterion.SCHOOL,
            }[first],
            unresolved=tuple(unresolved),
            copy_key="needs_confirmation",
        )

    return Decision(
        verdict=Verdict.LIKELY_ELIGIBLE,
        criterion=Criterion.NONE,
        copy_key="likely_eligible",
    )


# Documents that stand IN FOR the item before them rather than adding to it.
ALTERNATIVES = frozenset({"passport"})


def documents_for(answers: dict[str, str]) -> tuple[str, ...]:
    """Which documents apply, in reading order."""
    documents: list[str] = []

    citizenship = answers.get("citizenship")
    if citizenship == "born_skn":
        # ASP-035/036 firm, ASP-250/037 as the hedged alternative.
        documents += ["birth_certificate", "passport"]
    elif citizenship == "by_descent":
        documents.append("descent_certificate")  # ASP-028, ASP-035, ASP-038
    else:
        # Unsure. Both routes, so nothing is ruled out by a guess of ours.
        documents += ["birth_certificate", "descent_certificate"]

    # ASP-248.
    if answers.get("registrant") in ("guardian", "unsure", None):
        documents.append("guardian_id")

    # ASP-251, and the weakest item in the source. Always last, always hedged.
    documents.append("proof_of_address")
    return tuple(documents)


def steps_for(answers: dict[str, str]) -> tuple[str, ...]:
    """The walkthrough, routed by island."""
    in_person = (
        "in_person_kitts"
        if answers.get("residence") == "st_kitts"
        else "in_person_events"
    )
    return ("portal", "who_fills", "documents", in_person, "after", "confirm")
