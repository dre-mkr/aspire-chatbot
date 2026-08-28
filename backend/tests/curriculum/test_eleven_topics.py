"""The eleven authored topics, and what a reader can be taught because of them.

`module_01_saving.yaml` teaches six concepts and every one of them is
savings-adjacent. The eleven topics are the rest of the curriculum, written
voice by voice and band by band with the vocabulary gates reasoned through in
the file itself. Without them the product can explain saving and nothing else,
and a reader asking about interest, credit, taxes or scams gets a corpus
lookup rather than a lesson.
"""

from __future__ import annotations

import pytest

from app.curriculum.topics import _VOICE_BAND, concept_rows, load_topics
from app.learning.concepts import TeachingConcept

ROWS = {row["id"]: row for row in concept_rows()}


def _concept(row: dict) -> TeachingConcept:
    payload = {f"body_{b.replace('-', '_')}": row["bodies"].get(b)
               for b in ("5-8", "9-12", "13-15", "16-18", "adult")}
    return TeachingConcept.from_row(
        {"id": row["id"], "slug": row["id"], "locale": "en", "title": row["title"],
         "domain": "money", "band_min": row["band_min"], "band_max": row["band_max"],
         "status": "approved", "check_bank": row["check_bank"], **payload}
    )


class TestAllElevenArrive:
    def test_the_file_has_eleven_topics(self):
        assert len(load_topics()) == 11

    def test_every_topic_becomes_a_concept(self):
        assert len(ROWS) == 11

    @pytest.mark.parametrize(
        "cid",
        ["budget", "interest", "ai_money", "credit_debt", "investing", "need",
         "save", "scams", "mobile_money", "taxes", "entrepreneurship"],
    )
    def test_the_concept_is_present_and_can_teach(self, cid):
        assert cid in ROWS, f"{cid} did not survive the import"
        concept = _concept(ROWS[cid])
        band = ROWS[cid]["band_max"]
        assert concept.teachable_at(band), f"{cid} cannot be taught at {band}"

    def test_the_ai_topic_was_renamed_to_the_reader(self):
        """It is about the reader's own money, not what banks do."""
        title = ROWS["ai_money"]["title"].lower()
        assert "help you" in title
        assert "banks" not in title

    def test_three_topics_enrich_rather_than_duplicate(self):
        """A second `saving` id would split one reader's mastery in two."""
        enriching = {r["id"] for r in concept_rows() if r["enriches_existing"]}
        assert enriching == {"budget", "save", "need"}


class TestTheBandsTheAuthorWroteFor:
    def test_every_authored_voice_maps_to_a_band(self):
        assert set(_VOICE_BAND) == {"skye", "kaleb", "z13", "z16", "imani"}
        assert set(_VOICE_BAND.values()) == {"5-8", "9-12", "13-15", "16-18", "adult"}

    def test_interest_reaches_the_youngest_readers(self):
        """The ban was overturned for lessons: a five-year-old may be told."""
        assert "5-8" in ROWS["interest"]["bodies"]
        assert _concept(ROWS["interest"]).teachable_at("5-8") is True

    def test_a_gated_topic_stays_gated_where_nothing_was_written(self):
        """Skye has no credit cell, so credit is not teachable at 5-8."""
        assert "5-8" not in ROWS["credit_debt"]["bodies"]
        assert _concept(ROWS["credit_debt"]).teachable_at("5-8") is False

    def test_scams_reaches_every_band(self):
        """The topic the file calls the highest real-world stakes of the eleven."""
        concept = _concept(ROWS["scams"])
        for band in ("5-8", "9-12", "13-15", "16-18", "adult"):
            assert concept.teachable_at(band), f"scams is not taught at {band}"


class TestNothingWasInvented:
    def test_the_body_is_the_authors_own_copy(self):
        topic = next(t for t in load_topics() if t["title"] == "What is Interest?")
        authored = (topic["voices"]["kaleb"]["copy"])[0].strip()
        assert authored in ROWS["interest"]["bodies"]["9-12"]

    def test_the_check_is_the_question_the_author_closed_with(self):
        for row in concept_rows():
            for check in row["check_bank"]:
                assert check["question"].endswith("?")

    def test_the_check_is_not_also_left_inside_the_body(self):
        """Teaching and asking in one breath leaves nothing waiting for a reply.

        A teaching line may still ASK something -- the AI topic closes its
        16-18 body on two questions the author wrote to be thought about, not
        answered. What must not happen is the check appearing twice: once as
        the last thing said and again as the thing being waited on.
        """
        for row in concept_rows():
            questions = {c["question"].strip() for c in row["check_bank"]}
            for band, body in row["bodies"].items():
                for question in questions:
                    assert question not in body, (
                        f"{row['id']} at {band} both says and asks {question!r}"
                    )
