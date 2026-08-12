"""The slot loop, the schema's authority, and the PII split."""

from __future__ import annotations

import os
from datetime import date

import pytest

os.environ.setdefault(
    "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
)

from langchain_core.messages import HumanMessage  # noqa: E402

from app.agents.register import graph as rg  # noqa: E402
from app.agents.register import schema as rs  # noqa: E402
from app.agents.register import store  # noqa: E402
from app.agents.register.nodes import doc_check, review, upload  # noqa: E402
from app.graph.state import initial_state  # noqa: E402
from app.safety import pii  # noqa: E402


def state_for(message: str = "", **overrides):
    state = initial_state(
        session_id="s-reg",
        user_id="u-reg",
        device_id="d",
        persona="aurora",
        age_band="adult",
        account_status="guardian",
    )
    state["messages"] = [HumanMessage(content=message)] if message else []
    state["active_agent"] = "register_agent"
    state.update(overrides)
    return state


async def answer(graph, state, text: str):
    state = dict(state)
    state["messages"] = list(state["messages"]) + [HumanMessage(content=text)]
    return await graph.ainvoke(state)


# ── the schema decides ───────────────────────────────────────────────────────


class TestTheSchemaIsTheSourceOfTruth:
    def test_the_walk_is_guardian_first_then_child(self):
        """Order comes from a tuple, not from the conversation."""
        paths = [slot.path for slot in rs.SLOTS]
        guardian = [index for index, path in enumerate(paths) if path.startswith("guardian.")]
        child = [index for index, path in enumerate(paths) if path.startswith("child.")]
        assert max(guardian) < min(child)

    def test_next_missing_walks_in_order_and_skips_optional(self):
        filled: dict = {}
        assert rs.next_missing(filled).path == "guardian.full_name"
        filled["guardian.full_name"] = "Rachel Providence"
        assert rs.next_missing(filled).path == "guardian.national_id"

    def test_an_optional_slot_is_still_asked_for(self):
        """`optional` decides whether it may be DECLINED, not whether it is asked."""
        filled = {slot.path: "x" for slot in rs.GUARDIAN_SLOTS if not slot.optional}
        assert rs.next_missing(filled).path == "guardian.email"

    def test_a_declined_slot_is_passed_over(self):
        """`barred` is how a skip is honoured, and it writes nothing to `filled`."""
        filled = {slot.path: "x" for slot in rs.GUARDIAN_SLOTS if not slot.optional}
        assert rs.next_missing(
            filled, barred=frozenset({"guardian.email"})
        ).path.startswith("child.")

    def test_every_slot_has_copy_in_every_locale(self):
        for slot in rs.SLOTS:
            for locale in ("en", "es", "fr"):
                assert slot.prompt.get(locale), f"{slot.path} has no {locale} prompt"
                assert slot.reask.get(locale), f"{slot.path} has no {locale} reask"

    def test_a_reask_names_the_format_and_gives_an_example(self):
        """"That didn't work" tells a parent nothing and they retry the same thing."""
        dob = rs.slot_for("guardian.date_of_birth")
        assert "day/month/year" in dob.reask["en"]
        assert "14/03/1985" in dob.reask["en"]

    def test_dates_are_read_day_first(self):
        """Month-first on 03/04/2015 is a different child's birthday, silently."""
        value, problem = rs.slot_for("child.date_of_birth").parse("03/04/2015")
        assert problem is None
        assert value == date(2015, 4, 3)

    @pytest.mark.parametrize(
        ("raw", "ok"),
        [("14/03/2015", True), ("2015-03-14", True), ("14-03-2015", True),
         ("March", False), ("", False), ("32/13/2015", False)],
    )
    def test_date_parsing(self, raw, ok):
        _value, problem = rs.slot_for("child.date_of_birth").parse(raw)
        assert (problem is None) is ok

    def test_a_parish_is_matched_loosely_but_from_a_closed_list(self):
        value, problem = rs.slot_for("guardian.parish").parse("Cayon")
        assert problem is None and value == "Saint Mary Cayon"
        _value, problem = rs.slot_for("guardian.parish").parse("Atlantis")
        assert problem is not None

    def test_a_guardian_must_be_an_adult(self):
        with pytest.raises(ValueError, match="18 or over"):
            rs.GuardianSection(
                full_name="A Person",
                national_id="A12345678",
                date_of_birth=date.today().replace(year=date.today().year - 16),
                relationship="mother",
                phone="8695550123",
                address_line1="12 Cayon Street",
                parish="Saint Mary Cayon",
            )

    def test_a_child_over_eighteen_is_refused(self):
        with pytest.raises(ValueError, match="up to 18"):
            rs.ChildSection(
                full_name="A Child",
                date_of_birth=date.today().replace(year=date.today().year - 19),
                sex="female",
            )


