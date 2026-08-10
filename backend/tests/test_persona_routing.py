"""Per-persona model routing and output caps (P14-A)."""

from __future__ import annotations

import os

os.environ.setdefault("SESSION_SECRET", "test-only-secret-not-for-production")

from app.agent import resolve_max_tokens_for, resolve_model_for  # noqa: E402
from app.config import get_settings  # noqa: E402


class TestModelRouting:
    def test_empty_config_routes_every_persona_to_the_default(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(settings, "chat_model_by_persona", {})
        for persona in (None, "", "stella", "orion", "aurora", "nova", "unknown"):
            assert resolve_model_for(persona) == settings.chat_model

    def test_a_routed_persona_gets_its_model_and_nobody_else_does(self, monkeypatch):
        settings = get_settings()
        monkeypatch.setattr(
            settings, "chat_model_by_persona", {"stella": "openai:gpt-5.6-terra"}
        )
        assert resolve_model_for("stella") == "openai:gpt-5.6-terra"
        assert resolve_model_for("aurora") == settings.chat_model
        assert resolve_model_for(None) == settings.chat_model

    def test_the_auxiliary_calls_cannot_be_routed(self, monkeypatch):
        """Titles and summaries always use the default model."""
        import inspect

        from app import agent

        settings = get_settings()
        monkeypatch.setattr(
            settings, "chat_model_by_persona", {"stella": "openai:gpt-5.6-terra"}
        )
        for factory in (agent._title_model, agent._summary_model):
            source = inspect.getsource(factory)
            assert "resolve_model_for" not in source


class TestMaxTokens:
    def test_unset_means_uncapped(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "max_tokens_by_persona", {})
        assert resolve_max_tokens_for("stella") is None
        assert resolve_max_tokens_for(None) is None

    def test_the_blank_entry_is_the_fallback_for_everyone(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "max_tokens_by_persona", {"": 4096})
        for persona in (None, "stella", "orion", "aurora", "nova"):
            assert resolve_max_tokens_for(persona) == 4096

    def test_a_persona_entry_beats_the_fallback(self, monkeypatch):
        monkeypatch.setattr(
            get_settings(), "max_tokens_by_persona", {"": 4096, "stella": 2048}
        )
        assert resolve_max_tokens_for("stella") == 2048
        assert resolve_max_tokens_for("orion") == 4096

    def test_zero_means_uncapped_not_zero_output(self, monkeypatch):
        """A 0 in config must read as "no cap", never as max_tokens=0 -- a cap of zero would reject every request at the…"""
        monkeypatch.setattr(get_settings(), "max_tokens_by_persona", {"": 0})
        assert resolve_max_tokens_for("stella") is None


# `TestAgentSharing` stood here.
