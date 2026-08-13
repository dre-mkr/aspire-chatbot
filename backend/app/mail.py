"""Sending the three emails this product actually needs."""

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
    """Deliver, or say plainly that it was not delivered."""
    settings = get_settings()
    api_key = settings.resend_api_key

    if not api_key:
        # The development default, where logging the link is the only way to follow it.
        if settings.mail_console_logs_links:
            logger.info(
                "[mail:console] to=%s subject=%s\n%s",
                message.to,
                message.subject,
                message.text,
            )
        else:
            logger.error(
                "No RESEND_API_KEY is set, so %r could not be delivered. The link "
                "is NOT logged: it is a working credential. Set RESEND_API_KEY, or "
                "set MAIL_CONSOLE_LOGS_LINKS=true if this really is a development "
                "environment.",
                message.subject,
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
            # The address is left out on purpose: a bounce log becomes a list of real addresses.
            logger.error("Mail provider refused a message: %s", response.status_code)
            return False
        return True
    except Exception:
        logger.exception("Could not reach the mail provider.")
        return False