# ── PII ──────────────────────────────────────────────────────────────────────


class TestPIISplit:
    def test_the_sensitive_slots_are_the_ones_you_would_expect(self):
        assert rs.sensitive_paths() == frozenset(
            {
                "guardian.full_name",
                "guardian.national_id",
                "guardian.date_of_birth",
                "guardian.phone",
                "guardian.email",
                "guardian.address_line1",
                "child.full_name",
                "child.date_of_birth",
            }
        )

    def test_a_parish_is_not_sensitive(self):
        """It is a filter on the reviewer's queue, and it identifies nobody."""
        assert not rs.slot_for("guardian.parish").sensitive

    def test_display_values_are_masked(self):
        slot = rs.slot_for("guardian.national_id")
        assert rs.display_value(slot, "A12345678") == "•••••5678"

    def test_an_email_is_masked_but_recognisable(self):
        """A parent checking their own address needs to recognise it, not read it."""
        slot = rs.slot_for("guardian.email")
        assert rs.display_value(slot, "rachel@example.com") == "ra••••@example.com"

    def test_a_non_sensitive_value_is_shown_whole(self):
        assert rs.display_value(rs.slot_for("guardian.parish"), "Saint Mary Cayon") == (
            "Saint Mary Cayon"
        )

    def test_a_completed_application_leaves_nothing_in_a_summary(self):
        """The acceptance criterion, stated directly."""
        collected = {
            "guardian.full_name": "Rachel Providence",
            "guardian.national_id": "A12345678",
            "guardian.date_of_birth": "14/03/1985",
            "guardian.phone": "869-555-0123",
            "guardian.email": "rachel@example.com",
            "guardian.address_line1": "12 Cayon Street",
            "child.full_name": "Amara Providence",
            "child.date_of_birth": "14/03/2015",
        }
        transcript = " ".join(collected.values())
        summary = pii.redact_for_summary(transcript)

        for value in ("A12345678", "14/03/1985", "869-555-0123",
                      "rachel@example.com", "12 Cayon Street", "14/03/2015"):
            assert value not in summary, value
        assert pii.kinds_in(summary) == []


