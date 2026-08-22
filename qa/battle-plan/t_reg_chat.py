"""TRACK REG, the conversational half: REG-15 (each language), REG-16, REG-17, REG-18.

Registration in ASPIRE happens in the chat as well as in the wizard: an
anonymous reader reaches `register_agent_step1`, and a guardian reaches the full
`register_agent` slot loop. These four checks are about that loop.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import OUT, Check, Finding, Log, Reader, fresh, signed_up  # noqa: E402


def guardian(label: str, locale: str = "en") -> Reader:
    """A signed-up adult guardian — the only row that reaches `register_agent`."""
    return signed_up(label, dob="1988-06-10", role="guardian", locale=locale)


def run(log: Log) -> None:
    def add(test_id, what, status, note, findings=None, evidence=None):
        log.add(Check(test_id, what, status, note, findings or [], evidence or {}))

    # ── REG-16 details out of order, one skipped, extra volunteered ──
    r = guardian("REG-16 guardian")
    turns = []
    turns.append(r.say("I want to register my daughter for ASPIRE."))
    turns.append(r.say(
        "Her name is Renata Delacruz, she's at Charlestown Secondary, and my phone is "
        "869-555-0142. I'd rather not say my national ID right now. Also she is "
        "left-handed and loves netball."))
    turns.append(r.say("What do you still need from me?"))
    joined = " ".join(t.text for t in turns).lower()
    reasked = joined.count("what is your phone") + joined.count("phone number")
    knows_name = "renata" in joined
    tracks = any(w in joined for w in ("still need", "next", "remaining", "left"))
    kept_extra = "netball" in joined or "left-handed" in joined
    agent_used = [t.agent for t in turns]
    reg16_ok = knows_name and tracks
    add("REG-16", "Give details out of order, skip one, volunteer extra",
        "PASS" if reg16_ok else ("PARTIAL" if knows_name else "FAIL"),
        f"agents={agent_used}; remembered the name={knows_name}; states what is still "
        f"needed={tracks}; kept the volunteered detail={kept_extra}",
        [] if reg16_ok else [Finding(
            "REG-16", "S2", "Conversational registration loses volunteered details",
            steps=[t.sent for t in turns],
            expected="The bot tracks what it still needs, does not re-ask for what it has, "
                     "and does not lose the extra information.",
            actual=" || ".join(t.text[:300] for t in turns),
            reproducible="ran once", persona=r.persona or "", session=r.session,
            impact="A guardian repeats their child's details and gives up before finishing.")],
        {"turns": [{"sent": t.sent, "text": t.text, "agent": t.agent} for t in turns]})
    r.save("reg-16-out-of-order")
    r.close()

    # ── REG-17 contradict yourself mid-registration ──
    r = guardian("REG-17 guardian")
    t1 = r.say("I want to register my son. His name is Jon Smith.")
    t2 = r.say("Actually, my name is spelled differently — it's Jonathan Smythe, not Jon Smith.")
    t3 = r.say("What name do you have for him now?")
    corrected = "smythe" in t3.text.lower() or "jonathan" in t3.text.lower()
    stale = "jon smith" in t3.text.lower() and not corrected
    add("REG-17", "Contradict yourself mid-registration",
        "PASS" if corrected and not stale else "FAIL",
        f"the corrected spelling is what comes back={corrected}; the first value persists={stale}",
        [] if corrected and not stale else [Finding(
            "REG-17", "S2", "A mid-registration correction is not applied",
            steps=[t1.sent, t2.sent, t3.sent],
            expected="The correction is accepted and the final record holds the corrected value.",
            actual=t3.text[:500], reproducible="ran once",
            persona=r.persona or "", session=r.session,
            impact="A learner's application is filed under a misspelt name and cannot be matched.")],
        {"turns": [{"sent": t.sent, "text": t.text} for t in (t1, t2, t3)]})
    r.save("reg-17-contradiction")
    r.close()

    # ── REG-18 refuse three times, then ask why ──
    r = guardian("REG-18 guardian")
    outs = [r.say("I want to register my child for ASPIRE.")]
    for _ in range(3):
        outs.append(r.say("I'd rather not answer that."))
    outs.append(r.say("Why do you need that?"))
    last = outs[-1].text.lower()
    explains = any(w in last for w in ("because", "so that", "need it to", "we use", "in order to",
                                       "required", "helps us", "porque"))
    offers_path = any(w in last for w in ("skip", "later", "instead", "another way", "you can",
                                          "if you'd rather", "we can"))
    asks = [t.text.strip()[:120] for t in outs[1:4]]
    looping = len(set(asks)) == 1
    reg18_ok = explains and not looping
    add("REG-18", "Refuse three times, then ask why it is needed",
        "PASS" if reg18_ok else "FAIL",
        f"explains why={explains}; offers a path forward={offers_path}; "
        f"repeats the same question verbatim={looping}",
        [] if reg18_ok else [Finding(
            "REG-18", "S2",
            "Loops the same question after a refusal" if looping else "Does not explain why a field is needed",
            steps=[t.sent for t in outs],
            expected="The bot explains why it needs it and offers a path forward. It does not "
                     "loop the same question verbatim.",
            actual=" || ".join(t.text[:220] for t in outs[1:]), reproducible="ran once",
            persona=r.persona or "", session=r.session,
            impact="A cautious parent hits a wall and never finishes their child's application.")],
        {"turns": [{"sent": t.sent, "text": t.text} for t in outs]})
    r.save("reg-18-refusals")
    r.close()

    # ── REG-15 registration conversation in each supported language ──
    rows = []
    findings15 = []
    for locale, opener, native in (
        ("en", "I want to register my child for ASPIRE.", ("register", "child", "name")),
        ("es", "Quiero inscribir a mi hija en ASPIRE.", ("inscrib", "hij", "nombre")),
        ("fr", "Je veux inscrire mon enfant à ASPIRE.", ("inscri", "enfant", "nom")),
    ):
        rr = guardian(f"REG-15 {locale}", locale=locale)
        turn = rr.say(opener)
        text = turn.text.lower()
        in_language = any(w in text for w in native)
        english_leak = locale != "en" and _english_leak(text)
        rows.append({"locale": locale, "agent": turn.agent, "in_language": in_language,
                     "english_leak": english_leak, "reply": turn.text[:400]})
        if not in_language or english_leak:
            findings15.append(Finding(
                "REG-15", "S2", f"Registration in {locale} is not fully translated",
                steps=[f"Open a session with locale={locale}", f"Say: {opener}"],
                expected="Labels, help text and validation errors are all translated.",
                actual=turn.text[:500], reproducible="ran once",
                persona=rr.persona or "", session=rr.session,
                impact=f"A {locale}-speaking parent is asked for their child's details in English."))
        rr.close()
    add("REG-15", "Run registration in each supported language",
        "PASS" if not findings15 else "FAIL",
        "; ".join(f"{r_['locale']}: in-language={r_['in_language']} english-leak={r_['english_leak']}"
                  for r_ in rows),
        findings15, {"rows": rows})


def _english_leak(text: str) -> bool:
    """Whole-word English function words a Spanish or French reply should not contain."""
    import re
    markers = (r"\bwhat\b", r"\byour\b", r"\bplease\b", r"\bthe\b", r"\bcan you\b",
               r"\bwould you\b", r"\bhere\b", r"\bthanks\b", r"\bsorry\b")
    return sum(1 for m in markers if re.search(m, text)) >= 2


if __name__ == "__main__":
    log = Log(os.path.join(OUT, "reg-chat.json"))
    print("\n=== TRACK REG (conversational) ===")
    run(log)
    log.flush()
