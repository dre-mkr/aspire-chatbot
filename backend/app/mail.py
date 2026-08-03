"""Sending the three emails this product actually needs.

A password reset, an address verification, and a sign-in link. Nothing else —
there is no newsletter here and no reason for one.

Two providers behind one function:

* `console` writes the message to the log and is the default. Development and
  the test suite must never depend on a network call, and a developer who has
  not configured a mail provider should still be able to complete a password
  reset by reading their own terminal.
* `resend` posts to a real API when `RESEND_API_KEY` is set.

Both are addressed through `send()`, so nothing upstream knows or cares which is
in use, and forgetting to configure mail degrades to "the link is in the log"
rather than to a 500 in somebody's face.

## What is not in these emails

No name, no conversation content, no device details. A reset email is proof of
control over an address and nothing more, and every extra fact in it is a fact
that leaks if the mailbox is shared — which, for a product used by children, is
the normal case rather than the exception.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

RESEND_ENDPOINT = "https://api.resend.com/emails"


@dataclass(frozen=True, slots=True)
class Message:
    to: str
    subject: str
    text: str


def _link(path: str, token: str) -> str:
    base = (get_settings().public_web_url or "http://localhost:3000").rstrip("/")
    return f"{base}{path}?token={token}"


def reset_email(to: str, token: str) -> Message:
    return Message(
        to=to,
        subject="Reset your ASPIRE password",
        text=(
            "Somebody asked to reset the password for this address.\n\n"
            f"{_link('/reset', token)}\n\n"
            "The link works once and expires in an hour. If this was not you, "
            "nothing has changed and you can ignore this message."
        ),
    )


def verify_email(to: str, token: str) -> Message:
    return Message(
        to=to,
        subject="Confirm your ASPIRE email",
        text=(
            "Confirm this address to finish setting up the account.\n\n"
            f"{_link('/verify', token)}\n\n"
            "The link works once and expires in a day."
        ),
    )


def signin_link_email(to: str, token: str) -> Message:
    return Message(
        to=to,
        subject="Your ASPIRE sign-in link",
        text=(
            "Here is the link you asked for. No password needed.\n\n"
            f"{_link('/signin', token)}\n\n"
            "It works once and expires in fifteen minutes. If you did not ask "
            "for it, ignore this message — nobody can get in without it."
        ),
    )


async def send(message: Message) -> bool:
    """Deliver, or say plainly that it was not delivered.

    Never raises. A mail provider being down must not turn "we have sent you a
    link" into a 500 — the caller has already done the useful work, and the
    honest failure is a message saying to try again shortly.
    """
    settings = get_settings()
    api_key = settings.resend_api_key

    if not api_key:
        # The default. Not a silent no-op: the link is right there in the log,
        # which is what makes a local password reset possible at all.
        logger.info(
            "[mail:console] to=%s subject=%s\n%s", message.to, message.subject, message.text
        )
        return True

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                RESEND_ENDPOINT,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "from": settings.mail_from,
                    "to": [message.to],
                    "subject": message.subject,
                    "text": message.text,
                },
            )
        if response.status_code >= 400:
            # The address is deliberately not logged at error level: a bounce
            # log becomes a list of real addresses.
            logger.error("Mail provider refused a message: %s", response.status_code)
            return False
        return True
    except Exception:
        logger.exception("Could not reach the mail provider.")
        return False
