"""A greeting is answered before the cache is consulted.

ORDER IS THE WHOLE POINT. The response cache is keyed on the question, so a turn
that was misrouted once is served from the shelf for ever after -- and a
greeting is the single most likely thing to be asked twice.

Measured on aspire.eccugenai.app, FRESH sessions, 23 August 2026:

    "hi"      -> "And how are you related to the child?"        78ms   cache
    "thanks"  -> "Pick the closest one -- mother, father, ..."  78ms   cache
    "ok"      -> the same                                      128ms   cache
    "bye"     -> the same                                       73ms   cache

The small-talk short-circuit exists precisely to answer "hi". It lived inside
the QA agent, three layers below the cache, so it never ran once: the cache
answered first, every time, with a question from a registration form. The very
first thing a new visitor says was answered by asking them how they are related
to a child they had not mentioned.
"""

from __future__ import annotations

import pytest

from app.agents.qa.nodes import small_talk_answer, small_talk_kind


class TestTheClosedClass:
    @pytest.mark.parametrize(
        "message,kind",
        [
            ("hi", "greeting"),
            ("hey!", "greeting"),
            ("hello", "greeting"),
            ("hola", "greeting"),
            ("bonjour", "greeting"),
            ("thanks", "thanks"),
            ("thank you", "thanks"),
            ("ok", "ack"),
            ("got it", "ack"),
            ("who are you", "identity"),
            ("say that again", "repeat"),
            ("bye", "bye"),
        ],
    )
    def test_it_is_recognised_without_a_graph_state(self, message: str, kind: str):
        assert small_talk_kind(message) == kind

    @pytest.mark.parametrize(
        "message",
        [
            "What is the minimum savings rate?",
            "How do I register my child?",
            "hi, how much does ASPIRE give me?",
            "Why does saving early matter?",
            "",
            "   ",
        ],
    )
    def test_a_real_question_falls_through_to_the_full_path(self, message: str):
        assert small_talk_kind(message) is None
        assert (
            small_talk_answer(message, locale="en", persona="kaleb", age_band="9-12")
            is None
        )

    def test_an_over_long_message_is_not_small_talk(self):
        """The length guard sits on top of the anchoring."""
        assert small_talk_kind("ok " * 40) is None


class TestNoneOfThemCanBeARegistrationQuestion:
    """The property, stated directly: whatever put those entries on the shelf,
    a greeting can no longer reach them, because it never reaches the shelf.
    """

    POISON = (
        "And how are you related to the child?",
        "Pick the closest one",
        "mother, father, grandmother",
    )

    @pytest.mark.parametrize("message", ["hi", "thanks", "ok", "bye", "who are you"])
    @pytest.mark.parametrize("locale", ["en", "es", "fr"])
    def test_the_answer_is_conversational(self, message: str, locale: str):
        reply = small_talk_answer(
            message, locale=locale, persona="stella", age_band="5-8"
        )
        assert reply, f"{message!r} produced nothing"
        for fragment in self.POISON:
            assert fragment.lower() not in reply.lower()


class TestItStillSpeaksAsTheRightGuide:
    def test_identity_names_the_persona(self):
        reply = small_talk_answer(
            "who are you", locale="en", persona="aurora", age_band="adult"
        )
        assert "Imani" in reply

    def test_and_in_the_readers_language(self):
        reply = small_talk_answer(
            "who are you", locale="fr", persona="nova", age_band="adult"
        )
        assert "Azuri" in reply and "guide" in reply.lower()

    def test_guest_stays_generic(self):
        reply = small_talk_answer(
            "who are you", locale="en", persona="guest", age_band="13-15"
        )
        assert "ASPIRE assistant" in reply


