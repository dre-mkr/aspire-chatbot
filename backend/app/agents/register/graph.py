"""The slot loop."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from app.agents.register import store
from app.agents.handoff import Handoff, filter_slots
from app.agents.handoff import from_state as handoff_from_state
from app.agents.register.schema import (
    CHILD_SLOTS,
    GUARDIAN_SLOTS,
    Slot,
    display_value,
    next_missing,
    slot_for,
)
from app.graph.state import AspireState

logger = logging.getLogger(__name__)

#: The consent text version currently on screen.
CONSENT_VERSION = "2026-08-v1"

CONSENT_TEXT: dict[str, str] = {
    "en": (
        "I confirm the details above are correct and I am the parent or legal "
        "guardian of the child named."
    ),
    "es": (
        "Confirmo que los datos anteriores son correctos y que soy el padre, la "
        "madre o el tutor legal del menor indicado."
    ),
    "fr": (
        "Je confirme que les informations ci-dessus sont exactes et que je suis "
        "le parent ou le tuteur légal de l'enfant nommé."
    ),
}


def _locale(state: AspireState) -> str:
    return str(state.get("locale") or "en")


def _draft(state: AspireState) -> store.Draft:
    """The draft this turn is working on, from state or fresh."""
    raw = state.get("registration")
    if isinstance(raw, dict) and raw.get("application_id"):
        # A PRESENCE map, rebuilt from the path list the checkpoint carries.
        values: dict[str, Any] = {path: PRESENT for path in (raw.get("filled") or [])}
        if raw.get("awaiting"):
            values["__awaiting"] = raw["awaiting"]
        return store.Draft(
            application_id=raw["application_id"],
            resume_token=raw.get("resume_token", ""),
            values=values,
            child_index=int(raw.get("child_index") or 0),
            children_complete=int(raw.get("children_complete") or 0),
            status=raw.get("status", "draft"),
            pending_corrections=list(raw.get("pending_corrections") or []),
            skipped=list(raw.get("skipped") or []),
        )
    return store.new_draft(state.get("session_id"))


async def load_real_values(draft: store.Draft) -> store.Draft:
    """The same draft with its actual answers, read from the database."""
    if not draft.resume_token:
        return draft
    loaded = await store.load_draft(draft.resume_token)
    if loaded is None:
        logger.warning(
            "Could not reload application %s; rendering from the presence map.",
            draft.application_id,
        )
        return draft
    loaded.child_index = draft.child_index
    loaded.children_complete = draft.children_complete
    # Skips live in the checkpoint, not the database: declining a slot writes no row anywhere.
    loaded.skipped = list(draft.skipped)
    return loaded


#: Stands in for an answer in the checkpoint's presence map.
PRESENT = "__present"


def _persist_state(draft: store.Draft) -> dict[str, Any]:
    """The pointers that go into the checkpoint."""
    return {
        "application_id": draft.application_id,
        "resume_token": draft.resume_token,
        # Paths only. This is the line F1 was about.
        "filled": sorted(key for key in draft.values if not key.startswith("__")),
        "child_index": draft.child_index,
        "children_complete": draft.children_complete,
        "status": draft.status,
        "pending_corrections": draft.pending_corrections,
        # Optional slots the parent declined.
        "skipped": list(draft.skipped),
        # The slot currently being asked for.
        "awaiting": draft.values.get("__awaiting"),
    }


# ── resume_or_start ──────────────────────────────────────────────────────────


def make_resume_or_start(loader=None):
    """Reopen a draft, enter correction mode, or begin a new application."""

    async def resume_or_start(state: AspireState) -> dict[str, Any]:
        raw = state.get("registration")
        if isinstance(raw, dict) and raw.get("application_id"):
            return {"registration": raw}

        token = (state.get("safety_flags") or {}).get("resume_token")
        draft = None
        if token:
            draft = await (loader or store.load_draft)(str(token))

        if draft is None:
            draft = store.new_draft(state.get("session_id"))
            await store.open_application(
                draft,
                session_id=state.get("session_id"),
                owner=state.get("user_id"),
            )
            logger.info("started application %s", draft.application_id)
        elif draft.in_correction_mode:
            # F2's loop.
            logger.info(
                "application %s reopened for corrections: %s",
                draft.application_id,
                draft.pending_corrections,
            )

        return {"registration": _persist_state(draft)}

    return resume_or_start


# ── next_missing_slot / ask ──────────────────────────────────────────────────


#: What an anonymous caller is told when the walk runs out of slots it may ask.
_HANDOFF: dict[str, str] = {
    "en": (
        "That is everything I can take without a grown-up. The next questions "
        "ask for things like an ID number, so a parent or guardian needs to "
        "sign in and finish with you. Nothing you have told me is lost."
    ),
    "es": (
        "Eso es todo lo que puedo aceptar sin una persona adulta. Las siguientes "
        "preguntas piden cosas como un numero de identificacion, asi que un padre, "
        "una madre o un tutor debe iniciar sesion y terminar contigo. No se ha "
        "perdido nada de lo que me has contado."
    ),
    "fr": (
        "C'est tout ce que je peux prendre sans une grande personne. Les questions "
        "suivantes demandent des choses comme un numero d'identite, alors un parent "
        "ou un tuteur doit se connecter et terminer avec toi. Rien de ce que tu m'as "
        "dit n'est perdu."
    ),
}


def pick_slot(
    draft: store.Draft,
    *,
    allow_sensitive: bool = True,
    handoff: Handoff | None = None,
) -> Slot | None:
    """Which question comes next."""
    if draft.in_correction_mode:
        candidates: list[Slot] = []
        for path in draft.pending_corrections:
            base = path
            if path.startswith("child.") and path.split(".")[1].isdigit():
                parts = path.split(".")
                base = f"child.{parts[-1]}"
            slot = slot_for(base)
            if slot is not None and draft.values.get(path) in (None, ""):
                candidates.append(slot)
        permitted = filter_slots(candidates, handoff)
        return permitted[0] if permitted else None

    # The barred set goes INTO the walk rather than filtering its output.
    return next_missing(
        draft.values,
        child_index=draft.child_index,
        allow_sensitive=allow_sensitive,
        barred=frozenset(handoff.do_not_reask if handoff else ()) | frozenset(draft.skipped),
    )


def make_ask(*, allow_sensitive: bool = True):
    """Ask for the next slot, with its options as quick replies."""

    def ask(state: AspireState) -> dict[str, Any]:
        draft = _draft(state)
        slot = pick_slot(
            draft, allow_sensitive=allow_sensitive, handoff=handoff_from_state(state)
        )
        locale = _locale(state)

        if slot is None:
            draft.values.pop("__awaiting", None)
            if not allow_sensitive:
                return {
                    "messages": [
                        AIMessage(content=_HANDOFF.get(locale) or _HANDOFF["en"])
                    ],
                    "registration": _persist_state(draft),
                }
            return {"registration": {**_persist_state(draft), "phase": "review"}}

        draft.values["__awaiting"] = slot.path
        prompt = slot.prompt.get(locale) or slot.prompt["en"]

        return {
            "messages": [AIMessage(content=prompt)],
            "quick_replies": _options_for(slot, locale),
            "registration": _persist_state(draft),
        }

    return ask


def make_collect(recorder=None):
    """A document slot: pause the graph, take an id, store it, move on."""

    async def collect(state: AspireState) -> dict[str, Any]:
        from langgraph.types import interrupt

        from app.agents.register.nodes.upload import (
            _assert_no_bytes,
            document_ref,
            interrupt_payload,
        )

        draft = _draft(state)
        locale = _locale(state)
        slot = pick_slot(draft, handoff=handoff_from_state(state))
        if slot is None or not slot.document:
            return {"registration": _persist_state(draft)}

        draft.values["__awaiting"] = slot.path
        label = _document_label(draft, slot)

        # `interrupt` replays the node from the top, so nothing above it may have side effects.
        raw = interrupt(
            interrupt_payload(
                slot, locale, label=label, application_id=draft.application_id
            )
        )
        payload = _assert_no_bytes(raw if isinstance(raw, dict) else {})

        if payload.get("skipped") and slot.optional:
            # No `save_slot`.
            _record_skip(draft, slot)
            draft.values.pop("__awaiting", None)
            return {"registration": {**_persist_state(draft), "phase": "next"}}

        ref = document_ref(payload)
        if ref is None:
            # Resumed with nothing usable.
            logger.info("document slot %s resumed with no id", slot.path)
            return {"registration": {**_persist_state(draft), "phase": "reask"}}

        await store.save_slot(draft, slot.path, ref)
        if recorder is not None:
            try:
                await recorder(draft, slot.path, payload)
            except Exception:
                # The document is in storage and the slot is filled.
                logger.exception(
                    "Could not record document %s for %s", ref["document_id"], slot.path
                )

        draft.values.pop("__awaiting", None)
        if draft.in_correction_mode:
            key = draft.key_for(slot.path)
            draft.pending_corrections = [
                pending for pending in draft.pending_corrections if pending != key
            ]

        logger.info(
            "[collected: %s] document %s",
            slot.path.rsplit(".", 1)[-1],
            ref["document_id"],
        )
        return {
            "registration": {
                **_persist_state(draft),
                "phase": "next",
                # Read by `doc_check`, which runs next and is advisory only.
                "__last_document": {**ref, "slot": slot.path, **payload},
            }
        }

    return collect


def _document_label(draft: store.Draft, slot: Slot) -> str:
    """"Rachel's birth certificate", not "child.birth_certificate"."""
    if not slot.path.startswith("child."):
        return slot.label
    name = draft.values.get(f"child.{draft.child_index}.full_name")
    if not isinstance(name, str) or not name.strip():
        return slot.label
    first = name.split()[0]
    possessive = f"{first}'" if first.endswith("s") else f"{first}'s"
    return f"{possessive} {slot.label[0].lower()}{slot.label[1:]}"


def _record_skip(draft: store.Draft, slot: Slot) -> None:
    """Note that this parent declined an optional slot, once."""
    key = draft.key_for(slot.path)
    if key not in draft.skipped:
        draft.skipped.append(key)
    logger.info("[skipped: %s]", slot.path.rsplit(".", 1)[-1])


def _options_for(slot: Slot, locale: str) -> list[str]:
    """Tap targets when the answer is one of a closed set."""
    if not slot.options:
        return _skip_chip(slot, locale)
    # `locale` was taken and ignored here, which is how a Spanish question ended
    # up over Mother / Father / Grandmother / Grandfather.
    if slot.path == "guardian.relationship":
        from app.agents.register.schema import relationship_label

        return [relationship_label(o, locale) for o in slot.options[:4]]
    return [option.title() for option in slot.options[:4]]


def _skip_chip(slot: Slot, locale: str) -> list[str]:
    if not slot.optional:
        return []
    return {
        "en": ["Skip"],
        "es": ["Saltar"],
        "fr": ["Passer"],
    }.get(locale, ["Skip"])


# ── extract / validate / persist ─────────────────────────────────────────────


def make_extract():
    """Parse the answer with the SLOT's parser."""

    async def extract(state: AspireState) -> dict[str, Any]:
        draft = _draft(state)
        path = draft.values.get("__awaiting")
        slot = slot_for(str(path)) if path else None
        if slot is None:
            return {"registration": _persist_state(draft)}

        from app.graph.nodes.safety_in import latest_user_text

        answer = latest_user_text(state).strip()
        locale = _locale(state)

        if slot.optional and answer.lower() in ("skip", "saltar", "passer", ""):
            # Recorded as a skip, not written as a None.
            _record_skip(draft, slot)
            draft.values.pop("__awaiting", None)
            return {"registration": {**_persist_state(draft), "phase": "next"}}

        value, problem = slot.parse(answer)
        if problem is not None:
            return {
                "messages": [
                    AIMessage(content=slot.reask.get(locale) or slot.reask["en"])
                ],
                "quick_replies": _options_for(slot, locale),
                "registration": {**_persist_state(draft), "phase": "reask"},
            }

        await store.save_slot(draft, slot.path, value)
        draft.values.pop("__awaiting", None)
        if draft.in_correction_mode:
            key = draft.key_for(slot.path)
            draft.pending_corrections = [
                pending for pending in draft.pending_corrections if pending != key
            ]

        # The transcript gets a MARKER, never the value.
        note = (
            f"[collected: {slot.path.rsplit('.', 1)[-1]}]"
            if slot.sensitive
            else f"[collected: {slot.path.rsplit('.', 1)[-1]} = {display_value(slot, value)}]"
        )
        logger.info("application %s %s", draft.application_id, note)

        return {"registration": {**_persist_state(draft), "phase": "next"}}

    return extract


