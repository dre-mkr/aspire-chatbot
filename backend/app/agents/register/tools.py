"""Opening the account sign-up wizard from inside a conversation.

An APPLICATION enrols a child in ASPIRE. An ACCOUNT is how a person signs in.
Applying through this assistant needs the second before the first, on a parent
or guardian's own account -- and until this existed there was no way to say so
from a conversation. A reader who was told "an application is completed by a
parent or guardian" had to go and find the sign-up page unaided, which is the
loop the ticket behind this change was stuck in.

## Where the working path actually is

`graph/nodes/cards._open_signup`, matched deterministically by
`intents.wants_account` before retrieval. This module is the same capability in
tool form, and the distinction matters because of what the v2 graph is:

    $ grep -rn "bind_tools" backend/app --include=*.py
    (no matches)

Nothing binds tools. `ELIGIBILITY_TOOLS` and `GAME_TOOLS` are in the same
position -- kept in the tree, wired to nothing, because the nodes that replaced
them are deterministic. `intents.py` sets out why that was an upgrade: a matcher
cannot be talked out of firing, costs no round trip, and cannot narrate what the
card is about to say.

So this is written to the same contract as `eligibility/tools.py` and will work
the moment an agent binds it, and it is NOT the reason the feature works today.
Deleting the matcher would break sign-up; deleting this file would not. That is
stated plainly rather than left for somebody to discover by changing one and
watching nothing happen.

## The role is not the model's to choose

`start_signup` takes no arguments. The wizard's opening branch is derived from
the reader's own audience by the node, from claims the server minted -- see
`cards._open_signup`. A tool that accepted `role="guardian"` would let a model
open the guardian branch for a nine-year-old on the strength of a sentence they
typed, and the whole point of deriving persona server-side is that a sentence
cannot do that.
"""

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
      "Sign me up for an account"          "¿Cómo creo una cuenta?"
      "Crear una cuenta de tutor"          "Créer un compte"

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
    # No session id, no arguments, no I/O. The node that emits the directive
    # holds the reader's audience; this exists so a tool-bound agent has the
    # same capability, and it deliberately cannot parameterise the wizard.
    logger.info("start_signup called")
    return {"ok": True, "opened": "signup"}


SIGNUP_TOOLS = [start_signup]
