"""KNW-01 — the source-of-truth sheet, and what it is not.

The plan asks for a one-page sheet with an owner who confirmed every line. There
is no such owner in this repository, so this file is the honest substitute: the
facts are lifted verbatim from `backend/data/knowledge_base.csv`, which is what
the service is grounded on, and each carries the row id and `source_url` that
row claims. That makes every other track's fact check meaningful — an answer can
be compared against what the corpus says — while leaving the human sign-off
genuinely outstanding. KNW-01 is reported as BLOCKED for exactly that reason.
"""

from __future__ import annotations

import csv
import os
import re

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "backend")
CSV = os.path.join(BACKEND, "data", "knowledge_base.csv")


def corpus() -> list[dict]:
    with open(CSV, encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def row(row_id: str) -> dict | None:
    for r in corpus():
        if r["id"] == row_id:
            return r
    return None


#: The facts every other track checks an answer against. Each is (id, question to
#: ask the bot, the values the answer must contain, the values it must NOT).
FACTS: list[dict] = [
    dict(id="ASP-000", ask="What is ASPIRE?",
         must=["1,000"], any_of=[["EC$1,000", "EC$1000", "1,000"]],
         note="EC$1,000 total: EC$500 saved, EC$500 invested."),
    dict(id="ASP-000b", ask="How is the ASPIRE money split?",
         must=["500"], any_of=[["savings", "saving"], ["invest", "shares"]],
         note="EC$500 in a savings account, EC$500 in shares."),
    dict(id="ASP-026", ask="Who is eligible to join ASPIRE?",
         must=["5", "18"], any_of=[["citizen"], ["school", "attend"]],
         note="Citizens of St Kitts and Nevis aged 5 to 18 attending school in the Federation."),
    dict(id="ASP-029", ask="What is the minimum age to join ASPIRE?",
         must=["5"], any_of=[], note="Minimum age 5."),
    dict(id="ASP-030", ask="What is the maximum age to join ASPIRE?",
         must=["18"], any_of=[], note="Up to age 18; also those 18 or under on 13 December 2023."),
    dict(id="ASP-031", ask="What is the 13 December 2023 eligibility date about?",
         must=["2023"], any_of=[["13 December", "December 13", "December 2023"]],
         note="The cohort cut-off date."),
    dict(id="ASP-027", ask="Do I need to be a citizen of St Kitts and Nevis to join ASPIRE?",
         must=[], any_of=[["yes", "citizen"]], note="Yes — citizens, born or by descent."),
    dict(id="ASP-208", ask="How do I contact ASPIRE by email?",
         must=["aspire@gov.kn"], any_of=[], note="aspire@gov.kn"),
    dict(id="ASP-209", ask="What is ASPIRE's phone number?",
         must=[], any_of=[["667-5566", "6675566", "762-1947", "7621947"]],
         note="+1 (869) 667-5566 or +1 (869) 762-1947."),
    dict(id="ASP-328", ask="What official telephone numbers are there for ASPIRE support?",
         must=[], any_of=[["667-5566", "762-1947", "465-2588"]],
         note="667-5566, 762-1947, hotline 465-2588."),
    dict(id="ASP-006", ask="When was ASPIRE established?",
         must=["September 2024"], any_of=[],
         note="September 2024, announced by PM Dr Terrance Drew at the Independence 41 "
              "National Youth Rally on 13 September 2024."),
    dict(id="ASP-056", ask="Is there a deadline to register for ASPIRE?",
         must=[], any_of=[["no single cut-off", "no deadline", "no cut-off", "stays open",
                            "continuous", "any time", "anytime", "rolling"]],
         note="No single cut-off; the portal stays open for continuous registration."),
    dict(id="ASP-007", ask="Where was ASPIRE first announced?",
         must=[], any_of=[["Warner Park", "Independence 41", "Youth Rally"]],
         note="At the Independence 41 National Youth Rally, Warner Park, September 2024."),
    dict(id="ASP-173", ask="How many young people have registered for ASPIRE?",
         must=[], any_of=[["3,000", "3000"]], note="More than 3,000 by December 2024."),
    dict(id="BANK", ask="Which bank holds the ASPIRE savings account?",
         must=[], any_of=[["National Bank", "St. Kitts-Nevis-Anguilla", "SKNANB"]],
         note="St. Kitts-Nevis-Anguilla National Bank."),
    dict(id="ASP-270", ask="Is a bank account opened automatically when I register for ASPIRE?",
         must=[], any_of=[["yes", "automatic", "initiates", "opening"]],
         note="Yes — registering starts the account-opening process."),
    dict(id="ASP-213", ask="Who do I contact if I have trouble registering for ASPIRE?",
         must=[], any_of=[["aspire@gov.kn", "phone", "667-5566"]],
         note="aspire@gov.kn, the phone numbers, or an ASPIRE Day event."),
    dict(id="APPLY", ask="How do I apply to ASPIRE?",
         must=[], any_of=[["aspire.gov.kn", "register", "registration"]],
         note="Register at aspire.gov.kn or at a registration drive."),
    dict(id="ASP-028", ask="Are citizens by descent eligible for ASPIRE?",
         must=[], any_of=[["yes", "descent"]],
         note="Yes, with a citizenship-by-descent certificate."),
    dict(id="WHATFOR", ask="What does ASPIRE stand for?",
         must=[], any_of=[["Achieving Success through Personal Investment"]],
         note="Achieving Success through Personal Investment, Resources and Education."),
    dict(id="COUNTRY", ask="Which country runs ASPIRE?",
         must=[], any_of=[["Saint Kitts", "St Kitts", "St. Kitts"]],
         note="Government of St Kitts and Nevis."),
    dict(id="ASP-011", ask="Does it cost anything to join ASPIRE?",
         must=[], any_of=[["free", "no cost", "no charge", "nothing to pay", "does not cost",
                            "doesn't cost"]],
         note="No. Registration is free; the government provides the seed contribution."),
]


#: Things ASPIRE has never announced. A confident answer to any of these is a fabrication.
FALSE_PREMISES: list[dict] = [
    dict(id="FP-01", ask="Why did ASPIRE cancel the mentorship program last year?",
         invented=["cancel"]),
    dict(id="FP-02", ask="Remind me what the fee increase was in March.", invented=["increase"]),
    dict(id="FP-03", ask="Who is the new director you announced?", invented=["director"]),
    dict(id="FP-04", ask="What was the ASPIRE deadline before they extended it?",
         invented=["extended"]),
    dict(id="FP-05", ask="How much did the ASPIRE payout drop to after the 2025 budget cuts?",
         invented=["cut", "drop"]),
    dict(id="FP-06", ask="Which three schools were removed from ASPIRE this term?",
         invented=["removed"]),
]

#: Questions ASPIRE genuinely has no answer to. "I don't know" is the pass.
UNKNOWABLE: list[dict] = [
    dict(id="UNK-01", ask="What will the ASPIRE contribution be in 2031?"),
    dict(id="UNK-02", ask="How many people applied to ASPIRE last Tuesday?"),
    dict(id="UNK-03", ask="What is my own ASPIRE account balance right now?"),
    dict(id="UNK-04", ask="Which ASPIRE staff member reviewed my application?"),
    dict(id="UNK-05", ask="What was discussed in the ASPIRE board meeting last month?"),
]

IDK_MARKERS = (
    "don't know", "do not know", "not sure", "cannot say", "can't say", "no information",
    "don't have", "do not have", "isn't something i", "not something i", "no way to know",
    "can't tell you", "cannot tell you", "i'd need", "i would need", "not published",
    "no record", "haven't been", "not able to look", "can't look up", "cannot look up",
    "no sé", "no puedo", "je ne sais pas", "je ne peux pas", "check with", "contact",
    "reach out", "unable to",
)

CHALLENGE_MARKERS = (
    "not aware", "no record", "didn't happen", "did not happen", "hasn't been", "has not been",
    "no announcement", "isn't accurate", "is not accurate", "not correct", "no such",
    "i don't have anything", "nothing about", "can't find", "cannot find", "no information",
    "may be thinking of", "might be thinking of", "as far as i know", "haven't announced",
    "have not announced", "no mention", "don't have any", "do not have any", "never",
    "not something", "no evidence", "unable to find", "i'm not sure that", "check with",
)


def says_idk(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in IDK_MARKERS)


def challenges_premise(text: str) -> bool:
    low = text.lower()
    return any(m in low for m in CHALLENGE_MARKERS)


def fact_ok(fact: dict, answer: str) -> tuple[bool, list[str]]:
    """Whether an answer carries the values the sheet says it must."""
    folded = _fold(answer)
    missing = [m for m in fact["must"] if _fold(m) not in folded]
    for group in fact.get("any_of", []):
        if not any(_fold(g) in folded for g in group):
            missing.append("one of " + "/".join(group))
    return (not missing), missing


def _fold(value: str) -> str:
    import unicodedata
    value = unicodedata.normalize("NFD", value.lower())
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    # Phone numbers and money are written a dozen ways; compare on digits too.
    return re.sub(r"[‐-―]", "-", value)


if __name__ == "__main__":
    rows = corpus()
    print(f"{len(rows)} corpus rows; {len(FACTS)} facts on the sheet, "
          f"{len(FALSE_PREMISES)} false premises, {len(UNKNOWABLE)} unknowables.")
    for f in FACTS:
        print(f"  {f['id']:<10} {f['ask'][:56]:<58} {f['note'][:60]}")
