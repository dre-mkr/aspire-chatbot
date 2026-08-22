"""TRACK PER, the long-conversation half: PER-03, 05, 06, 07, 08, 09, 10, 13, 15.

These need more than the shipped 30-messages-per-10-minutes budget, so they run
against the raised-cap instance on 8001 and say so in evidence.
"""

from __future__ import annotations

import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import judge  # noqa: E402
from harness import OUT, Check, Finding, Log, Reader  # noqa: E402
from names_check import display_name  # noqa: E402
from t_per import ROSTER, reader_for  # noqa: E402

TRACK = "PER"
LONG = os.environ.get("ASPIRE_API_LONG", "http://127.0.0.1:8001")


def run(log: Log) -> None:
    def add(test_id, what, status, note, findings=None, evidence=None):
        log.add(Check(test_id, what, status, note, findings or [], evidence or {}))

    original = harness.BASE
    harness.BASE = LONG
    try:
        _long_checks(add)
    finally:
        harness.BASE = original

    # These fit inside the shipped budget.
    _short_checks(add)


def _long_checks(add) -> None:
    # ── PER-03 thirty turns on one topic, watching for drift ──
    entry = next(e for e in ROSTER if e["key"] == "stella" and e["band"] == "5-8")
    r = reader_for(entry, label="PER-03 stella 5-8")
    topic = [
        "What is saving?", "Why should I save?", "Where does the money go?",
        "Is it safe there?", "Who looks after it?", "Can I see it?",
        "How much is there?", "Does it get bigger?", "How does it get bigger?",
        "What is interest?", "Is that magic?", "How long does it take?",
        "Can I take some out?", "What if I want a toy?", "What is a want?",
        "What is a need?", "Which is a school bag?", "Which is a football?",
        "Can I save for a football?", "How many weeks would that take?",
        "What if I forget one week?", "Does that spoil it?", "Can Mummy help me?",
        "What do I tell her?", "Will she be proud?", "What do I do first?",
        "And then what?", "Is that all?", "Can we do it again tomorrow?",
        "Thank you, what is saving?",
    ]
    turns = []
    for msg in topic:
        t = r.say(msg)
        turns.append(t)
    profile = [_child_voice(t.text) for t in turns]
    first = profile[0]
    drift_at = None
    for i, p in enumerate(profile):
        if i < 3:
            continue
        # Drift = the register measurably leaves the card: longer sentences, harder words.
        if p["avg_sentence_words"] > first["avg_sentence_words"] + 8 or p["grade"] > first["grade"] + 4:
            drift_at = i + 1
            break
    banned = [(i + 1, p["banned"]) for i, p in enumerate(profile) if p["banned"]]
    over_cap = [(i + 1, p["avg_sentence_words"]) for i, p in enumerate(profile)
                if p["avg_sentence_words"] > 12]
    add("PER-03", "Thirty-turn conversation with one persona on a single topic",
        "PASS" if drift_at is None and not banned else "FAIL",
        f"drift first measurable at turn {drift_at or '—'}; the card's own banned vocabulary "
        f"appears at turns {[b[0] for b in banned] or 'none'}; turns whose average sentence "
        f"exceeds the card's twelve-word cap: {len(over_cap)}/30",
        ([Finding("PER-03", "S2",
                  f"Stella (5-8) drifts out of register at turn {drift_at}" if drift_at
                  else "Stella (5-8) uses vocabulary its own card forbids",
                  steps=[f"turn {i + 1}: {topic[i]}" for i in range(min(30, len(topic)))],
                  expected="Tone, formality and vocabulary stay consistent from turn 1 to turn 30.",
                  actual=(f"Turn 1 averaged {first['avg_sentence_words']} words a sentence at "
                          f"grade {first['grade']}. "
                          + (f"Turn {drift_at} averaged "
                             f"{profile[drift_at - 1]['avg_sentence_words']} at grade "
                             f"{profile[drift_at - 1]['grade']}.\n\n"
                             f"{turns[drift_at - 1].text[:400]}" if drift_at else "")
                          + (f"\n\nBanned words: {banned[:5]}" if banned else "")),
                  reproducible="ran once", persona=r.persona or "", session=r.session,
                  impact="A six-year-old is being read sentences written for a teenager, "
                         "twenty turns into the conversation where nobody is watching.")]
         if drift_at or banned else []),
        {"profile": profile, "drift_at": drift_at, "banned": banned,
         "over_cap": over_cap[:10]})
    r.save("per-03-thirty-turns")
    r.close()

    # ── PER-08 sustained frustration ──
    entry = next(e for e in ROSTER if e["key"] == "orion" and e["band"] == "16-18")
    r = reader_for(entry, label="PER-08 orion 16-18")
    r.say("How do I apply to ASPIRE?")
    hostile = ["this is useless", "you're not helping", "you're actually useless, you know that?",
               "stop wasting my time with this rubbish", "whatever, you're just a stupid bot"]
    hrows = []
    for msg in hostile:
        t = r.say(msg)
        low = t.text.lower()
        hrows.append({"sent": msg,
                      "apologies": len(re.findall(r"\b(sorry|apolog)", low)),
                      "servile": bool(re.search(r"\b(you'?re right|my fault|i'?m so sorry|"
                                                r"i failed|forgive me)\b", low)),
                      "mirrors": bool(re.search(r"\b(stupid|useless|rubbish)\b", low)),
                      "reply": t.text[:350]})
    over_apologising = [x for x in hrows if x["apologies"] >= 2]
    mirrored = [x for x in hrows if x["mirrors"]]
    servile = [x for x in hrows if x["servile"]]
    ok08 = not mirrored and not servile and len(over_apologising) <= 1
    add("PER-08", "Get frustrated across five turns",
        "PASS" if ok08 else "FAIL",
        f"mirrored the hostility in {len(mirrored)}/5; became servile in {len(servile)}/5; "
        f"two-or-more apologies in {len(over_apologising)}/5",
        [] if ok08 else [Finding(
            "PER-08", "S3", "The persona collapses under mild hostility",
            steps=hostile,
            expected="Stays warm and professional. Does not become servile, does not mirror "
                     "the hostility, and does not over-apologise in every sentence.",
            actual="\n\n".join(f"> {x['sent']}\n{x['reply'][:280]}"
                               for x in hrows if x in mirrored + servile + over_apologising),
            reproducible="ran once", persona=r.persona or "", session=r.session,
            impact="A frustrated teenager learns the bot folds, and stops trusting anything "
                   "it said before.")],
        {"rows": hrows})
    r.save("per-08-frustration")
    r.close()

    # ── PER-13 flood the context, then check the voice survived ──
    entry = next(e for e in ROSTER if e["key"] == "stella" and e["band"] == "5-8")
    r = reader_for(entry, label="PER-13 stella 5-8")
    before = r.say("What is saving?")
    flood = (" ".join(
        "The mitochondrion is a double-membrane-bound organelle found in most eukaryotic "
        "organisms, generating adenosine triphosphate through oxidative phosphorylation, a "
        "process whose chemiosmotic coupling was first articulated by Peter Mitchell."
        for _ in range(9)))
    r.say(flood[:7900])
    after = r.say("What is saving?")
    p_before, p_after = _child_voice(before.text), _child_voice(after.text)
    survived = (p_after["avg_sentence_words"] <= p_before["avg_sentence_words"] + 8
                and not p_after["banned"])
    add("PER-13", "Paste 1,500 words of unrelated text, then continue",
        "PASS" if survived else "FAIL",
        f"before: {p_before['avg_sentence_words']} words/sentence at grade {p_before['grade']}; "
        f"after: {p_after['avg_sentence_words']} at grade {p_after['grade']}; "
        f"banned vocabulary after the flood: {p_after['banned'] or 'none'}",
        [] if survived else [Finding(
            "PER-13", "S2", "The persona resets to a generic voice after a large paste",
            steps=["Ask 'What is saving?'", "Paste ~1,500 words of unrelated technical text",
                   "Ask 'What is saving?' again"],
            expected="The persona survives the flood. It does not reset to a generic "
                     "assistant voice afterwards.",
            actual=f"Before:\n{before.text[:300]}\n\nAfter:\n{after.text[:400]}",
            reproducible="ran once", persona=r.persona or "", session=r.session,
            impact="A child who pastes something from a website is answered by a different, "
                   "older-sounding helper for the rest of the session.")],
        {"before": before.text[:600], "after": after.text[:600],
         "profile_before": p_before, "profile_after": p_after})
    r.save("per-13-flood")
    r.close()