# ── review / attest / submit ────────────────────────────────────────────────


def review_sections(draft: store.Draft) -> list[dict[str, Any]]:
    """The whole application, grouped, with sensitive values MASKED."""
    guardian_fields = []
    for slot in GUARDIAN_SLOTS:
        if slot.document:
            continue
        guardian_fields.append(
            (slot.path, slot.label, display_value(slot, draft.values.get(slot.path)))
        )

    sections = [
        {
            "title": "About you",
            "fields": guardian_fields,
            "documents": [
                str(draft.values.get(slot.path, {}).get("document_id", ""))
                for slot in GUARDIAN_SLOTS
                if slot.document and isinstance(draft.values.get(slot.path), dict)
            ],
        }
    ]

    for index in range(draft.children_complete + 1):
        fields = []
        for slot in CHILD_SLOTS:
            if slot.document:
                continue
            key = f"child.{index}.{slot.path[len('child.'):]}"
            fields.append((key, slot.label, display_value(slot, draft.values.get(key))))
        if not any(value for _key, _label, value in fields):
            continue
        sections.append(
            {
                "title": f"Child {index + 1}",
                "fields": fields,
                "documents": [
                    str(draft.values.get(key, {}).get("document_id", ""))
                    for slot in CHILD_SLOTS
                    if slot.document
                    for key in [f"child.{index}.{slot.path[len('child.'):]}"]
                    if isinstance(draft.values.get(key), dict)
                ],
            }
        )
    return sections


