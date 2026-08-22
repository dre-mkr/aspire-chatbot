"""The ladder has to hold in every language the product answers in.

WHAT WAS WRONG
    `check()` runs on the finished reply in `safety_out`, whatever language it is
    in, and `_BAN` held English variants only. So the gate was a NO-OP the moment
    the model answered in Spanish or French:

        EN  "...pays you interest every year, a percent of your money."  -> stripped
        FR  "...verse un intérêt chaque année, un pourcentage..."         -> untouched
        ES  "...paga un interés cada año, un porcentaje..."               -> untouched

    Same sentence, same five-year-old, three different outcomes. The word caps
    were never affected -- they count words in any language. The ladder was, and
    it is the half that exists to protect a child.

    This had been live since Spanish shipped. French only inherited it.

WHAT THIS FILE PINS
    That the three shipped locales are held to the same ladder, that the term
    KEYS stay English (they are identifiers, not copy), and that ordinary
    band-appropriate sentences in Spanish and French do not trip it -- a gate
    that fires on safe text gets switched off by the next person who trips over
    it.
"""

from __future__ import annotations

import pytest

from app.domain import Language
from app.safety import vocab

#: One banned idea per band, said naturally in each locale.
#:
#: Not translations of each other word for word -- the point is that a native
#: sentence a model would actually produce gets caught, not that a dictionary
#: lookup succeeds.
SAYS_IT_ANYWAY: list[tuple[str, str, str, str]] = [
    ("5-8", "interest", "en", "The bank pays you interest every year."),
    ("5-8", "interest", "es", "El banco te paga un interés cada año."),
    ("5-8", "interest", "fr", "La banque te verse un intérêt chaque année."),
    ("5-8", "percent", "en", "You get two percent of your money."),
    ("5-8", "percent", "es", "Recibes un porcentaje de tu dinero."),
    ("5-8", "percent", "fr", "Tu reçois un pourcentage de ton argent."),
    ("5-8", "investment", "es", "La otra mitad es una inversión."),
    ("5-8", "investment", "fr", "L'autre moitié est un investissement."),
    ("5-8", "loan", "es", "Es como un préstamo del banco."),
    ("5-8", "loan", "fr", "C'est comme un prêt de la banque."),
    ("9-12", "compound", "es", "Se llama interés compuesto."),
    ("9-12", "compound", "fr", "On appelle cela la capitalisation."),
    ("9-12", "inflation", "es", "La inflación se come tus ahorros."),
    ("9-12", "inflation", "fr", "L'inflation ronge ton épargne."),
    ("13-15", "leverage", "es", "Eso se hace con apalancamiento."),
    ("13-15", "leverage", "fr", "Cela se fait avec un effet de levier."),
]

#: The general list applies at every band, adult included, in every locale.
NEVER_ANYWHERE: list[tuple[str, str, str]] = [
    ("guaranteed return", "en", "There is no guaranteed return on this."),
    ("guaranteed return", "es", "No existe un rendimiento garantizado."),
    ("guaranteed return", "fr", "Il n'existe aucun rendement garanti."),
    ("risk-free", "es", "No es una inversión sin riesgo."),
    ("risk-free", "fr", "Ce n'est pas un placement sans risque."),
    ("crypto", "es", "No hablamos de criptomonedas aquí."),
    ("crypto", "fr", "On ne parle pas de cryptomonnaie ici."),
    ("get rich", "es", "Esto no es para hacerse rico."),
    ("get rich", "fr", "Ce n'est pas pour devenir riche."),
]

#: Band-appropriate sentences that must NOT trip the gate.
#:
#: The more important half of the file. A gate that fires on safe text is a gate
#: somebody switches off.
SAFE: list[tuple[str, str, str]] = [
    ("5-8", "es", "Tu dinero está seguro en el banco y crece solo."),
    ("5-8", "fr", "Ton argent est en sécurité à la banque et il grandit tout seul."),
    ("5-8", "es", "Guardar es dejar el dinero quieto para después."),
    ("5-8", "fr", "Épargner, c'est laisser l'argent tranquille pour plus tard."),
    ("9-12", "es", "El banco te añade dinero dos veces al año."),
    ("9-12", "fr", "La banque ajoute de l'argent deux fois par an."),
    ("13-15", "es", "El interés compuesto se puede nombrar en esta banda."),
    ("13-15", "fr", "Les intérêts composés peuvent être nommés à cette tranche."),
    ("adult", "es", "La mitad invertida no está publicada."),
    ("adult", "fr", "La moitié investie n'est pas publiée."),
]


class TestTheLadderHoldsInEveryShippedLocale:
    @pytest.mark.parametrize(
        ("band", "term", "locale", "text"),
        SAYS_IT_ANYWAY,
        ids=lambda v: str(v),
    )
    def test_a_banned_idea_is_caught_however_it_is_said(self, band, term, locale, text):
        caught = {v.term for v in vocab.check(text, band)}
        assert term in caught, (
            f"{locale}: {text!r} passed the {band} gate. The reply reaches the "
            f"reader with the word intact, and the English sentence saying the "
            f"same thing would have been stripped."
        )

    @pytest.mark.parametrize(("term", "locale", "text"), NEVER_ANYWHERE)
    @pytest.mark.parametrize("band", ["5-8", "9-12", "13-15", "16-18", "adult"])
    def test_the_general_list_applies_at_every_band_in_every_locale(
        self, band, term, locale, text
    ):
        assert term in {v.term for v in vocab.check(text, band)}


class TestItDoesNotFireOnSafeText:
    @pytest.mark.parametrize(("band", "locale", "text"), SAFE)
    def test_band_appropriate_text_passes(self, band, locale, text):
        found = vocab.check(text, band)
        assert not found, (
            f"{locale}: {text!r} is fine at {band} and was flagged for "
            f"{[v.term for v in found]}. False positives are how a gate gets "
            f"switched off."
        )


class TestTheKeysStayEnglish:
    """The variants are multilingual. The term key is an identifier."""

    def test_every_violation_reports_an_english_term(self):
        """`explain()` puts the term into a reprompt and the tests assert on it.

        A localised key would mean the reprompt sent to the model, the message a
        developer reads and the word the persona card lists all drift apart by
        locale.
        """
        found = vocab.check("La banque te verse un intérêt.", "5-8")
        assert [v.term for v in found] == ["interest"]
        assert found[0].matched == "intérêt", "the MATCH is what was actually said"

    def test_the_shipped_locales_are_the_ones_covered(self):
        """If a fourth locale is added, this test is the reminder.

        Adding a language means adding variants to `_BAN` and `_GENERAL_BAN`, and
        nowhere else -- but nothing forces it, so this pins the set that has been
        done to the set the product ships.
        """
        assert {lang.value for lang in Language} == {"en", "es", "fr"}, (
            "a locale was added to Language. Add its variants to vocab._BAN and "
            "vocab._GENERAL_BAN, then widen this test."
        )
