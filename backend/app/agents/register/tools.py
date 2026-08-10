"""Opening the account sign-up wizard from inside a conversation."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


@tool
def start_signup() -> dict[str, Any]:
    """Open the ASPIRE account sign-up form. Call this INSTEAD of explaining how.

    Call it when somebody asks to create an account they can sign in with:

      "I want to create an account"        "How do I make an account?"
      "Can I set up a guardian account?"   "I need a parent account"
      "Sign me up for an account"          "Â¿CÃ³mo creo una cuenta?"
      "Crear una cuenta de tutor"          "CrÃ©er un compte"

    An ACCOUNT is not an APPLICATION. If they are asking to enrol a child in
    ASPIRE, that is the registration flow, not this -- though somebody with no
    account needs one first, so this is the right call for "I want to register
    my daughter" from a reader who has no guardian account to do it from.

    ON SUCCESS, SAY ONE SHORT SENTENCE AT MOST. The form is on screen with its
    own heading and steps, so describing it is a second copy of what the reader
    is already looking at. Do not list the steps and do not ask for any of the
    fields yourself -- an email address or a date of birth typed into the chat
    is PII in a transcript, which is precisely what the form avoids.

    Never state which persona or assistant the new account will get. That is
    derived from the date of birth and role the form collects, server-side, and
    a guess made here is a promise the account may not keep.
    """
    # No session id, no arguments, no I/O.
    logger.info("start_signup called")
    return {"ok": True, "opened": "signup"}


SIGNUP_TOOLS = [start_signup]