def make_review():
    """Render the whole application as an editable card."""

    async def review(state: AspireState) -> dict[str, Any]:
        from app.schemas.directives import ReviewCardDirective, ReviewSection

        # The one node that needs real answers rather than the presence map: it renders them.
        draft = await load_real_values(_draft(state))
        locale = _locale(state)

        directive = ReviewCardDirective(
            sections=[ReviewSection(**section) for section in review_sections(draft)]
        )

        return {
            "messages": [
                AIMessage(
                    content={
                        "en": "Here is everything. Check it over, change anything that is wrong, then confirm.",
                        "es": "Aquí está todo. Revísalo, cambia lo que esté mal y luego confirma.",
                        "fr": "Voici le tout. Vérifie, corrige ce qui ne va pas, puis confirme.",
                    }.get(locale, "Here is everything. Check it over, then confirm.")
                )
            ],
            "ui_directives": [directive],
            "registration": {**_persist_state(draft), "phase": "review"},
        }

    return review


def make_submit():
    """Attest and submit."""

    async def submit(state: AspireState) -> dict[str, Any]:
        draft = _draft(state)
        locale = _locale(state)
        flags = state.get("safety_flags") or {}
        attested = bool(flags.get("attested"))

        if not attested:
            return {
                "messages": [
                    AIMessage(
                        content={
                            "en": "I need you to tick the confirmation before I can send it.",
                            "es": "Necesito que marques la confirmación antes de enviarlo.",
                            "fr": "J'ai besoin que tu coches la confirmation avant l'envoi.",
                        }.get(locale, "Please confirm before I send it.")
                    )
                ],
                "registration": {**_persist_state(draft), "phase": "review"},
            }

        await store.attest_and_submit(
            draft,
            consent_version=str(flags.get("consent_version") or CONSENT_VERSION),
            ip=flags.get("ip"),
        )

        return {
            "messages": [
                AIMessage(
                    content={
                        "en": (
                            "Sent. ASPIRE has it now, and you will hear back within "
                            "five working days. Your reference is "
                            f"{draft.application_id[:8].upper()}."
                        ),
                        "es": (
                            "Enviado. ASPIRE ya lo tiene y recibirás noticias en "
                            "cinco días hábiles. Tu referencia es "
                            f"{draft.application_id[:8].upper()}."
                        ),
                        "fr": (
                            "Envoyé. ASPIRE l'a reçu et tu auras une réponse sous "
                            "cinq jours ouvrables. Ta référence est "
                            f"{draft.application_id[:8].upper()}."
                        ),
                    }.get(locale, "Sent.")
                )
            ],
            "registration": {**_persist_state(draft), "phase": "done"},
        }

    return submit


