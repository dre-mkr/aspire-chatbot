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
        """What the name always claimed, and what it now actually checks.

        This asserted `startswith("aspire:answer:v1:")` -- the UN-namespaced form.
        `cache_key` ignored `namespace()` until P13-006, so answer keys and their
        leases sat in the shared production namespace and a pytest run read and
        wrote the live cache. The test encoded the bug rather than catching it,
        because the literal it pinned was exactly what the bug produced.
        """
        from app.cache import namespace

        produced = key("x" * 10_000)
        assert produced.startswith(namespace()), (
            f"{produced!r} is outside {namespace()!r}; a test run would share "
            "answer keys with production"
        )
        assert produced.startswith(f"{namespace()}answer:v1:")
        # Hashed, so a very long question cannot produce an unbounded key and no
        # user text leaks into logs or `KEYS` output. Bound allows for the test
        # namespace, which production does not carry.
        assert len(produced) < 64 + len(namespace())
        assert "x" * 20 not in produced

    def test_the_namespace_actually_isolates(self, monkeypatch):
        """Two namespaces must not collide on the same question.

        The property the P11-001 note asks for, asserted on answer keys rather
        than only on the metrics counters that were honouring it.
        """
        from app import cache

        monkeypatch.setenv("ASPIRE_CACHE_NAMESPACE", "run-a:")
        first = cache.cache_key("same question", language="en", persona=None, account_status=None)
        monkeypatch.setenv("ASPIRE_CACHE_NAMESPACE", "run-b:")
        second = cache.cache_key("same question", language="en", persona=None, account_status=None)

        assert first != second
        assert first.endswith(second.split(":")[-1]), (
            "only the namespace should differ; the digest is the same question"
        )


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
