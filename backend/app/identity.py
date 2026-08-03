"""Who is asking.

One module, because "who is this" is the kind of question that ends up answered
slightly differently in six places. Everything that needs a principal reads it
from here, so adding real accounts later is a change to `principal()` and
nothing else.

A principal is a namespaced string:

    device:9f1c4e...   an anonymous browser that has never signed in
    user:1042          a signed-in account

Two things are deliberately true of the anonymous form.

It is a bearer credential. Whoever holds the device id can read that device's
conversations, exactly as whoever holds the browser could read them out of
localStorage before this existed. It is not a claim about a person and must
never be treated as one — it is not shown, not logged beside content, and never
used as a display name.

It is client-minted. The server does not issue it, cannot revoke it, and must
therefore never trust it for anything beyond scoping a read to the same browser
that wrote it. Anything that needs a real identity waits for `user:`.
"""

from __future__ import annotations

import re

from fastapi import Header

#: The anonymous browser id, minted client-side on first use.
DEVICE_HEADER = "X-Aspire-Device"

#: A conservative shape for a client-minted id: a UUID, or the fallback form
#: `t-<base36>-<base36>` used where `crypto.randomUUID` is unavailable (it needs
#: a secure context, which a plain-HTTP staging box is not).
#:
#: Validated rather than trusted because this value reaches a SQL predicate and
#: a log line. It is parameterised at both, but a length cap and a character
#: class mean a hostile client cannot make either of those interesting.
_DEVICE_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def device_principal(device_id: str | None) -> str | None:
    """`device:<id>` for a well-formed id, or None."""
    if not device_id or not _DEVICE_RE.match(device_id):
        return None
    return f"device:{device_id}"


async def principal(
    x_aspire_device: str | None = Header(default=None),
) -> str | None:
    """The caller's principal, or None if they have no identity at all.

    A signed-in account outranks the device it is being used from, so when
    accounts arrive their branch goes above this one and the device id becomes
    a fallback rather than a competitor. Nothing downstream changes: callers
    already treat this as an opaque string.

    None is a legitimate answer, not an error. The chat endpoint accepts it —
    asking a question has never required identifying yourself and must not start
    to — and the read endpoints treat it as "you own nothing", which is true.
    """
    return device_principal(x_aspire_device)
