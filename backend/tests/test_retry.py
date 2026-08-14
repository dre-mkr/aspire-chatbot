"""Bounded retries on the calls that leave this process.

Nothing in `app/` retried anything before this. `tenacity` sits in the lockfile
as a transitive dependency and is imported nowhere; the only backoff in the repo
was one retry on the Valkey client. So every model call and every embedding was
one attempt and then a refusal, and a single dropped connection turned a good
answer into "The assistant is temporarily unavailable" -- the likeliest reading
of "The assistant could not be reached" during the 11 Aug demo.
"""

from __future__ import annotations

import asyncio

import pytest

from app.retry import with_retry


@pytest.mark.asyncio
async def test_a_transient_failure_is_tried_again():
    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("connection reset by peer")
        return "answer"

    assert await with_retry(flaky, what="probe", backoff=0.001) == "answer"
    assert attempts["n"] == 3


@pytest.mark.asyncio
async def test_it_gives_up_rather_than_hanging_on():
    attempts = {"n": 0}

    async def broken():
        attempts["n"] += 1
        raise TimeoutError("upstream timed out")

    with pytest.raises(TimeoutError):
        await with_retry(broken, what="probe", attempts=3, backoff=0.001)

    assert attempts["n"] == 3, "a bounded retry must actually be bounded"


@pytest.mark.asyncio
async def test_a_permanent_failure_is_not_retried():
    """
    Asking again cannot fix a key that lacks the model.

    Measured against this project's own history: an OpenAI project key that
    cannot reach a model 403s, and retrying it three times only spends the
    reader's patience.
    """
    attempts = {"n": 0}

    async def refused():
        attempts["n"] += 1
        raise RuntimeError("Error code: 403 - does not have access to model gpt-9")

    with pytest.raises(RuntimeError):
        await with_retry(refused, what="probe", backoff=0.001)

    assert attempts["n"] == 1


@pytest.mark.asyncio
async def test_a_cancelled_turn_is_not_retried():
    """The reader closed the tab. Retrying spends money on nobody."""
    attempts = {"n": 0}

    async def cancelled():
        attempts["n"] += 1
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await with_retry(cancelled, what="probe", backoff=0.001)

    assert attempts["n"] == 1


@pytest.mark.asyncio
async def test_the_first_success_costs_nothing_extra():
    attempts = {"n": 0}

    async def fine():
        attempts["n"] += 1
        return "answer"

    assert await with_retry(fine, what="probe") == "answer"
    assert attempts["n"] == 1


@pytest.mark.asyncio
async def test_every_retry_is_logged(caplog):
    """A retry nobody can see is a latency mystery later."""
    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise ConnectionError("reset")
        return "answer"

    with caplog.at_level("WARNING"):
        await with_retry(flaky, what="qa.generate", backoff=0.001)

    assert any("qa.generate" in record.getMessage() for record in caplog.records)
