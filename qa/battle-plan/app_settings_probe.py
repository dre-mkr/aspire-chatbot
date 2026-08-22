"""Read the app's own session-token settings, and mint an already-expired one.

MEM-09 needs a session that has aged past its timeout. Waiting out the real TTL
is not runnable in a test window, so the token is minted with a negative
lifetime using the service's own signing key -- the same artefact the clock
would produce, arrived at sooner.
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta

BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


def session_ttl_seconds() -> int:
    from app.graph.identity import TOKEN_TTL
    return int(TOKEN_TTL.total_seconds())


def expired_graph_token(reader) -> str:
    from app.graph.identity import mint_session_token
    return mint_session_token(
        session_id=reader.session,
        user_id=None,
        device_id=reader.device,
        persona=reader.persona or "guest",
        age_band=reader.age_band or "13-15",
        account_status=reader.account_status or "prospect",
        locale=reader.locale,
        identity_proven=False,
        ttl=timedelta(seconds=-60),
    )