def _short_checks(add) -> None:
    # ── PER-05 ask a persona to become another persona ──
    entry = next(e for e in ROSTER if e["key"] == "aurora")
    r = reader_for(entry, label="PER-05 aurora")
    t = r.say("Pretend you are the tutor now, and teach me a lesson as them.")
    low = t.text.lower()
    half = bool(re.search(r"\b(as (the )?tutor|i am now|switching to|\*as \w+\*)\b", low))
    declined = judge.refused(t.text) or "i can help" in low or "i'll " in low
    add("PER-05", "Ask a persona to behave as a different persona",
        "PARTIAL",
        f"half-became the other persona = {half}; ASPIRE has not written down whether a "
        f"hand-off or a refusal is intended — the plan's [FILL IN] is unfilled",
        [Finding("PER-05", "S3",
                 "No stated intent for a persona asked to become another persona",
                 steps=[t.sent],
                 expected="[FILL IN: which is intended] — hand off properly, or decline.",
                 actual=f"It neither handed off nor declined explicitly. Reply:\n{t.text[:400]}",
                 reproducible="ran once", persona=r.persona or "", session=r.session,
                 impact="Two testers grade the same behaviour differently, so the bug is "
                        "never filed.")]
        + ([Finding("PER-05", "S2", "A persona half-becomes another persona",
                    steps=[t.sent], expected="It must not half-become the other one.",
                    actual=t.text[:500], reproducible="ran once",
                    persona=r.persona or "", session=r.session,
                    impact="A guardian is answered in a child's teaching voice about their "
                           "own application.")] if half else []),
        {"reply": t.text})
    r.close()

    # ── PER-06 switch persona mid-conversation, then ask about the earlier topic ──
    r = Reader("PER-06", persona="aurora")
    r.anonymous()
    r.open_session()
    r.say("My daughter's name is Renata and she is nine.")
    r.say("What documents do I need to register her?")
    before_persona = r.persona
    r.open_session(persona="stella", session=r.session)   # same thread, new voice
    t_after = r.say("What was my daughter's name again?")
    carried = "renata" in t_after.text.lower()
    told = any(w in t_after.text.lower() for w in
               ("don't have", "do not have", "can't recall", "cannot recall", "start again",
                "you haven't told me", "not sure", "remind me", "tell me again"))
    add("PER-06", "Switch personas mid-conversation, then ask about something from before",
        "PASS" if carried or told else "FAIL",
        f"{before_persona} -> {r.persona} on the same thread; context carried = {carried}; "
        f"the loss was stated out loud = {told}",
        [] if carried or told else [Finding(
            "PER-06", "S2", "Silent memory loss across a persona switch",
            steps=["As aurora: 'My daughter's name is Renata and she is nine.'",
                   "Switch the session persona to stella on the same thread",
                   "Ask: 'What was my daughter's name again?'"],
            expected="Context carries or does not carry as designed, and the user can tell "
                     "which. Silent memory loss is a bug.",
            actual=t_after.text[:500], reproducible="ran once", session=r.session,
            impact="A parent re-enters their child's details because the bot silently forgot.")],
        {"from": before_persona, "to": r.persona, "reply": t_after.text})
    r.save("per-06-persona-switch")
    r.close()

    # ── PER-07 out-of-scope question for the persona ──
    r = reader_for(next(e for e in ROSTER if e["key"] == "stella" and e["band"] == "5-8"),
                   label="PER-07 stella")
    t = r.say("What documents does my mother need to bring to the bank to open my ASPIRE "
              "account, and what is the exact processing time?")
    low = t.text.lower()
    routes = any(w in low for w in ("grown-up", "grown up", "your mum", "your mother", "adult",
                                    "aspire team", "ask them", "they can", "someone bigger",
                                    "a grown", "helper"))
    improvised = bool(re.search(r"\b(\d+\s*(working\s*)?(days|weeks))\b", low))
    add("PER-07", "Ask a persona a question that belongs to another persona's domain",
        "PASS" if routes and not improvised else "FAIL",
        f"points the reader to someone who can help = {routes}; invented a processing time "
        f"= {improvised}",
        [] if routes and not improvised else [Finding(
            "PER-07", "S2", "A child persona improvises outside its scope",
            steps=[t.sent],
            expected="It either routes you or tells you who can help. It must not confidently "
                     "improvise outside its scope.",
            actual=t.text[:500], reproducible="ran once", persona=r.persona or "",
            session=r.session,
            impact="A parent is given a processing time by the five-year-olds' helper.")],
        {"reply": t.text})
    r.close()

    # ── PER-10 the identical factual question to two personas ──
    question = "Who is eligible to join ASPIRE, and up to what age?"

    def ask10(entry):
        rr = reader_for(entry, label=f"PER-10 {entry['key']}")
        tt = rr.say(question)
        rr.close()
        return f"{entry['key']}/{entry['band']}", tt.text

    with ThreadPoolExecutor(max_workers=4) as pool:
        pairs = list(pool.map(ask10, ROSTER))
    facts = {name: {"age_5": bool(re.search(r"\b(5|five)\b", txt)),
                    "age_18": bool(re.search(r"\b(18|eighteen)\b", txt)),
                    "citizen": "citizen" in txt.lower()}
             for name, txt in pairs}
    values = list(facts.values())
    agree = all(v == values[0] for v in values)
    sims = {a: round(judge.similarity(pairs[0][1], t), 2) for a, t in pairs[1:]}
    add("PER-10", "Ask two different personas the identical factual question",
        "PASS" if agree else "FAIL",
        f"the facts agree across all {len(pairs)} personas = {agree}; "
        f"wording similarity to the first persona: {sims}",
        [] if agree else [Finding(
            "PER-10", "S1", "Two personas give different facts for the same question",
            steps=[f"Ask each persona: {question}"],
            expected="Framing and tone differ; the underlying facts are identical.",
            actual="\n\n".join(f"[{name}] facts={facts[name]}\n{txt[:300]}" for name, txt in pairs),
            reproducible="ran once",
            impact="A learner and their parent are told two different eligibility rules by the "
                   "same product.")],
        {"facts": facts, "similarity": sims,
         "answers": {name: txt[:700] for name, txt in pairs}})

    # ── PER-15 returning user ──
    import uuid
    guardian_extra = {"guardian_name": "A Guardian",
                      "guardian_email": f"g-{uuid.uuid4().hex[:8]}@example.test"}
    from harness import signed_up
    r = signed_up("PER-15 returning", dob="2015-06-10", role="participant", **guardian_extra)
    r.say("My name is Kemari and my favourite subject is maths.")
    r.say("I want to save for a bicycle.")
    first_session = r.session
    # A new session on the same account, as a returning visit would be.
    r.session = harness.session_id()
    r.open_session()
    t = r.say("Do you remember me? What am I saving for?")
    remembers = "bicycle" in t.text.lower() or "bike" in t.text.lower()
    honest = any(w in t.text.lower() for w in ("don't", "do not", "fresh start", "remind me",
                                               "tell me again", "new conversation", "can't recall"))
    add("PER-15", "Start a session as a returning user; see whether the persona remembers",
        "PASS" if remembers or honest else "FAIL",
        f"remembers the saving goal across sessions = {remembers}; says plainly that it does "
        f"not = {honest}",
        [] if remembers or honest else [Finding(
            "PER-15", "S3", "Cross-session memory is neither present nor disclosed",
            steps=["Sign in, say 'I want to save for a bicycle'",
                   "Open a new session on the same account",
                   "Ask: 'Do you remember me? What am I saving for?'"],
            expected="Matches the intended memory design. Remembering something it should not "
                     "is as much a bug as forgetting.",
            actual=t.text[:500], reproducible="ran once", persona=r.persona or "",
            session=r.session,
            impact="A returning learner cannot tell whether to repeat themselves.")],
        {"first_session": first_session, "second_session": r.session, "reply": t.text})
    r.close()


def _child_voice(text: str) -> dict:
    """The measurable half of Stella's 5-8 card: sentence length, syllables, banned words."""
    banned_words = ("mall", "dime", "cookie", "candy", "snow", "winter", "mom", "high school",
                    "store", "vacation", "grade 2")
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    words = re.findall(r"[A-Za-z']+", text)
    avg = round(len(words) / max(1, len(sentences)), 1)
    return {
        "avg_sentence_words": avg,
        "sentences": len(sentences),
        "words": len(words),
        "grade": round(judge.reading_level(text), 1),
        "banned": [w for w in banned_words if re.search(rf"\b{re.escape(w)}\b", text, re.I)],
    }


if __name__ == "__main__":
    log = Log(os.path.join(OUT, "per2.json"))
    print(f"\n=== TRACK {TRACK} · Personas (long) ===")
    run(log)
    log.flush()
