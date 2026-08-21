"""Every FAQ on aspire.gov.kn, and whether this corpus can answer it.

Dr Marcus L Natta, 18 August, twice: "We also, on the website, put about 24 or so
frequently asked questions, which I am not sure I have seen the bot answer. I
would like you to ask it one of those questions, and I want to compare the answer
from the bot to what is on the website."

He will run that test himself. This runs it first.

    python3 tools/check_website_faqs.py

WHAT IT IS AND IS NOT
    It is a LEXICAL check: for each published FAQ it finds the closest question
    in the corpus and scores the similarity. That catches the failure that
    actually happened -- a question with no row phrased anywhere near it, so
    retrieval lands on something adjacent and answers a different question.

    It is NOT a retrieval test. It does not embed anything and it does not run
    the model. A row scoring 1.00 here can still lose to a better-scoring
    neighbour at serving time. Treat a pass as "there is something to find" and
    then ask the live bot the ones you care about.

    The FAQ list is pinned below rather than scraped, so this runs offline and in
    CI. If the site changes, update the list -- and notice that you had to.
"""

from __future__ import annotations

import csv
import difflib
import re
import sys
from pathlib import Path

KB = Path(__file__).resolve().parents[1] / "data" / "knowledge_base.csv"

#: The 22 questions published at aspire.gov.kn/#faqs, read 20 August 2026.
PUBLISHED: tuple[str, ...] = (
    "What is the ASPIRE Programme?",
    "Who is eligible to join the ASPIRE Programme?",
    "What evidence of citizenship do I need to provide?",
    "When will participants be enrolled?",
    "At what age can I register for my own account?",
    "Can I deposit additional funds into the ASPIRE savings account?",
    "Can I withdraw funds from my ASPIRE savings account?",
    "Will the savings account earn interest?",
    "What happens if an ASPIRE participant passes away or becomes incapacitated "
    "before completing the programme?",
    "How are the funds in the savings account protected?",
    "What kind of investments are made through the ASPIRE Programme?",
    "Can the participant choose the investments?",
    "How are dividends from investments handled?",
    "Can I withdraw my investment before completing the programme?",
    "How will I know the value of my Aspire savings and investments?",
    "What topics are covered in the financial education curriculum?",
    "How is the financial education delivered?",
    "Are there any assessments or exams in the financial education component?",
    "What happens when an ASPIRE participant completes the programme?",
    "What if I move abroad?",
    "Can parents/guardians monitor the ASPIRE account?",
    "What should I do if I have more questions about the ASPIRE Programme?",
)

#: Above this, a row is phrased closely enough that retrieval will find it.
GOOD = 0.80

#: Below this, nothing in the corpus is even about the same subject.
POOR = 0.62


def normalise(text: str) -> str:
    return re.sub(r"[^a-z ]", " ", text.lower()).strip()


def main() -> int:
    rows = list(csv.DictReader(KB.open(encoding="utf-8")))
    corpus = [(row["id"], row["question"]) for row in rows]

    weak: list[str] = []
    for question in PUBLISHED:
        target = normalise(question)
        best_id, best_q, best = "", "", 0.0
        for row_id, candidate in corpus:
            score = difflib.SequenceMatcher(None, target, normalise(candidate)).ratio()
            if score > best:
                best_id, best_q, best = row_id, candidate, score

        mark = "ok  " if best >= GOOD else ("near" if best >= POOR else "MISS")
        if best < POOR:
            weak.append(question)
        print(f"{mark} {best:.2f}  {question[:58]:60} -> [{best_id}] {best_q[:44]}")

    strong = sum(1 for q in PUBLISHED if q not in weak)
    print(f"\n{strong}/{len(PUBLISHED)} published FAQs have a row about the same subject.")

    if weak:
        print("\nNothing in the corpus is about these at all:")
        for question in weak:
            print(f"  - {question}")
        return 1

    print("\nEvery published FAQ has something to find. Now ask the live bot the")
    print("four you would least like to be wrong about, and compare word for word.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
