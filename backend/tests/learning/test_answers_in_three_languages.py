"""A learner's answer is understood in all three shipped languages.

Two deterministic pieces sat under every graded answer and spoke only
English: the accept-list comparison could not see past an accent, and the
"I don't know" triage had no Spanish or French at all. Both are the kind of
gap the model pass papers over on a good day and turns into a wrong WRONG
on a bad one -- so both are pinned here, deterministically.
"""

from __future__ import annotations

from app.agents.learn.evaluate import Verdict, match_accept_list, triage
from app.learning.concepts import CheckItem


def item(accept, answer=""):
    return CheckItem(
        id="chk_es_1",
        band="9_12",
        type="free",
        question="¿Qué es ahorrar?",
        answer=answer,
        accept=tuple(accept),
        hints=("piensa en guardar",),
        explanation_on_correct="Eso es.",
        explanation_on_wrong="Ahorrar es guardar.",
    )


class TestAccentsDoNotFailAnAnswer:
    def test_an_unaccented_answer_matches_an_accented_term(self):
        assert match_accept_list(item(["educación financiera"]), "educacion financiera") is True

    def test_an_accented_answer_matches_an_unaccented_term(self):
        assert match_accept_list(item(["ahorrar dinero"]), "ahorrár dinero") is True

    def test_french_accents_fold_the_same_way(self):
        assert match_accept_list(item(["économiser"]), "economiser") is True

    def test_keyword_matching_survives_accents_in_any_order(self):
        assert match_accept_list(item(["depósito mínimo"]), "el minimo deposito") is True

    def test_a_wrong_short_answer_is_still_wrong(self):
        assert match_accept_list(item(["ahorrar"]), "gastar todo") is False


class TestDontKnowSpeaksThreeLanguages:
    def test_spanish(self):
        assert triage("no sé") is Verdict.DONT_KNOW
        assert triage("No lo sé.") is Verdict.DONT_KNOW
        assert triage("ni idea") is Verdict.DONT_KNOW

    def test_french(self):
        assert triage("je ne sais pas") is Verdict.DONT_KNOW
        assert triage("Je sais pas") is Verdict.DONT_KNOW
        assert triage("aucune idée") is Verdict.DONT_KNOW

    def test_english_is_unchanged(self):
        assert triage("i don't know") is Verdict.DONT_KNOW
        assert triage("dunno") is Verdict.DONT_KNOW

    def test_asking_for_the_answer_in_spanish_and_french(self):
        assert triage("dime la respuesta") is Verdict.ASKS_FOR_ANSWER
        assert triage("me rindo") is Verdict.ASKS_FOR_ANSWER
        assert triage("donne-moi la réponse") is Verdict.ASKS_FOR_ANSWER
        assert triage("j'abandonne") is Verdict.ASKS_FOR_ANSWER

    def test_a_real_attempt_is_not_triaged(self):
        assert triage("guardar dinero para después") is None
