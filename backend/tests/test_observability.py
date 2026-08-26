"""Tracing, and the two things it must never do by accident.

This product is used by children. A tracer that uploads what they typed is one
environment variable away from existing, so the defaults are the test.
"""

from __future__ import annotations

import pytest

from app.observability import _client, configure, tracing_enabled, turn_config


@pytest.fixture(autouse=True)
def _fresh_client():
    """`_client` is lru_cached, and every test here changes settings."""
    _client.cache_clear()
    yield
    _client.cache_clear()


def _settings(monkeypatch, **values):
    from app.config import get_settings

    settings = get_settings()
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value, raising=False)
    return settings


class TestOffIsTheDefault:
    def test_nothing_is_traced_without_the_flag(self, monkeypatch):
        _settings(monkeypatch, langsmith_tracing=False)
        assert tracing_enabled() is False

    def test_the_config_is_handed_back_untouched(self, monkeypatch):
        """The off path must cost nothing: no client, no callback, no copy."""
        _settings(monkeypatch, langsmith_tracing=False)
        config = {"configurable": {"thread_id": "t"}}
        assert turn_config(config, {"persona": "orion"}) is config

    def test_the_flag_without_a_key_stays_off_rather_than_raising(self, monkeypatch):
        """A half-configured server keeps answering readers."""
        _settings(monkeypatch, langsmith_tracing=True, langsmith_api_key=None)
        assert tracing_enabled() is False
        configure()  # must not raise


class TestWhatIsUploadedWhenItIsOn:
    def test_the_words_are_redacted_unless_asked_for(self, monkeypatch):
        """`hide_inputs`/`hide_outputs` have no environment variable, which is
        exactly why the safe default has to be chosen in code."""
        _settings(
            monkeypatch,
            langsmith_tracing=True,
            langsmith_api_key="lsv2_pt_test_not_a_real_key",
            langsmith_trace_content=False,
        )
        client = _client()
        assert client is not None
        assert client._hide_inputs is True
        assert client._hide_outputs is True

    def test_content_tracing_is_a_separate_deliberate_switch(self, monkeypatch):
        _settings(
            monkeypatch,
            langsmith_tracing=True,
            langsmith_api_key="lsv2_pt_test_not_a_real_key",
            langsmith_trace_content=True,
        )
        client = _client()
        assert client._hide_inputs is False
        assert client._hide_outputs is False

    def test_the_metadata_carries_no_personal_data(self, monkeypatch):
        _settings(
            monkeypatch,
            langsmith_tracing=True,
            langsmith_api_key="lsv2_pt_test_not_a_real_key",
            langsmith_project="aspire-test",
        )
        traced = turn_config(
            {"configurable": {"thread_id": "t"}},
            {
                "persona": "orion",
                "age_band": "16-18",
                "locale": "es",
                "account_status": "prospect",
                "active_agent": "qa_agent",
                "overlay": "limer",
            },
            session_id="sess-abc",
        )
        metadata = traced["metadata"]
        # What it carries: the shape of the reader, never the reader.
        assert metadata["persona"] == "orion"
        assert metadata["age_band"] == "16-18"
        assert metadata["locale"] == "es"
        assert metadata["session_id"] == "sess-abc"
        for forbidden in ("email", "name", "message", "text", "device_id", "ip"):
            assert forbidden not in metadata
        assert "persona:orion" in traced["tags"]
        assert traced["run_name"] == "aspire.turn"
        assert traced["callbacks"], "a tracer was attached"
        # And the thread config it was given survives.
        assert traced["configurable"]["thread_id"] == "t"

    def test_existing_callbacks_are_kept(self, monkeypatch):
        _settings(
            monkeypatch,
            langsmith_tracing=True,
            langsmith_api_key="lsv2_pt_test_not_a_real_key",
        )
        sentinel = object()
        traced = turn_config(
            {"configurable": {"thread_id": "t"}, "callbacks": [sentinel]},
            {"persona": "stella"},
        )
        assert sentinel in traced["callbacks"]
        assert len(traced["callbacks"]) == 2
