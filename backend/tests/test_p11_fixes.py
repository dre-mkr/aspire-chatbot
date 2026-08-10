"""Regression tests for the P11 remediation batch."""

from __future__ import annotations

import pytest

from app import cache as response_cache


# ── P11-002: a signing key too short to be one is refused ──────────────────


def test_a_short_session_secret_is_refused(monkeypatch):
    """The presence check was never the strength check."""
    from app import auth
    from app.config import Settings, get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SESSION_SECRET", "tooshort")
    monkeypatch.setattr(auth, "get_settings", lambda: Settings())

    with pytest.raises(RuntimeError, match="at least 32"):
        auth._secret()


def test_an_adequate_session_secret_is_accepted(monkeypatch):
    from app import auth
    from app.config import Settings

    get = lambda: Settings()  # noqa: E731
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    monkeypatch.setattr(auth, "get_settings", get)
    assert auth._secret() == "x" * 32


# ── P7-004: an edited knowledge base retires answers built from the old one ──


def test_the_cache_key_changes_with_the_corpus(monkeypatch, tmp_path):
    """Re-ingesting an edited CSV must not leave stale answers servable."""
    from app.config import Settings, get_settings

    original = tmp_path / "kb.csv"
    original.write_text("id,question,answer\nASP-001,What is it?,The old answer.\n", encoding="utf-8")

    def _settings_for(path):
        s = get_settings().model_copy(update={"knowledge_base_csv": path})
        return s

    monkeypatch.setattr(response_cache, "get_settings", lambda: _settings_for(original))
    response_cache.corpus_fingerprint.cache_clear()
    before = response_cache.cache_key("What is it?", language="en", persona=None, account_status=None)

    edited = tmp_path / "kb2.csv"
    edited.write_text("id,question,answer\nASP-001,What is it?,The CORRECTED answer.\n", encoding="utf-8")
    monkeypatch.setattr(response_cache, "get_settings", lambda: _settings_for(edited))
    response_cache.corpus_fingerprint.cache_clear()
    after = response_cache.cache_key("What is it?", language="en", persona=None, account_status=None)

    assert before != after, (
        "the same question against a different corpus must not share a cache key"
    )


def test_a_missing_corpus_does_not_stop_caching(monkeypatch, tmp_path):
    """No corpus to fingerprint is not a reason to stop answering."""
    from app.config import get_settings

    missing = tmp_path / "gone.csv"
    monkeypatch.setattr(
        response_cache,
        "get_settings",
        lambda: get_settings().model_copy(update={"knowledge_base_csv": missing}),
    )
    response_cache.corpus_fingerprint.cache_clear()
    assert response_cache.corpus_fingerprint() == "nocorpus"


# ── P9-003: an email body is a credential and is not logged by default ──────


def test_the_console_mailer_does_not_log_links_by_default(caplog, monkeypatch):
    """A production deploy that forgets RESEND_API_KEY must not leak tokens."""
    import asyncio

    from app import mail
    from app.config import Settings

    monkeypatch.setenv("RESEND_API_KEY", "")
    monkeypatch.setenv("MAIL_CONSOLE_LOGS_LINKS", "false")
    monkeypatch.setattr(mail, "get_settings", lambda: Settings())

    message = mail.Message(
        to="child@example.com",
        subject="Sign in to ASPIRE",
        text="Open https://aspire.example/verify?token=SECRET-TOKEN-VALUE to sign in.",
    )
    with caplog.at_level("INFO"):
        assert asyncio.run(mail.send(message)) is True

    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "SECRET-TOKEN-VALUE" not in logged, "a working credential reached the log"
    assert "child@example.com" not in logged, "a child's address reached the log"
    assert "RESEND_API_KEY" in logged, "the operator should be told why nothing was sent"