# ── the loop ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestTheSlotLoop:
    async def test_it_opens_with_the_first_guardian_question(self):
        graph = rg.build_register_graph()
        result = await graph.ainvoke(state_for("I want to register my daughter"))
        assert "full name" in result["messages"][-1].content.lower()
        assert result["registration"]["awaiting"] == "guardian.full_name"

    async def test_an_answer_advances_to_the_next_slot(self):
        graph = rg.build_register_graph()
        state = await graph.ainvoke(state_for("register"))
        state = await answer(graph, state, "Rachel Providence")
        assert state["registration"]["awaiting"] == "guardian.national_id"

    async def test_a_bad_answer_re_asks_with_the_reason_and_does_not_advance(self):
        graph = rg.build_register_graph()
        state = await graph.ainvoke(state_for("register"))
        state = await answer(graph, state, "Rachel Providence")
        state = await answer(graph, state, "not an id at all")

        assert "A1234567" in state["messages"][-1].content
        # Still on the same slot. A re-ask that advanced would leave a hole.
        assert state["registration"]["awaiting"] == "guardian.national_id"

    async def test_resuming_picks_up_at_the_exact_next_slot(self):
        """The acceptance criterion."""
        draft = store.Draft(
            application_id="app-1",
            resume_token="token-1",
            values={
                "guardian.full_name": "Rachel Providence",
                "guardian.national_id": "A12345678",
                "guardian.date_of_birth": date(1985, 3, 14),
            },
        )

        async def loader(token: str):
            return draft if token == "token-1" else None

        graph = rg.build_register_graph(loader=loader)
        state = state_for("carry on", safety_flags={"resume_token": "token-1"})
        result = await graph.ainvoke(state)

        assert result["registration"]["awaiting"] == "guardian.relationship"
        assert "related" in result["messages"][-1].content.lower()

    async def test_an_optional_slot_is_asked_and_offers_a_skip_chip(self):
        """`optional` means "may be declined", not "is never asked"."""
        draft = store.Draft(
            application_id="app-2",
            resume_token="t",
            values={
                slot.path: "x"
                for slot in rs.GUARDIAN_SLOTS
                if not slot.optional and slot.path != "guardian.email"
            },
        )

        async def loader(token: str):
            return draft

        graph = rg.build_register_graph(loader=loader)
        result = await graph.ainvoke(
            state_for("hi", safety_flags={"resume_token": "t"})
        )

        assert result["registration"]["awaiting"] == "guardian.email"
        assert result["quick_replies"] == ["Skip"]

    async def test_skipping_an_optional_slot_advances_the_walk(self):
        """And does so without writing an answer for it."""
        draft = store.Draft(
            application_id="app-2b",
            resume_token="t",
            values={
                slot.path: "x"
                for slot in rs.GUARDIAN_SLOTS
                if not slot.optional and slot.path != "guardian.email"
            },
        )
        async def loader(token: str):
            return draft

        graph = rg.build_register_graph(loader=loader)
        # `_entry` routes to `extract` on `registration.awaiting`, which is state, not the draft.
        result = await graph.ainvoke(
            state_for(
                "skip",
                registration={
                    "application_id": "app-2b",
                    "resume_token": "t",
                    "filled": [
                        slot.path
                        for slot in rs.GUARDIAN_SLOTS
                        if not slot.optional and slot.path != "guardian.email"
                    ],
                    "awaiting": "guardian.email",
                },
            )
        )

        registration = result["registration"]
        assert "guardian.email" in registration["skipped"]
        assert "guardian.email" not in registration["filled"]
        assert registration["awaiting"] != "guardian.email"

    async def test_a_closed_set_slot_offers_its_options_as_chips(self):
        draft = store.Draft(
            application_id="app-3",
            resume_token="t",
            values={"guardian.full_name": "R P", "guardian.national_id": "A12345678",
                    "guardian.date_of_birth": date(1985, 3, 14)},
        )

        async def loader(token: str):
            return draft

        graph = rg.build_register_graph(loader=loader)
        result = await graph.ainvoke(
            state_for("hi", safety_flags={"resume_token": "t"})
        )
        assert result["quick_replies"]
        assert "Mother" in result["quick_replies"]


# ── uploads ──────────────────────────────────────────────────────────────────


class TestUploads:
    def test_the_interrupt_payload_carries_no_bytes(self):
        slot = rs.slot_for("child.birth_certificate")
        payload = upload.interrupt_payload(slot, "en")
        assert payload["type"] == "upload_request"
        assert payload["slot"] == "child.birth_certificate"
        assert "application/pdf" in payload["accepts"]
        assert payload["max_mb"] == 10

    def test_a_resume_payload_carrying_a_preview_is_stripped(self, caplog):
        """Prevents a base64 thumbnail reaching a checkpoint and then a model prompt."""
        with caplog.at_level("WARNING"):
            cleaned = upload._assert_no_bytes(
                {
                    "document_id": "doc-1",
                    "mime": "image/jpeg",
                    "preview_base64": "iVBORw0KGgo...",
                    "raw": b"...",
                }
            )
        assert set(cleaned) == {"document_id", "mime"}
        assert "unexpected key" in caplog.text

    def test_a_document_ref_is_never_clean_by_default(self):
        """Unscanned must not be indistinguishable from scanned."""
        ref = upload.document_ref({"document_id": "doc-1", "mime": "image/jpeg"})
        assert ref["scan_status"] == "pending"

    def test_a_resume_with_no_id_produces_no_ref(self):
        assert upload.document_ref({}) is None
        assert upload.document_ref(None) is None

    def test_a_document_slot_refuses_typed_text(self):
        _value, problem = rs.slot_for("child.birth_certificate").parse("here you go")
        assert problem is not None and "photo" in problem