# ── routing ──────────────────────────────────────────────────────────────────


def _entry(state: AspireState) -> str:
    raw = state.get("registration")
    phase = (raw or {}).get("phase") if isinstance(raw, dict) else None
    awaiting = (raw or {}).get("awaiting") if isinstance(raw, dict) else None

    if phase == "review":
        return "submit" if (state.get("safety_flags") or {}).get("attested") else "review"
    if awaiting:
        return "extract"
    return "resume_or_start"


def _after_extract(state: AspireState) -> str:
    raw = state.get("registration") or {}
    phase = raw.get("phase")
    if phase == "reask":
        # The re-ask has already been said.
        return END
    # `route`, not `ask`.
    return "route"


def _after_ask(state: AspireState) -> str:
    raw = state.get("registration") or {}
    return "review" if raw.get("phase") == "review" else END


def _needs_document(state: AspireState) -> str:
    """Whether the next slot is a document, decided before anything is asked."""
    draft = _draft(state)
    slot = pick_slot(draft, handoff=handoff_from_state(state))
    if slot is None:
        return "review"
    return "collect" if slot.document else "ask"


def _after_collect(state: AspireState) -> str:
    raw = state.get("registration") or {}
    if raw.get("phase") == "reask":
        return END
    return "doc_check" if raw.get("__last_document") else "resume_or_start"


