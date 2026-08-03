"""The response cache key.

The failure this file exists to prevent is a cached English answer being served
into a Spanish session: silent, plausible-looking, and wrong for the person
reading it. Everything here is pure -- no Valkey required.
"""

from app.cache import cache_key, normalise


def key(query: str, *, language="en", persona=None, account_status=None) -> str:
    return cache_key(
        query, language=language, persona=persona, account_status=account_status
    )


class TestNormalisation:
    def test_case_punctuation_and_whitespace_collapse(self):
        assert normalise("  What IS an Index Fund??  ") == "what is an index fund"

    def test_the_same_question_written_three_ways_shares_one_key(self):
        assert (
            key("What is an index fund?")
            == key("what is an index fund")
            == key("WHAT   IS AN INDEX FUND!!!")
        )

    def test_accents_are_preserved(self):
        # Stripping them would fold "años" into "anos", a different word. A
        # cache that answers the wrong question quickly is worse than a miss.
        assert "ñ" in normalise("¿Cuántos años?")
        assert key("cuántos años") != key("cuantos anos")

    def test_different_questions_do_not_collide(self):
        assert key("what is an index fund") != key("what is a bond")


class TestKeyDimensions:
    def test_language_separates(self):
        assert key("q", language="en") != key("q", language="es")

    def test_language_is_case_insensitive(self):
        assert key("q", language="ES") == key("q", language="es")

    def test_persona_separates(self):
        # Persona changes what the assistant may say, so an answer cached for
        # one must never be served to another.
        assert key("q", persona="student") != key("q", persona="parent")
        assert key("q", persona=None) != key("q", persona="student")

    def test_account_status_separates(self):
        assert key("q", account_status="active") != key("q", account_status="lapsed")

    def test_key_is_namespaced_and_bounded(self):
        # Hashed, so a very long question cannot produce an unbounded key and no
        # user text leaks into logs or `KEYS` output.
        produced = key("x" * 10_000)
        assert produced.startswith("aspire:answer:v1:")
        assert len(produced) < 64
        assert "x" * 20 not in produced


class TestValkeyUrl:
    """`localhost` is pinned to IPv4 -- see `valkey_url` for why."""

    def test_localhost_is_pinned_to_ipv4(self, monkeypatch):
        from app import cache
        from app.config import get_settings

        monkeypatch.setattr(
            cache,
            "get_settings",
            lambda: type("S", (), {"valkey_url": "redis://localhost:6380"})(),
        )
        assert cache.valkey_url() == "redis://127.0.0.1:6380"

    def test_a_real_host_is_left_alone(self, monkeypatch):
        from app import cache

        url = "rediss://user:pw@valkey.example.com:6379/0"
        monkeypatch.setattr(
            cache, "get_settings", lambda: type("S", (), {"valkey_url": url})()
        )
        assert cache.valkey_url() == url

    def test_unset_stays_none(self, monkeypatch):
        from app import cache

        monkeypatch.setattr(
            cache, "get_settings", lambda: type("S", (), {"valkey_url": None})()
        )
        assert cache.valkey_url() is None