# ── doc_check ────────────────────────────────────────────────────────────────


class TestDocCheck:
    def test_a_clear_document_passes_silently(self):
        verdict = doc_check.Verdict(confidence=0.95)
        assert not verdict.should_flag
        assert not verdict.retake_worth_asking

    def test_a_blurry_document_is_worth_one_retake(self):
        verdict = doc_check.Verdict(legible=False, confidence=0.3)
        assert verdict.retake_worth_asking
        assert verdict.should_flag

    def test_a_wrong_document_type_is_not_worth_a_retake(self):
        """Asking a parent to re-photograph the wrong document wastes their time."""
        verdict = doc_check.Verdict(expected_type=False, confidence=0.2)
        assert verdict.should_flag
        assert not verdict.retake_worth_asking

    def test_a_name_mismatch_is_not_worth_a_retake_either(self):
        verdict = doc_check.Verdict(name_matches=False, confidence=0.3)
        assert not verdict.retake_worth_asking

    def test_the_cap_is_one(self):
        assert doc_check.MAX_RETAKES == 1

    def test_an_unavailable_check_flags_nothing_and_blocks_nothing(self):
        """A vision outage must not stop a family applying."""
        verdict = doc_check.Verdict(unavailable=True, confidence=0.0)
        assert not verdict.should_flag
        assert not verdict.retake_worth_asking

    def test_there_is_no_way_to_reject(self):
        """ADVISORY ONLY, asserted as an absence."""
        assert not hasattr(doc_check, "block_submission")
        assert not any(
            field in doc_check.Verdict.__slots__ for field in ("rejected", "blocked")
        )

    def test_the_retake_message_is_specific_and_cheerful(self):
        verdict = doc_check.Verdict(whole_page=False, confidence=0.3)
        message = doc_check.retake_message(verdict, "en")
        assert "corner" in message
        assert "?" in message


# ── review, attest, submit ───────────────────────────────────────────────────


class TestReview:
    def test_editing_one_field_clears_only_that_field(self):
        """The acceptance criterion."""
        registration = {
            "values": {
                "guardian.full_name": "Rachel Providence",
                "guardian.parish": "Saint Mary Cayon",
                "child.0.full_name": "Amara Providence",
            }
        }
        updated = review.jump_to_slot(registration, "guardian.parish")

        assert "guardian.parish" not in updated["values"]
        assert updated["values"]["guardian.full_name"] == "Rachel Providence"
        assert updated["values"]["child.0.full_name"] == "Amara Providence"
        assert updated["values"]["__awaiting"] == "guardian.parish"

    def test_an_edit_returns_to_review_rather_than_continuing_the_form(self):
        updated = review.jump_to_slot({"values": {}}, "guardian.parish")
        assert updated["return_to_review"] is True
        assert review.after_edit(updated) == "review"

    def test_a_child_slot_key_resolves_to_its_base_slot(self):
        updated = review.jump_to_slot(
            {"values": {"child.1.full_name": "B"}}, "child.1.full_name"
        )
        assert updated["values"]["__awaiting"] == "child.full_name"

    def test_an_unknown_slot_is_ignored_rather_than_clearing_something(self):
        registration = {"values": {"guardian.parish": "Saint Mary Cayon"}}
        assert review.jump_to_slot(registration, "guardian.nonsense") == registration

    def test_the_consent_version_is_recorded_with_the_timestamp(self):
        attestation = review.attestation_for(ip="1.2.3.4", actor="u-1")
        assert attestation.consent_version == review.CONSENT_VERSION
        assert attestation.at is not None
        assert attestation.ip == "1.2.3.4"

    def test_the_queue_summary_carries_only_masked_values(self):
        summary = review.summarise_for_reviewer(
            {"values": {"guardian.national_id": "A12345678", "guardian.parish": "Saint Mary Cayon"}}
        )
        values = {value for _key, _label, value in summary["fields"]}
        assert "A12345678" not in values
        assert "Saint Mary Cayon" in values

    @pytest.mark.asyncio
    async def test_submitting_without_attestation_is_refused(self):
        graph = rg.build_register_graph()
        state = state_for(
            "send it",
            registration={
                "application_id": "app-9",
                "resume_token": "t",
                "values": {},
                "phase": "review",
            },
        )
        result = await graph.ainvoke(state)
        assert "confirm" in result["messages"][-1].content.lower()
        assert result["registration"]["phase"] == "review"


