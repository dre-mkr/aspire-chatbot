"""Wire schemas, re-exported so `app.schemas` keeps meaning what it meant.

`app/schemas.py` was a module. It is now a package, because the graph needed a
second schema surface (`directives.py`) and a `schemas_directives.py` sitting
beside `schemas.py` would have been two files pretending not to be a package.

The original module moved to `http.py` and everything it exported is re-exported
here, so every existing `from app.schemas import ChatRequest` resolves exactly
as before. That is why this file has an explicit import list rather than a star
import: these names are the compatibility contract, and a star import would let
one of them disappear silently.

Two surfaces, deliberately separate:

  * `http` -- the REST request and response bodies for `/chat`, `/chat/stream`
    and the title endpoint. Unchanged.
  * `directives` -- what the graph tells a client to render, over SSE. New, and
    imported by path (`app.schemas.directives`) rather than re-exported here,
    so the two never blur into one namespace.
"""

from app.schemas.http import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    HealthResponse,
    Source,
    StartedEligibilityCheck,
    StartedGame,
    TitleRequest,
    TitleResponse,
)

__all__ = [
    "ChatRequest",
    "ChatResponse",
    "ErrorResponse",
    "HealthResponse",
    "Source",
    "StartedEligibilityCheck",
    "StartedGame",
    "TitleRequest",
    "TitleResponse",
]
