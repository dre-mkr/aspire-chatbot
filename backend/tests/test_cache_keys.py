"""The response cache key.

The failure this file exists to prevent is a cached English answer being served
into a Spanish session: silent, plausible-looking, and wrong for the person
reading it. Everything here is pure -- no Valkey required.
"""

from app.cache import cache_key, normalise


def key(
    query: str, *, language="en", persona=None, account_status=None, age_band=None
) -> str:
    return cache_key(
        query,
        language=language,
        persona=persona,
        account_status=account_status,
        age_band=age_band,
    )


class TestAgeBand:
    """One persona spans three bands, and each has a different word cap.

    `safety_out` caps a reply at 35 words for 5-8, 70 for 9-12 and 180 for
    16-18. `orion` is the mascot for 9-12, 13-15 and 16-18 alike, so a key that
    stopped at persona would let a 180-word answer written for a sixteen-year-
    old be served whole to a nine-year-old -- and a cache hit never reaches the
    gate that would have cut it.
    """

    def test_two_bands_on_one_persona_do_not_share_a_key(self):
        assert key("What is interest?", persona="orion", age_band="9-12") != key(
            "What is interest?", persona="orion", age_band="16-18"
        )

    def test_the_same_band_still_shares_one_key(self):
        assert key("What is interest?", persona="orion", age_band="9-12") == key(
            "What is interest?", persona="orion", age_band="9-12"
        )

    def test_an_absent_band_is_its_own_bucket(self):
        """Not silently folded into any real band.

        A caller with no band -- the eval harness, a direct construction -- must
        not read or write the entries belonging to a child.
        """
        assert key("What is interest?", persona="orion") != key(
            "What is interest?", persona="orion", age_band="9-12"
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

        This asserted `startswith("aspire:answer:v2:")` -- the UN-namespaced form.
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
        assert produced.startswith(f"{namespace()}answer:v2:")
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


class TestFlushCoverage:
    """A key version that `flush_answers` cannot see is a flush that lies.

    `answer:` went v1 -> v2 when the age band entered the key and the sweep in
    `flush_answers` was left on `answer:v1:`, so a knowledge-base reload matched
    nothing and reported zero deleted -- indistinguishable from an empty cache.
    It had been verified live at 71 keys -> 0 before the bump.

    So these derive the prefix FROM the key builders rather than restating it.
    Bump a version without touching `_FLUSH_PREFIXES` and this fails, which is
    the only way a constant like that stays honest.
    """

    def _prefix(self, produced: str) -> str:
        from app.cache import namespace

        kind, version, _ = produced[len(namespace()) :].split(":", 2)
        return f"{kind}:{version}:"

    def test_the_answer_key_version_is_swept(self):
        from app.cache import _FLUSH_PREFIXES

        assert self._prefix(key("q")) in _FLUSH_PREFIXES

    def test_the_shelf_key_version_is_swept(self):
        from app.cache import _FLUSH_PREFIXES, semantic_shelf_key

        produced = semantic_shelf_key(language="en", persona=None, account_status=None)
        assert self._prefix(produced) in _FLUSH_PREFIXES

    def test_the_embedding_key_version_is_swept(self):
        from app.cache import _FLUSH_PREFIXES, embedding_key

        assert self._prefix(embedding_key("q", "m")) in _FLUSH_PREFIXES

    def test_the_probe_flush_keeps_the_embedding_cache(self):
        """`flush_probe_answers` measures a warm-MISS: answers gone, vectors warm.

        Deleting the embedding cache too would make every probe pay a ~400 ms
        round trip that the steady state it is modelling does not.
        """
        from app.cache import embedding_key
        from scripts.flush_probe_answers import _PREFIXES

        assert self._prefix(embedding_key("q", "m")) not in _PREFIXES
        assert self._prefix(key("q")) in _PREFIXES


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
