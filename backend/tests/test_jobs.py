"""The arq worker's wiring.

Both assertions here exist because the failure mode is a worker that imports
fine, starts, and then dies with a message naming neither Valkey nor this
module.
"""

from arq.connections import RedisSettings

from app.config import get_settings
from app.jobs import SUMMARISE_TASK, WorkerSettings, summarise_conversation_job


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


def test_the_registered_function_name_matches_what_we_enqueue():
    # `enqueue_job` takes the function's NAME as a string. A rename that misses
    # one of the two leaves jobs queued that no worker will ever claim.
    assert SUMMARISE_TASK == summarise_conversation_job.__name__
    assert summarise_conversation_job in WorkerSettings.functions
