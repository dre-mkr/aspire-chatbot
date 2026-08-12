"""The copy: complete in three languages, and never claiming a decision."""

from __future__ import annotations

import pytest

from app.eligibility import content as copy
from app.eligibility.engine import EligibilityEngine
from app.eligibility.models import Language
from app.eligibility.rules import OPTIONS
from app.eligibility.schemas import LabelsOut

LANGUAGES = list(Language)


# --- completeness ----------------------------------------------------------


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_question_and_option_has_copy(language: Language):
    for question_id, options in OPTIONS.items():
        strings = copy.QUESTIONS[question_id][language]
        assert strings["text"].strip()
        for value in options:
            assert strings[value].strip(), f"{question_id}.{value} missing in {language}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_document_has_copy(language: Language):
    for document_id, by_language in copy.DOCUMENTS.items():
        strings = by_language[language]
        for field in ("title", "detail", "where"):
            assert strings[field].strip(), f"{document_id}.{field} missing in {language}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_step_has_copy(language: Language):
    for step_id, by_language in copy.STEPS.items():
        strings = by_language[language]
        assert strings["title"].strip()
        assert strings["detail"].strip()


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_result_has_copy(language: Language):
    for key, by_language in copy.RESULTS.items():
        strings = by_language[language]
        assert str(strings["headline"]).strip()
        assert strings["body"], f"{key} has no body in {language}"


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_chrome_is_complete_and_matches_the_schema(language: Language):
    """The labels are served, so a missing one is a 500 rather than a blank button."""
    labels = LabelsOut(**copy.UI[language])
    for value in labels.model_dump().values():
        assert value.strip()


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_mentor_question_and_unresolved_label_is_translated(language: Language):
    for by_language in copy.MENTOR_QUESTIONS.values():
        assert by_language[language].strip()
    for by_language in copy.UNRESOLVED_LABELS.values():
        assert by_language[language].strip()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_disclaimer_and_notices_are_translated(language: Language):
    assert copy.DISCLAIMER[language].strip()
    for by_language in copy.NOTICES.values():
        assert by_language[language].strip()
    assert len(copy.contacts(language)) == 3


def test_the_language_enum_matches_the_games_one():
    """Re-declared for independence, checked so they cannot drift apart."""
    from app.games.models import Language as GameLanguage

    assert {item.value for item in Language} == {item.value for item in GameLanguage}


# --- no approval language --------------------------------------------------

# Phrases that read as a decision on an application, in all three languages.
FORBIDDEN = (
    "you are approved",
    "you're approved",
    "approved",
    "you are accepted",
    "you're accepted",
    "accepted into",
    "you are eligible",
    "you're eligible",
    "you qualify",
    "guaranteed",
    "aprobado",
    "aprobada",
    "aceptado",
    "aceptada",
    "garantizado",
    "cumples los requisitos",
    "approuvé",
    "approuvée",
    "accepté",
    "acceptée",
    "garanti",
    "tu es admissible",
)


def _all_result_text(language: Language) -> str:
    parts = []
    for strings in copy.RESULTS.values():
        by_language = strings[language]
        parts.append(str(by_language["headline"]))
        parts.extend(str(line) for line in by_language["body"])  # type: ignore[union-attr]
        for optional in ("year", "meanwhile"):
            if optional in by_language:
                parts.append(str(by_language[optional]))
    parts.append(copy.DISCLAIMER[language])
    parts.append(copy.UI[language]["banner"])
    parts.append(copy.UI[language]["subtitle"])
    return " ".join(parts).lower()


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_result_ever_reads_as_a_decision(language: Language):
    text = _all_result_text(language)
    for phrase in FORBIDDEN:
        assert phrase not in text, f"{phrase!r} reads as a decision ({language})"


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_strongest_headline_is_hedged(language: Language):
    """The positive outcome is the one that must not overclaim."""
    headline = str(copy.RESULTS["likely_eligible"][language]["headline"]).lower()
    hedges = {
        Language.EN: ("likely", "based on what"),
        Language.ES: ("probable", "según lo que"),
        Language.FR: ("probable", "d'après ce que"),
    }[language]
    assert any(hedge in headline for hedge in hedges)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_pre_check_disclaimer_is_visible_chrome_not_fine_print(language: Language):
    """The banner rides on the card the whole way through, so it must say so."""
    banner = copy.UI[language]["banner"].lower()
    marker = {
        Language.EN: "pre-check",
        Language.ES: "consulta previa",
        Language.FR: "vérification préalable",
    }[language]
    assert marker in banner


# --- the hedges survive translation ----------------------------------------


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_hedged_documents_stay_hedged_in_every_language(language: Language):
    """Three of the five documents are hedged by the SOURCE itself."""
    for document_id in ("passport", "guardian_id", "proof_of_address"):
        strings = copy.DOCUMENTS[document_id][language]
        assert strings.get("caveat", "").strip(), (
            f"{document_id} lost its caveat in {language}"
        )


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_document_claims_a_civil_registry_the_source_does_not_name(
    language: Language,
):
    """The knowledge base says nothing about where to obtain a birth certificate."""
    for document_id in ("birth_certificate", "descent_certificate"):
        where = copy.DOCUMENTS[document_id][language]["where"].lower()
        for invented in ("civil registry", "registrar", "high court", "registro civil"):
            assert invented not in where


@pytest.mark.parametrize("language", LANGUAGES)
def test_only_basseterre_is_named_as_a_walk_in_centre(language: Language):
    """ASP-299 names one, and the knowledge base names no other."""
    events = copy.STEPS["in_person_events"][language]["detail"]
    assert "Cayon" not in events
    assert "Basseterre" in events  # named only to say there is none beyond it


# --- the contact details are the source's own ------------------------------


def test_contact_details_are_never_invented():
    """ASP-208, ASP-209, ASP-328. Nothing here may drift from the source."""
    assert copy.EMAIL == "aspire@gov.kn"
    assert copy.PHONES == ("+1 (869) 667-5566", "+1 (869) 762-1947")
    assert copy.HOTLINE == "465-2588"
    for language in LANGUAGES:
        joined = " ".join(copy.contacts(language))
        assert copy.EMAIL in joined
        assert copy.HOTLINE in joined


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_whole_flow_renders_end_to_end_in_every_language(language: Language):
    """Walks every question and both plan shapes so a missing key fails here, not in the UI."""
    answers = {
        "age": "under5",
        "age_exact": "3",
        "citizenship": "unsure",
        "residence": "nevis",
        "school": "home_school",
        "registrant": "unsure",
    }
    engine = EligibilityEngine()
    engine.quit("lang-test")
    snapshot = engine.start("lang-test", language)
    while snapshot.question is not None:
        assert snapshot.question.text.strip()
        for option in snapshot.question.options:
            assert option.label.strip()
        snapshot = engine.answer("lang-test", answers[snapshot.question.id])

    result = snapshot.result
    assert result is not None and result.headline.strip()
    for item in result.checklist:
        assert item.title.strip() and item.detail.strip() and item.where.strip()
    for step in result.steps:
        assert step.title.strip() and step.detail.strip()
