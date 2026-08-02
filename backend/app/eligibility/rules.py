"""The audited eligibility rules, as data.

**Every rule in this file cites the knowledge-base row it came from.** That is
the hard constraint the feature was built under: a criterion with no `ASP-xxx`
beside it does not belong here, because a confidently wrong "you do not qualify"
turns away a young person who was entitled to the programme.

Three findings from the audit shape the logic more than anything else:

1. **The 13 December 2023 clause.** ASP-030 extends eligibility to anyone who
   was "18 or under on 13 December 2023" — born on or after 14 December 2004,
   which today is people well past 18. ASP-043 and ASP-242 read the other way.
   A naive `age > 18 -> not eligible` test would refuse people the source may
   cover, so 19-21 routes to NEEDS CONFIRMATION and never to a no.

2. **Only one firm refusal exists.** ASP-039: "Non-citizens and permanent
   residents are not eligible." Everything else that is not a clean yes is a
   NEEDS CONFIRMATION, including living abroad (ASP-032 is firm but ASP-133 and
   ASP-243 allow arrangements) and not currently being in school (ASP-033 is
   firm but silent on a five-year-old who has not started).

3. **Island decides nothing.** ASP-044 and ASP-247 cover both islands
   identically. It is asked because it carries the residency gate and because
   the only walk-in centre in the source is in Basseterre — it routes the
   walkthrough, never the verdict.

`plan()` and `decide()` are pure. They do not read the clock except through the
`today` argument, they do not call a model, and they do not log.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.eligibility.models import Criterion, Verdict

# Every question the flow can ask, in order. The plan is a subset of these.
QUESTION_ORDER = ("age", "age_exact", "citizenship", "residence", "school", "registrant")

# What the progress indicator counts. `age_exact` is deliberately absent: it is
# a follow-up to the age question, not a step of its own, and counting it made
# the indicator read "1 of 5" and then "2 of 6" the moment someone tapped
# "Under 5". A progress bar that grows while you answer it is worse than one
# that is slightly coarse.
COUNTED = ("age", "citizenship", "residence", "school", "registrant")


def counted_position(question_id: str) -> int:
    """Which of the five steps a question belongs to. `age_exact` shares age's."""
    if question_id == "age_exact":
        question_id = "age"
    return COUNTED.index(question_id) + 1

# Valid tokens per question. The engine rejects anything not in here, which is
# what stops a crafted request from steering the verdict with a made-up answer.
OPTIONS: dict[str, tuple[str, ...]] = {
    "age": ("under5", "5to18", "19to21", "22plus", "unsure"),
    "age_exact": ("0", "1", "2", "3", "4", "unsure"),
    "citizenship": ("born_skn", "by_descent", "neither", "unsure"),
    "residence": ("st_kitts", "nevis", "abroad", "unsure"),
    "school": ("in_school", "home_school", "not_in_school", "unsure"),
    "registrant": ("guardian", "self", "unsure"),
}

# The source rows behind each criterion, carried so the reasoning is checkable
# from the code rather than from a document beside it.
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
    # Which result copy to render. Not the same as `criterion`: two criteria can
    # share a verdict but need different words.
    copy_key: str = "likely_eligible"


def plan(answers: dict[str, str]) -> tuple[str, ...]:
    """Which questions this person gets, given what they have said so far.

    Computed rather than fixed because the under-5 branch asks one extra
    question, and a progress indicator that says "of 5" and then shows a sixth
    is a small dishonesty the flow does not need.
    """
    questions = ["age"]
    if answers.get("age") == "under5":
        questions.append("age_exact")
    questions += ["citizenship", "residence", "school", "registrant"]
    return tuple(questions)


def reminder_year(answers: dict[str, str], today: date) -> int | None:
    """Roughly which year an under-5 child can register.

    Deliberately approximate, and the copy says "around": we asked for an age in
    whole years, not a birthday, so the true date is somewhere inside a
    twelve-month window. Naming an approximate year is far more use than "later",
    and overstating the precision would be the actual mistake.
    """
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
    """Turn a complete set of answers into one of the three outcomes.

    Order matters and is deliberate:

    * Citizenship first. It is the only firm refusal in the source, and telling a
      non-citizen child "come back when you are 5" would be a kinder sentence
      that wastes three years.
    * Then the two age outcomes, which are the ones with something concrete to
      offer.
    * Then everything unresolved, collected together.
    * Likely eligible is what is left, and only what is left.
    """
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

    # ASP-030 vs ASP-043/ASP-242. Outside the band on any ordinary birthday, but
    # the cohort clause is date-based and we asked for a range, so the copy
    # surfaces the clause and offers the mentor route rather than closing it.
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

    # Audit finding B. ASP-032 is firm, ASP-133/ASP-243 allow arrangements, and
    # neither addresses a NEW applicant already abroad.
    residence = answers.get("residence")
    if residence in ("abroad", "unsure"):
        unresolved.append("residence")

    # Audit finding C. ASP-033 is firm but silent on a child who has not started
    # school yet, or a school leaver still inside the age band.
    school = answers.get("school")
    if school in ("not_in_school", "unsure"):
        unresolved.append("school")

    # `registrant` is deliberately absent from every branch above. It shapes the
    # checklist and the steps (ASP-049, ASP-050, ASP-295) and has never been a
    # criterion; "I am not sure yet" must not cost anyone a verdict.

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
# `documents_for` always emits these immediately after what they substitute for.
ALTERNATIVES = frozenset({"passport"})


def documents_for(answers: dict[str, str]) -> tuple[str, ...]:
    """Which documents apply, in reading order.

    Personalised from the answers rather than printed whole: a family whose
    child was born in the Federation should not be handed a citizenship-by-
    descent certificate to find, and vice versa. Somebody who is not sure gets
    both, because that is the honest answer and the flow already told them to
    ask.
    """
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

    # ASP-248. Only where an adult is actually completing the form. "Not sure
    # yet" gets it too: an unnecessary line on a checklist costs nothing, a
    # missing one costs a trip.
    if answers.get("registrant") in ("guardian", "unsure", None):
        documents.append("guardian_id")

    # ASP-251, and the weakest item in the source. Always last, always hedged.
    documents.append("proof_of_address")
    return tuple(documents)


def steps_for(answers: dict[str, str]) -> tuple[str, ...]:
    """The walkthrough, routed by island.

    The only branch: ASP-299/ASP-300 name a daily walk-in centre in Basseterre
    and the knowledge base names no equivalent on Nevis, so sending someone on
    Nevis to Cayon Street would be inventing a service. They get the school and
    event route the source does carry, and are told plainly that no permanent
    centre outside Basseterre is on record.
    """
    in_person = (
        "in_person_kitts"
        if answers.get("residence") == "st_kitts"
        else "in_person_events"
    )
    return ("portal", "who_fills", "documents", in_person, "after", "confirm")
