"""URL handling for Neon."""

from app.db.engine import POOLED_HOST_MARKER, _normalise, _strip_libpq_only_params


class TestDriverNormalisation:
    def test_postgres_scheme_becomes_asyncpg(self):
        # psql accepts `postgres://`, but SQLAlchemy would pick psycopg2 and break the async engine.
        assert _normalise("postgres://u:p@host/db").startswith("postgresql+asyncpg://")

    def test_postgresql_scheme_becomes_asyncpg(self):
        assert _normalise("postgresql://u:p@host/db").startswith("postgresql+asyncpg://")

    def test_an_explicit_driver_is_left_alone(self):
        url = "postgresql+asyncpg://u:p@host/db"
        assert _normalise(url) == url

    def test_credentials_survive_normalisation(self):
        assert "u:p@host" in _normalise("postgres://u:p@host/db")


class TestLibpqParameters:
    def test_sslmode_is_stripped(self):
        # Neon's copy-paste string ends in `?sslmode=require`, a libpq parameter.
        assert "sslmode" not in _strip_libpq_only_params(
            "postgresql://u:p@host/db?sslmode=require"
        )

    def test_channel_binding_is_stripped(self):
        assert "channel_binding" not in _strip_libpq_only_params(
            "postgresql://u:p@host/db?sslmode=require&channel_binding=require"
        )

    def test_the_query_string_goes_entirely_when_nothing_survives(self):
        assert (
            _strip_libpq_only_params("postgresql://u:p@host/db?sslmode=require")
            == "postgresql://u:p@host/db"
        )

    def test_other_parameters_are_kept(self):
        cleaned = _strip_libpq_only_params(
            "postgresql://u:p@host/db?sslmode=require&application_name=aspire"
        )
        assert "application_name=aspire" in cleaned
        assert "sslmode" not in cleaned

    def test_a_url_without_a_query_string_is_untouched(self):
        url = "postgresql://u:p@host/db"
        assert _strip_libpq_only_params(url) == url


def test_the_pooled_marker_is_what_we_check_for():
    # The direct endpoint gives one backend per connection, so a per-request pool exhausts it.
    assert POOLED_HOST_MARKER in "ep-cool-name-123456-pooler.us-east-2.aws.neon.tech"
    assert POOLED_HOST_MARKER not in "ep-cool-name-123456.us-east-2.aws.neon.tech"


def test_no_database_url_means_no_engine(monkeypatch):
    """The state the service runs in today, and must keep running in."""
    from app.config import get_settings
    from app.db import engine as db_engine

    get_settings.cache_clear()
    db_engine.get_engine.cache_clear()
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(
        db_engine, "get_settings", lambda: type("S", (), {"database_url": None})()
    )

    assert db_engine.get_engine() is None
    db_engine.get_engine.cache_clear()
    get_settings.cache_clear()


class TestEmbeddingDimensions:
    """The column width and the embedding model must agree."""

    def test_the_known_models_carry_their_real_widths(self):
        from app.db.models import dimensions_for

        # 1536 is `small` and ada.
        assert dimensions_for("text-embedding-3-large") == 3072
        assert dimensions_for("text-embedding-3-small") == 1536
        assert dimensions_for("text-embedding-ada-002") == 1536

    def test_an_unknown_model_is_reported_rather_than_guessed(self):
        from app.db.models import dimensions_for

        assert dimensions_for("some-future-model") is None

    def test_the_column_matches_a_model_we_know_about(self):
        from app.db.models import EMBEDDING_DIMENSIONS, EMBEDDING_MODEL_DIMENSIONS

        assert EMBEDDING_DIMENSIONS in EMBEDDING_MODEL_DIMENSIONS.values()

    def test_3072_cannot_be_indexed_as_a_plain_vector(self):
        # Which is why migration 0002 builds the HNSW index over a halfvec cast.
        from app.db.models import (
            EMBEDDING_DIMENSIONS,
            MAX_INDEXABLE_VECTOR_DIMENSIONS,
        )

        if EMBEDDING_DIMENSIONS > MAX_INDEXABLE_VECTOR_DIMENSIONS:
            import pathlib

            migration = pathlib.Path("alembic/versions/20260801_0002_indexes.py")
            assert "halfvec" in migration.read_text(encoding="utf-8")