# ── the status machine ───────────────────────────────────────────────────────


class TestStatusMachine:
    def test_the_allowed_moves(self):
        from app.api.admin.router import can_transition

        assert can_transition("submitted", "under_review")
        assert can_transition("under_review", "info_requested")
        assert can_transition("under_review", "approved")
        assert can_transition("under_review", "rejected")
        assert can_transition("info_requested", "under_review")

    def test_a_decision_is_terminal(self):
        """Reopening an approved application would let a decision be rewritten."""
        from app.api.admin.router import can_transition

        assert not can_transition("approved", "under_review")
        assert not can_transition("rejected", "under_review")

    def test_info_requested_cannot_jump_straight_to_approved(self):
        """The point of asking was to look again."""
        from app.api.admin.router import can_transition

        assert not can_transition("info_requested", "approved")

    def test_submitted_cannot_skip_review(self):
        from app.api.admin.router import can_transition

        assert not can_transition("submitted", "approved")


# ── the admin auth realm ─────────────────────────────────────────────────────


class TestStaffAuth:
    def test_a_chat_session_token_is_refused_at_the_admin_door(self):
        """The two realms cannot be interchanged. That is the whole point."""
        from app.api.admin.auth import decode_staff
        from app.graph.identity import mint_session_token

        chat = mint_session_token(
            session_id="s",
            user_id="u",
            device_id="d",
            persona="aurora",
            age_band="adult",
            account_status="guardian",
        )
        assert decode_staff(chat) is None

    def test_a_staff_token_is_refused_at_the_chat_door(self):
        from app.api.admin.auth import mint_staff_token
        from app.graph.identity import decode_session_token

        staff = mint_staff_token(staff_id="s-1", email="a@b.test", role="reviewer")
        assert decode_session_token(staff) is None

    def test_roles_are_a_ladder(self):
        from app.api.admin.auth import Staff

        supervisor = Staff(staff_id="s", email="e", role="supervisor")
        assert supervisor.at_least("reviewer")
        assert supervisor.at_least("supervisor")
        assert not supervisor.at_least("admin")

    def test_an_unknown_role_satisfies_nothing(self):
        from app.api.admin.auth import Staff

        assert not Staff(staff_id="s", email="e", role="root").at_least("reviewer")

    def test_an_unknown_role_cannot_be_minted(self):
        from app.api.admin.auth import mint_staff_token

        with pytest.raises(ValueError):
            mint_staff_token(staff_id="s", email="e", role="root")


# ── storage ──────────────────────────────────────────────────────────────────


class TestPresign:
    def test_an_oversize_file_is_refused_before_a_url_is_minted(self):
        from app.storage.presign import check_upload

        assert check_upload("image/jpeg", 40 * 1024 * 1024) is not None

    def test_an_unaccepted_type_is_refused(self):
        from app.storage.presign import check_upload

        assert check_upload("video/mp4", 1000) is not None

    def test_an_acceptable_upload_passes(self):
        from app.storage.presign import check_upload

        assert check_upload("image/jpeg", 500_000) is None

    def test_the_storage_key_is_scoped_and_unguessable(self):
        from app.storage.presign import storage_key_for

        key = storage_key_for("app-1", "child.birth_certificate", "abcdef")
        assert key.startswith("applications/app-1/")
        assert key.endswith("abcdef")

    def test_a_traversal_attempt_in_a_slot_name_cannot_escape(self):
        from app.storage.presign import storage_key_for

        key = storage_key_for("app-1", "../../etc/passwd", "x")
        assert ".." not in key

    def test_without_credentials_it_refuses_rather_than_degrading(self, monkeypatch):
        from app.config import get_settings
        from app.storage.presign import StorageUnavailable, presign_upload

        monkeypatch.setattr(get_settings(), "s3_access_key_id", None)
        with pytest.raises(StorageUnavailable):
            presign_upload(
                application_id="a", slot="s", mime="image/jpeg", size_bytes=100
            )