def _after_doc_check(state: AspireState) -> str:
    """A retake request ends the turn; anything else continues the walk."""
    raw = state.get("registration") or {}
    document = raw.get("__last_document") or {}
    return END if document.get("retakes_requested") else "resume_or_start"


def build_register_graph(
    *,
    loader=None,
    recorder=None,
    doc_check=None,
    checkpointer=None,
    allow_sensitive: bool = True,
):
    graph = StateGraph(AspireState)

    graph.add_node("resume_or_start", make_resume_or_start(loader))
    graph.add_node("route", _passthrough)
    graph.add_node("ask", make_ask(allow_sensitive=allow_sensitive))
    graph.add_node("collect", make_collect(recorder))
    graph.add_node("doc_check", doc_check or _no_doc_check)
    graph.add_node("extract", make_extract())
    graph.add_node("review", make_review())
    graph.add_node("submit", make_submit())

    graph.add_conditional_edges(
        START, _entry, ["resume_or_start", "extract", "review", "submit"]
    )
    graph.add_edge("resume_or_start", "route")
    # `route` exists so the document/typed split is a named conditional edge in the diagram.
    graph.add_conditional_edges("route", _needs_document, ["ask", "collect", "review"])
    graph.add_conditional_edges("ask", _after_ask, ["review", END])
    graph.add_conditional_edges(
        "collect", _after_collect, ["doc_check", "resume_or_start", END]
    )
    graph.add_conditional_edges("doc_check", _after_doc_check, ["resume_or_start", END])
    graph.add_conditional_edges("extract", _after_extract, ["route", END])
    graph.add_edge("review", END)
    graph.add_edge("submit", END)

    # A checkpointer is required for `interrupt()` to resume: paused state needs somewhere to live.
    return graph.compile(checkpointer=checkpointer)


async def _passthrough(state: AspireState) -> dict[str, Any]:
    """A named junction. The routing lives in the edge, not in a node."""
    return {}


async def _no_doc_check(state: AspireState) -> dict[str, Any]:
    """No vision model configured."""
    return {}


async def _record_document(draft: store.Draft, slot: str, payload: dict[str, Any]) -> None:
    """Insert the `documents_uploaded` row once the client confirms the PUT."""
    from app.storage.presign import document_record, storage_key_for

    await store.record_documents(
        draft,
        [
            document_record(
                document_id=str(payload["document_id"]),
                application_id=draft.application_id,
                slot=draft.key_for(slot),
                storage_key=str(
                    payload.get("storage_key")
                    or storage_key_for(
                        draft.application_id, slot, str(payload["document_id"])
                    )
                ),
                mime=str(payload.get("mime") or ""),
                size_bytes=int(payload.get("size_bytes") or 0),
                uploaded_by=None,
            )
        ],
    )


def build_production_register(*, allow_sensitive: bool = True):
    from app.agents.register.nodes.doc_check import make_doc_check, vision_invoke

    return build_register_graph(
        recorder=_record_document,
        doc_check=make_doc_check(vision_invoke()),
        allow_sensitive=allow_sensitive,
    )


def register() -> None:
    """Register both registration agent names, as two DIFFERENT graphs."""
    from functools import partial

    from app.graph.main_graph import register_agent

    register_agent("register_agent", partial(build_production_register, allow_sensitive=True))
    register_agent(
        "register_agent_step1", partial(build_production_register, allow_sensitive=False)
    )
