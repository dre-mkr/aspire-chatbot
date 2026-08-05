"""The arq worker's wiring.

Every assertion here exists because the failure mode is a worker that imports
fine, starts, and then either dies with a message naming neither Valkey nor this
module, or -- worse -- runs perfectly and does nothing.
"""

from arq.connections import RedisSettings

from app.config import get_settings
from app.jobs import WorkerSettings
from app.retention import retention_job


def test_redis_settings_is_an_attribute_not_a_method():
    """arq reads this attribute; it never calls it.

    A `@staticmethod` here hands arq the descriptor object and the worker dies
    on startup with "'staticmethod' object has no attribute 'host'".
    """
    if not get_settings().valkey_url:
        # Nothing to configure without Valkey, and importing must still work.
        assert not hasattr(WorkerSettings, "redis_settings")
        return

    assert isinstance(WorkerSettings.redis_settings, RedisSettings)
    assert WorkerSettings.redis_settings.host


def test_the_retention_sweep_is_registered():
    """The only work this worker does. Replaces an assertion about the summary
    job, which was removed: the rolling summary lives in the checkpoint now and
    nothing had enqueued that job since `POST /chat` was deleted."""
    scheduled = [job.coroutine for job in WorkerSettings.cron_jobs]

    assert retention_job in scheduled, (
        "the nightly retention sweep is not registered, so a deployed worker "
        "would run cleanly and delete nothing"
    )


def test_nothing_is_enqueued_on_demand():
    """`functions` is empty ON PURPOSE, and this says so out loud.

    A registered job with no caller is indistinguishable from a broken one --
    the worker starts, reports healthy, and processes nothing forever. If
    something ever needs an on-demand job again, this test is the place that
    explains why the list was empty when it was written.
    """
    assert WorkerSettings.functions == []