class TestTheStreamCallsItBeforeTheCache:
    """BEHAVIOURAL, not positional.

    The first version of this asserted that `small_talk_answer(` appeared
    earlier in stream.py than `cached_answer(`. That passes for the wrong
    reasons and fails for the wrong reasons: extracting either into a helper,
    or adding a second cache probe, changes the answer without changing the
    behaviour. It proves the source is arranged a certain way, not that the
    reader gets the greeting.

    So this poisons the cache with the exact string production was serving and
    asserts the greeting wins anyway.
    """

    @pytest.fixture
    def client(self, monkeypatch):
        import os

        os.environ.setdefault(
            "SESSION_SECRET", "test-only-secret-not-for-production-at-least-32-bytes"
        )
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.api import stream as stream_module
        from app.api.stream import router

        async def no_checkpointer():
            return None

        monkeypatch.setattr(stream_module, "get_checkpointer", no_checkpointer)

        # THE POISON, verbatim from production on 23 August 2026.
        async def always_a_registration_step(*args, **kwargs):
            return stream_module.turn_service.CachedTurn(
                reply="And how are you related to the child?",
                citations=[],
                quick_replies=["Mother", "Father", "Grandmother", "Grandfather"],
            )

        monkeypatch.setattr(
            stream_module.turn_service, "cached_answer", always_a_registration_step
        )

        async def noop(*args, **kwargs):
            return None

        monkeypatch.setattr(stream_module.turn_service, "open_conversation", noop)
        monkeypatch.setattr(stream_module.turn_service, "persist_turn", noop)

        app = FastAPI()
        app.include_router(router)
        return TestClient(app)

    @staticmethod
    def _say(client, message, **claims):
        from app.api.stream import parse_sse
        from app.graph.identity import mint_session_token

        base = {
            "session_id": "sess-order",
            "user_id": "u-1",
            "device_id": "d-1",
            "persona": "kaleb",
            "age_band": "9-12",
            "account_status": "beneficiary",
            "locale": "en",
        }
        base.update(claims)
        headers = {"Authorization": f"Bearer {mint_session_token(**base)}"}
        with client.stream(
            "POST", "/v2/chat/stream", json={"message": message}, headers=headers
        ) as response:
            events = parse_sse("".join(chunk for chunk in response.iter_text()))
        text = "".join(
            e["data"]["t"] for e in events if e["event"] == "token"
        )
        return text, events

    @pytest.mark.parametrize("message", ["hi", "thanks", "ok", "bye", "who are you"])
    def test_the_greeting_beats_a_poisoned_cache_entry(self, client, message):
        text, _ = self._say(client, message)
        assert "related to the child" not in text, (
            f"{message!r} was answered from the cache; layer 0 did not run first"
        )
        assert text.strip(), f"{message!r} produced no reply at all"

    def test_the_reply_is_the_conversational_one(self, client):
        text, _ = self._say(client, "hi")
        assert "Hello!" in text

    def test_identity_still_names_the_guide_through_the_wire(self, client):
        text, _ = self._say(client, "who are you")
        assert "Kaleb" in text

    def test_it_reports_itself_as_small_talk(self, client):
        _text, events = self._say(client, "hi")
        assert events[-1]["data"]["usage"]["agent"] == "small_talk"

    def test_a_real_question_still_reaches_the_cache(self, client):
        """The fix must not have turned the cache off for everything else."""
        text, _ = self._say(client, "What is the minimum savings rate?")
        assert "related to the child" in text, (
            "a non-small-talk question no longer consults the cache at all"
        )

    def test_a_refused_pair_is_still_refused_rather_than_greeted(self, client):
        """orion at 5-8 is not a combination this product serves."""
        text, _ = self._say(client, "hi", persona="orion", age_band="5-8")
        assert "Hello!" not in text



class TestTheCopyLivesInAFileAndFailsSafely:
    """The words moved to `data/small_talk.yaml`; the behaviour did not.

    The point is that the people best placed to fix the Spanish and the French
    are not going to open a `.py` file. The risk that buys is a badly edited
    YAML taking the greeting down, so every way of editing it badly is checked
    here, and every one of them costs the wording of one reply and nothing else.
    """

    @pytest.fixture
    def restore(self):
        from app.agents.qa import nodes

        original = nodes.COPY_PATH.read_text(encoding="utf-8")
        yield
        nodes.COPY_PATH.write_text(original, encoding="utf-8")
        nodes._copy.cache_clear()

    @staticmethod
    def _with(content):
        from app.agents.qa import nodes

        nodes._copy.cache_clear()
        if content is None:
            nodes.COPY_PATH.unlink()
        else:
            nodes.COPY_PATH.write_text(content, encoding="utf-8")

    def test_the_file_is_actually_read(self):
        from app.agents.qa.nodes import COPY_PATH, reply_for

        assert COPY_PATH.exists(), f"{COPY_PATH} is missing"
        assert reply_for("greeting", "fr").startswith("Bonjour")

    @pytest.mark.parametrize("kind", ["greeting", "thanks", "ack", "identity", "repeat", "bye"])
    @pytest.mark.parametrize("locale", ["en", "es", "fr"])
    def test_every_kind_has_every_language(self, kind: str, locale: str):
        from app.agents.qa.nodes import reply_for

        assert reply_for(kind, locale).strip()

    @pytest.mark.parametrize(
        "label,content",
        [
            ("file deleted", None),
            ("empty file", ""),
            ("broken YAML", "a:\n b:\n  - 'x\n bad"),
            ("a list at the top level", "- a\n- b"),
            ("a bare string", "just a string"),
            ("null", "null"),
            ("replies is a list", "replies:\n  - a"),
            ("replies is a string", "replies: nope"),
            ("identity_named is a list", "identity_named:\n  - a"),
            ("a kind maps to a string", "replies:\n  greeting: nope"),
            ("a value is a number", "replies:\n  greeting:\n    en: 42"),
            ("template names the wrong field", "identity_named:\n  en: 'I am {nam}'"),
            ("template has an unclosed brace", "identity_named:\n  en: 'I am {name'"),
            ("template is positional", "identity_named:\n  en: 'I am {0}'"),
            ("template never uses the name", "identity_named:\n  en: 'Hello there.'"),
            ("only one language present", "replies:\n  greeting:\n    en: Hi!"),
        ],
    )
    def test_a_bad_edit_costs_one_reply_and_nothing_else(self, restore, label, content):
        from app.agents.qa.nodes import reply_for, small_talk_answer

        self._with(content)
        assert reply_for("greeting", "en").strip(), f"{label} took the greeting down"
        named = small_talk_answer(
            "who are you", locale="fr", persona="nova", age_band="adult"
        )
        assert named and "Azuri" in named, f"{label} took the identity line down"

    def test_a_good_edit_actually_reaches_the_reader(self, restore):
        from app.agents.qa.nodes import reply_for

        self._with("replies:\n  greeting:\n    en: Welcome to ASPIRE!\n")
        assert reply_for("greeting", "en") == "Welcome to ASPIRE!"
        # and the languages it did not mention still work
        assert reply_for("greeting", "fr").startswith("Bonjour")

    def test_it_is_read_once_not_per_turn(self):
        """`lru_cache` — a greeting must not cost a file read."""
        from app.agents.qa.nodes import _copy

        assert _copy() is _copy()
