"""The arq worker's wiring."""

from arq.connections import RedisSettings

from app.config import get_settings
from app.jobs import WorkerSettings
from app.retention import retention_job


def test_redis_settings_is_an_attribute_not_a_method():
    """arq reads this attribute; it never calls it."""
    if not get_settings().valkey_url:
        # Nothing to configure without Valkey, and importing must still work.
        assert not hasattr(WorkerSettings, "redis_settings")
        return

    assert isinstance(WorkerSettings.redis_settings, RedisSettings)
    assert WorkerSettings.redis_settings.host


def test_the_retention_sweep_is_registered():
    """The only work this worker does."""
    scheduled = [job.coroutine for job in WorkerSettings.cron_jobs]

    assert retention_job in scheduled, (
        "the nightly retention sweep is not registered, so a deployed worker "
        "would run cleanly and delete nothing"
    )


def test_nothing_is_enqueued_on_demand():
    """`functions` is empty ON PURPOSE, and this says so out loud."""
    assert WorkerSettings.functions == []
