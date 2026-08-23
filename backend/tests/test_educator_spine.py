"""The Educator Spine, against the corpus and the code that has to hold it up.

`app/prompting/spine/aspire_educator.yaml` is authored here rather than
vendored from the client, which makes it easier to edit and therefore easier to
let drift. These tests are what stop the drift being silent.

Three kinds of claim get checked:

  * **Structural** -- the band caps and persona key restate values declared in
    `app/safety/vocab.py` and `app/graph/nodes/safety_out.py`. A cap edited in
    one place and not the other is caught here, the same way
    `test_voice_spine.py` catches it for the voice spine.

  * **Measured** -- the quadrant row counts are a snapshot of the corpus taken
    on 23 August 2026. They are allowed to grow and not to shrink: a row
    deleted out from under the document turns the finding into a fiction.

  * **Negative** -- the two subjects pinned at provenance rung P4 are pinned
    there because ASPIRE has published nothing on them. If somebody writes a
    safeguarding answer, that pin is a lie and this file says so. This is the
    test that matters most, because inventing child-protection policy for a
    government programme is the worst output this system could produce.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest
import yaml

from app.graph.nodes.safety_out import WORD_CAPS

ROOT = Path(__file__).resolve().parents[1]
SPINE_FILE = ROOT / "app/prompting/spine/aspire_educator.yaml"
CORPUS = ROOT / "data" / "knowledge_base.csv"


@pytest.fixture(scope="module")
def spine() -> dict:
    return yaml.safe_load(SPINE_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def corpus() -> list[dict]:
    with CORPUS.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _teacher_rows(corpus: list[dict]) -> list[dict]:
    return [r for r in corpus if r["audience"] == "teacher"]


def _blob(row: dict) -> str:
    return " ".join(
        (row["question"], row["answer"], row["category"], row["subcategory"])
    ).lower()


# ── structural: the spine restates values the code owns ──────────────────────


class TestTheBandLadderMatchesTheEnforcedCaps:
    """Over the cap a reply is CUT. A spine that names the wrong number tells a
    teacher their classroom script has room it does not have.
    """

    def test_every_band_carries_the_cap_the_code_enforces(self, spine: dict):
        for entry in spine["band_ladder"]:
            band = entry["band"]
            if band == "T":  # the educator tier is the adult band, uncapped
                assert entry["word_cap"] is None
                continue
            assert entry["word_cap"] == WORD_CAPS[band], (
                f"spine says {band} is capped at {entry['word_cap']}, "
                f"code enforces {WORD_CAPS[band]}"
            )

    def test_the_ladder_covers_five_to_eighteen_and_the_tier_above(self, spine: dict):
        assert [e["band"] for e in spine["band_ladder"]] == [
            "5-8",
            "9-12",
            "13-15",
            "16-18",
            "T",
        ]

    def test_the_persona_key_is_the_key_and_not_the_label(self, spine: dict):
        """`nova` is the identifier. `Azuri` is the display name. Renaming a key
        is a migration; the spine must not quietly start using the label.
        """
        assert spine["meta"]["persona_key"] == "nova"


# ── structural: the local stage names ────────────────────────────────────────


class TestTheStageNamesAreLocal:
    """A teacher here has Kindergarten, Grade 4 and Form 2. Not 9th grade."""

    def test_the_official_divisions_are_named(self, spine: dict):
        stages = " ".join(e["stage"] for e in spine["band_ladder"]).lower()
        for division in ("kindergarten", "grade 1", "grade 6", "form 1", "form 5"):
            assert division in stages

    def test_no_american_stage_name_reaches_a_reader(self, corpus: list[dict]):
        """The banned list is not decoration: these must be absent from the
        corpus, not merely absent from the spine's own prose.
        """
        banned = re.compile(
            r"\b(elementary school|middle school|[0-9]+th grade|freshman|sophomore)\b",
            re.IGNORECASE,
        )
        offenders = [r["id"] for r in corpus if banned.search(r["question"] + r["answer"])]
        assert not offenders, f"American stage naming in: {offenders}"

    def test_the_us_k_2_shorthand_is_not_used(self, corpus: list[dict]):
        """`K-2` is US notation. The local name for that division is the Infant
        Department, and the corpus says so.
        """
        offenders = [
            r["id"] for r in corpus if re.search(r"\bK-2\b", r["question"] + r["answer"])
        ]
        assert not offenders, f"US 'K-2' shorthand still in: {offenders}"


# ── measured: the quadrant counts are a snapshot that may grow, not shrink ───


class TestTheQuadrantCountsStillHold:
    SUBJECT_PROGRAMME = re.compile(
        r"aspire programme|aspire account|ec\$500|seed|eligib|enrol|regist|"
        r"savings account|invest|council|task force|national bank|completion|"
        r"withdraw|aspire act",
        re.IGNORECASE,
    )

    def test_the_lesson_quadrant_has_not_been_emptied(self, spine: dict, corpus):
        """T2 is the quadrant that was already well served. The spine's finding
        -- that it dwarfed the others -- depends on it still being there.
        """
        claimed = spine["quadrants"]["T2"]["rows_at_audit"]
        actual = len(_teacher_rows(corpus))
        assert actual >= claimed, (
            f"spine measured {claimed} rows in T2 against a corpus that now "
            f"holds only {actual} teacher rows in total"
        )

    def test_the_programme_quadrants_have_been_filled(self, spine: dict, corpus):
        """T1 and E1 were 1 row and 5. The spine exists to correct that, so the
        corpus must now hold materially more than it measured.
        """
        rows = [r for r in _teacher_rows(corpus) if self.SUBJECT_PROGRAMME.search(_blob(r))]
        floor = spine["quadrants"]["T1"]["rows_at_audit"] + spine["quadrants"]["E1"][
            "rows_at_audit"
        ]
        assert len(rows) > floor, (
            f"only {len(rows)} teacher rows touch the programme; the spine was "
            f"written to raise this above {floor}"
        )


# ── negative: what is pinned at P4 must still be absent ──────────────────────


class TestWhatIsPinnedAtP4IsStillUnpublished:
    """The hardest floor in the document.

    Safeguarding and data-protection sit at P4 because ASPIRE has published
    neither -- confirmed against aspire.gov.kn, whose sections are Welcome,
    About, Financial Education, Eligibility Criteria, Application Process, FAQs
    and Contact Us. If a row ever appears that answers one of these
    substantively, either ASPIRE published something and the pin should be
    lifted deliberately, or somebody invented policy. Both need a human.
    """

    ANSWERS_SUBSTANTIVELY = re.compile(
        r"our safeguarding policy is|the safeguarding policy requires|"
        r"aspire's (child[- ]protection|safeguarding) policy (is|states|requires)|"
        r"data is retained for|the retention period is|aspire's privacy policy (is|states)",
        re.IGNORECASE,
    )

    def test_the_pinned_subjects_are_declared(self, spine: dict):
        pinned = {p["subject"] for p in spine["provenance_ladder"]["pinned_at_P4"]}
        assert pinned == {
            "child safeguarding policy",
            "participant data handling and consent",
        }

    def test_no_row_invents_a_safeguarding_or_privacy_policy(self, corpus: list[dict]):
        offenders = [r["id"] for r in corpus if self.ANSWERS_SUBSTANTIVELY.search(r["answer"])]
        assert not offenders, (
            "these rows answer a P4-pinned subject substantively, which means "
            f"either ASPIRE published it or it was invented: {offenders}"
        )

    def test_the_rows_that_do_exist_say_it_is_not_published(self, corpus: list[dict]):
        """One row each, and each one routes rather than answers."""
        by_id = {r["id"]: r for r in corpus}
        for row_id in ("ASP-384", "ASP-385"):
            answer = by_id[row_id]["answer"].lower()
            assert "not published" in answer, f"{row_id} no longer says it is unpublished"
            assert "aspire team" in answer, f"{row_id} no longer routes to a person"


# ── the CSEC floor ───────────────────────────────────────────────────────────


class TestNoRowClaimsCsecAlignment:
    """ASPIRE is not a scheme of work and is not aligned to CSEC. Telling a
    department otherwise is the claim that would cost a school the most.
    """

    CLAIMS_ALIGNMENT = re.compile(
        r"(is|are|fully|closely) aligned (to|with) (the )?(csec|cxc)|"
        r"csec[- ]aligned|meets the csec syllabus",
        re.IGNORECASE,
    )

    def test_no_alignment_claim_anywhere_in_the_corpus(self, corpus: list[dict]):
        offenders = [
            r["id"]
            for r in corpus
            if self.CLAIMS_ALIGNMENT.search(r["answer"])
            and "not aligned" not in r["answer"].lower()
        ]
        assert not offenders, f"CSEC alignment claimed in: {offenders}"


# ── the invariants are a list of rules, not prose ────────────────────────────


class TestTheInvariantsAreUsable:
    def test_every_invariant_has_an_id_and_a_rule(self, spine: dict):
        for entry in spine["invariants"]:
            assert entry["id"] and entry["rule"]

    def test_the_provenance_ladder_is_complete(self, spine: dict):
        ladder = spine["provenance_ladder"]
        for rung in ("P0", "P1", "P2", "P3", "P4"):
            assert ladder[rung]["has"] and ladder[rung]["opens"]

    def test_every_reader_signal_is_lowercase_for_matching(self, spine: dict):
        """The signals are matched against what a reader types."""
        for reader in ("teacher", "educator"):
            for signal in spine["readers"][reader]["signals"]:
                assert signal == signal.lower()
