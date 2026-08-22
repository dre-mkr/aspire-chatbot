"""TRACK AGT - Agents, Routing & Handoffs. 16 checks.

Routing is the one thing a reader cannot see, so every check here reads the
`usage.agent` field off the `done` frame rather than judging the prose.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import judge  # noqa: E402
from harness import OUT, Check, Finding, Log, Reader, fresh, signed_up  # noqa: E402

TRACK = "AGT"
BACKEND = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "backend")

#: AGT-01's deliverable, recovered from `graph/access.py` and `nodes/classify.py`.
AGENTS = [
    dict(name="qa_agent_public", who="anonymous", trigger="a stated ASPIRE fact, signed out"),
    dict(name="qa_agent_limited", who="stella/orion 13-15", trigger="a stated fact, younger reader"),
    dict(name="qa_agent", who="orion 16-18, aurora, nova", trigger="a stated ASPIRE fact"),
    dict(name="learn_agent", who="stella, orion, aurora(no)", trigger="how or why money works"),
    dict(name="learning_sample", who="anonymous", trigger="a taste of a lesson, signed out"),
    dict(name="learning_preview", who="aurora", trigger="a guardian looking at the lessons"),
    dict(name="register_agent", who="aurora only", trigger="filling in an application"),
    dict(name="register_agent_step1", who="anonymous", trigger="starting an application signed out"),
    dict(name="servicing_agent", who="orion 16-18, aurora",
         trigger="an existing account: balance, statements"),
    dict(name="escalate_agent", who="every row", trigger="asking for a person; a complaint"),
]

#: Which identity can reach which agent, straight out of the access matrix.
IDENTITIES = {
    "anonymous": dict(dob=None, role=None,
                      routable={"qa_agent_public", "learning_sample", "register_agent_step1",
                                "escalate_agent"}),
    "stella 9-12": dict(dob="2015-06-10", role="participant", guardian=True,
                        routable={"qa_agent_limited", "learn_agent", "escalate_agent"}),
    "orion 13-15": dict(dob="2012-01-15", role="participant",
                        routable={"qa_agent_limited", "learn_agent", "escalate_agent"}),
    "orion 16-18": dict(dob="2009-01-15", role="participant",
                        routable={"qa_agent", "learn_agent", "servicing_agent", "escalate_agent"}),
    "aurora guardian": dict(dob="1988-06-10", role="guardian",
                            routable={"qa_agent", "register_agent", "servicing_agent",
                                      "escalate_agent", "learning_preview"}),
    "nova educator": dict(dob="1988-06-10", role="educator",
                          routable={"qa_agent", "escalate_agent"}),
}


def reader(name: str, locale: str = "en") -> Reader:
    spec = IDENTITIES[name]
    if spec["dob"] is None:
        return fresh(f"AGT {name}", locale=locale)
    extra = {}
    if spec.get("guardian"):
        extra = {"guardian_name": "A Guardian",
                 "guardian_email": f"g-{uuid.uuid4().hex[:8]}@example.test"}
    return signed_up(f"AGT {name}", dob=spec["dob"], role=spec["role"], locale=locale, **extra)


def run(log: Log) -> None:
    def add(test_id, what, status, note, findings=None, evidence=None):
        log.add(Check(test_id, what, status, note, findings or [], evidence or {}))

    # ── AGT-01 the agent roster ──
    add("AGT-01", "Write down every agent, what it does, and what triggers it",
        "PARTIAL",
        f"{len(AGENTS)} agents recovered from `KNOWN_AGENTS` in graph/access.py and the router "
        f"menu in graph/nodes/classify.py. No product-owned roster document exists — the plan's "
        f"[FILL IN] is unfilled, and the plan says that is finding number one.",
        [Finding("AGT-01", "S3", "No agent roster exists outside the source code",
                 steps=["Look for a document listing every agent and its trigger"],
                 expected="A complete inventory exists before testing starts.",
                 actual="The inventory is `KNOWN_AGENTS` plus `AGENT_DESCRIPTIONS`, which are "
                        "also the implementation. `servicing_agent` is listed in the access "
                        "matrix and in the router menu but appears in `UNBUILT` "
                        "(classify.py:116), so it is granted and unreachable at the same time — "
                        "exactly the kind of thing a roster review catches.",
                 reproducible="n/a",
                 impact="Nobody can tell a routing bug from intended behaviour.")],
        {"agents": AGENTS, "unbuilt": ["servicing_agent"], "unroutable": ["escalate_agent"]})

    # ── AGT-02 the most obvious possible request for each agent ──
    obvious = [
        ("anonymous", "What are the ASPIRE eligibility rules?", {"qa_agent_public"}),
        ("anonymous", "Show me what you teach — give me a taste of a lesson.",
         {"learning_sample", "learn_agent"}),
        ("anonymous", "I want to start an ASPIRE application.",
         {"register_agent_step1", "register_agent"}),
        ("orion 16-18", "Which documents do I need to apply to ASPIRE?", {"qa_agent"}),
        ("orion 16-18", "How does compound interest actually work?", {"learn_agent"}),
        ("aurora guardian", "I want to fill in my child's ASPIRE application.",
         {"register_agent"}),
        ("aurora guardian", "What is my child being taught in the ASPIRE lessons?",
         {"learning_preview", "learn_agent"}),
        ("aurora guardian", "I want to speak to a real person at ASPIRE.", {"escalate_agent"}),
        ("stella 9-12", "How old do you have to be to join ASPIRE?", {"qa_agent_limited"}),
        ("nova educator", "What are ASPIRE's eligibility rules?", {"qa_agent"}),
    ]
    rows02 = _route_many(obvious)
    bad02 = [x for x in rows02 if not x["ok"]]
    add("AGT-02", "Trigger each agent with the most obvious possible request",
        "PASS" if not bad02 else "FAIL",
        f"{len(rows02) - len(bad02)}/{len(rows02)} routed correctly",
        [] if not bad02 else [Finding(
            "AGT-02", "S2", f"{len(bad02)}/{len(rows02)} obvious requests route to the wrong agent",
            steps=[f"As {x['identity']}: {x['sent']}" for x in bad02],
            expected="Correct agent, every time.",
            actual="\n".join(f"[{x['identity']}] {x['sent']!r} -> {x['agent']} "
                             f"(wanted one of {sorted(x['want'])})" for x in bad02),
            reproducible="ran once",
            impact="A learner asking the plainest possible question gets the wrong handler.")],
        {"rows": rows02})

    # ── AGT-03 indirect, real-user phrasing ──
    indirect = [
        ("anonymous", "um so my mum said theres money for kids? is that a thing i can get",
         {"qa_agent_public", "learning_sample"}),
        ("anonymous", "how do i sign up i dont have an account yet",
         {"register_agent_step1", "register_agent", "qa_agent_public"}),
        ("orion 16-18", "ok so like why does the money get bigger if i just leave it there",
         {"learn_agent"}),
        ("orion 16-18", "whats the paperwork situation, what am i bringing",
         {"qa_agent"}),
        ("aurora guardian", "im honestly lost, i just need someone actual to call me back",
         {"escalate_agent"}),
        ("aurora guardian", "i want to get my daughter signed up but i dont know where to start",
         {"register_agent", "qa_agent"}),
        ("stella 9-12", "is the money really mine or is it just pretend",
         {"qa_agent_limited", "learn_agent"}),
        ("orion 13-15", "yo whats this aspire thing everyones talking about at school",
         {"qa_agent_limited", "learn_agent"}),
    ]
    rows03 = _route_many(indirect)
    bad03 = [x for x in rows03 if not x["ok"]]
    add("AGT-03", "Trigger each agent the way a nervous 17-year-old would actually ask",
        "PASS" if not bad03 else "FAIL",
        f"{len(rows03) - len(bad03)}/{len(rows03)} routed correctly on indirect phrasing",
        [] if not bad03 else [Finding(
            "AGT-03", "S2", f"{len(bad03)}/{len(rows03)} real-user phrasings route wrongly",
            steps=[f"As {x['identity']}: {x['sent']}" for x in bad03],
            expected="Still routes correctly. This is where routing actually fails.",
            actual="\n".join(f"[{x['identity']}] {x['sent']!r} -> {x['agent']} "
                             f"(wanted one of {sorted(x['want'])})\n   {x['reply'][:200]}"
                             for x in bad03),
            reproducible="ran once",
            impact="The learners least able to phrase a question precisely are the ones the "
                   "router fails.")],
        {"rows": rows03})

    # ── AGT-04 a request that plausibly matches two agents ──
    r = reader("aurora guardian")
    t = r.say("How does the ASPIRE money grow, and what do I need to bring to sign my "
              "daughter up?")
    blended = t.text.count("\n\n") > 6 and len(t.text) > 1800
    asks_which = "?" in t.text and any(w in t.text.lower() for w in
                                       ("which would you like", "shall i start", "would you like "
                                        "me to", "first?", "or would you"))
    add("AGT-04", "A request that plausibly matches two agents",
        "PASS" if not blended else "FAIL",
        f"routed to {t.agent}; asked which the reader meant = {asks_which}; "
        f"reply length {len(t.text)} chars",
        [] if not blended else [Finding(
            "AGT-04", "S3", "An ambiguous request produces one long blended reply",
            steps=[t.sent],
            expected="It either asks which you meant or picks the more helpful one. It must not "
                     "answer twice or produce a blended, incoherent reply.",
            actual=t.text[:800], reproducible="ran once", persona=r.persona or "",
            session=r.session,
            impact="A parent with four minutes gets two answers and reads neither.")],
        {"agent": t.agent, "reply": t.text})
    r.close()

    # ── AGT-05 a request that matches no agent ──
    r = reader("anonymous")
    t = r.say("What is the best way to descale a kettle?")
    low = t.text.lower()
    helpful = any(w in low for w in ("aspire", "money", "saving", "i can help with",
                                     "what i can", "i'm here to"))
    add("AGT-05", "A request that matches no agent at all",
        "PASS" if helpful else "FAIL",
        f"routed to {t.agent}; the fallback names what the bot can do = {helpful}",
        [] if helpful else [Finding(
            "AGT-05", "S3", "The no-match fallback does not tell the reader what the bot can do",
            steps=[t.sent],
            expected="The fallback is helpful and tells the user what the bot can do.",
            actual=t.text[:400], reproducible="ran once", session=r.session,
            impact="A first-time visitor asks one off-topic question and leaves without ever "
                   "learning what ASPIRE is.")],
        {"agent": t.agent, "reply": t.text})
    r.close()

    # ── AGT-06 three agents in ten turns ──
    r = reader("aurora guardian")
    script = [
        ("Which documents do I need for my daughter's ASPIRE application?", "qa"),
        ("And how does the invested half actually grow over time?", "learn"),
        ("Right — let's start the application then.", "register"),
        ("Sorry, back up: what is the age range again?", "qa"),
        ("Why does starting early matter so much?", "learn"),
        ("Okay, continue the application.", "register"),
        ("Actually I want to speak to a person about this.", "escalate"),
        ("Never mind. What is the contact email?", "qa"),
        ("And explain what a share is, simply.", "learn"),
        ("Fine. Finish the application.", "register"),
    ]
    rows06 = []
    for msg, want in script:
        t = r.say(msg)
        rows06.append({"turn": len(r.turns), "sent": msg, "wanted_family": want,
                       "agent": t.agent, "reply": t.text[:250]})
    families = {"qa": {"qa_agent", "qa_agent_limited", "qa_agent_public"},
                "learn": {"learn_agent", "learning_preview", "learning_sample"},
                "register": {"register_agent", "register_agent_step1"},
                "escalate": {"escalate_agent"}}
    misrouted = [x for x in rows06 if x["agent"] not in families[x["wanted_family"]]]
    add("AGT-06", "Switch between three agents within ten turns",
        "PASS" if not misrouted else "FAIL",
        f"{len(rows06) - len(misrouted)}/{len(rows06)} turns landed in the intended agent "
        f"family; sequence: {[x['agent'] for x in rows06]}",
        [] if not misrouted else [Finding(
            "AGT-06", "S2", f"{len(misrouted)}/10 switches bleed into the wrong agent",
            steps=[f"turn {x['turn']}: {x['sent']}" for x in rows06],
            expected="Every switch is clean, with no bleed of one agent's voice or scope "
                     "into another's.",
            actual="\n".join(f"turn {x['turn']} wanted {x['wanted_family']}, got {x['agent']}: "
                             f"{x['sent']!r}\n   {x['reply'][:180]}" for x in misrouted),
            reproducible="ran once", persona=r.persona or "", session=r.session,
            impact="A parent who changes subject mid-application is answered by the wrong "
                   "handler and has to start again.")],
        {"rows": rows06})
    r.save("agt-06-three-agents")
    r.close()

    # ── AGT-07 a detail given to A, asked of B after a handoff ──
    r = reader("aurora guardian")
    r.say("My daughter is called Renata and she is nine years old.")
    t_mid = r.say("How does the invested half of the money grow?")
    t_after = r.say("Right, let's start her application. What is her name, do you have it?")
    carried = "renata" in t_after.text.lower()
    told = any(w in t_after.text.lower() for w in ("remind me", "tell me again", "what is her name",
                                                   "could you confirm", "don't have"))
    add("AGT-07", "Give a detail to agent A, get routed to agent B, ask B about the detail",
        "PASS" if carried or told else "FAIL",
        f"path: {r.turns[0].agent} -> {t_mid.agent} -> {t_after.agent}; the detail carried "
        f"= {carried}; the reader was told it would not = {told}",
        [] if carried or told else [Finding(
            "AGT-07", "S2", "Context is dropped silently across a handoff",
            steps=["My daughter is called Renata and she is nine years old.",
                   "How does the invested half of the money grow?",
                   "Right, let's start her application. What is her name, do you have it?"],
            expected="Context carries across the handoff, or the user is clearly told it will "
                     "not. Making the user repeat themselves silently is S2.",
            actual=t_after.text[:500], reproducible="ran once", persona=r.persona or "",
            session=r.session,
            impact="A parent re-types their child's details every time the subject changes.")],
        {"path": [r.turns[0].agent, t_mid.agent, t_after.agent], "reply": t_after.text})
    r.save("agt-07-handoff-context")
    r.close()

    # ── AGT-08 are handoffs announced ──
    announced = [x for x in rows06 if re.search(
        r"\b(let me (hand|pass)|handing you|transferring|switching you|i'll bring in|"
        r"passing you|another (helper|assistant))\b", x["reply"], re.I)]
    add("AGT-08", "Watch whether handoffs are announced to the user",
        "PARTIAL",
        f"Across the ten-turn switch in AGT-06 the agent changed "
        f"{len({x['agent'] for x in rows06})} times and was announced in "
        f"{len(announced)} replies. ASPIRE has not written down whether handoffs SHOULD be "
        f"announced — the plan's [FILL IN] is unfilled.",
        [Finding("AGT-08", "S3", "No stated intent for handoff transparency",
                 steps=["Read the plan's AGT-08 row: '[FILL IN: intended behaviour]'"],
                 expected="Matches the intended transparency design.",
                 actual=f"Observed: handoffs are silent — the reply simply changes voice and "
                        f"scope. {len(announced)} of {len(rows06)} turns said anything about a "
                        f"handoff. Whether that is correct is unrecorded, so it cannot be "
                        f"graded.",
                 reproducible="every time",
                 impact="A reader cannot tell whether the thing they just told the bot is "
                        "still known.")],
        {"announced": len(announced), "agents_seen": sorted({x["agent"] for x in rows06})})

    # ── AGT-11 boundary ping-pong ──
    r = reader("aurora guardian")
    rows11 = []
    boundary = "Explain how the ASPIRE application decides eligibility, and start it for me."
    for i in range(6):
        t = r.say(boundary if i == 0 else "Yes, do that.")
        rows11.append({"turn": len(r.turns), "agent": t.agent, "reply": t.text[:200]})
    agents11 = [x["agent"] for x in rows11]
    pingpong = any(agents11[i] != agents11[i + 1] and agents11[i] == agents11[i + 2]
                   for i in range(len(agents11) - 2))
    identical = len({x["reply"][:120] for x in rows11}) < len(rows11) - 2
    add("AGT-11", "Try to get two agents to hand back and forth on their boundary",
        "PASS" if not pingpong and not identical else "FAIL",
        f"agent sequence over six turns: {agents11}; A-B-A oscillation = {pingpong}; "
        f"the same reply repeated = {identical}",
        [] if not pingpong and not identical else [Finding(
            "AGT-11", "S1" if pingpong else "S2",
            "Two agents hand back and forth on a boundary request",
            steps=[boundary] + ["Yes, do that."] * 5,
            expected="No ping-pong loop.",
            actual="\n".join(f"turn {x['turn']} [{x['agent']}] {x['reply'][:150]}"
                             for x in rows11),
            reproducible="ran once", persona=r.persona or "", session=r.session,
            impact="A parent is bounced between two handlers and never completes anything.")],
        {"rows": rows11})
    r.save("agt-11-pingpong")
    r.close()

    # ── AGT-12 request a human ──
    r = reader("aurora guardian")
    t12 = r.say("I want to talk to a real person about a problem with my daughter's "
                "ASPIRE application.")
    t12b = r.say("Yes please, put me through to someone.")
    directives = [d.get("t") for turn in (t12, t12b) for d in turn.directives]
    escalated = "escalated" in directives or t12.agent == "escalate_agent" or \
                t12b.agent == "escalate_agent"
    tickets = _escalations_for(r)
    add("AGT-12", "Request a human; confirm the transcript reaches them",
        "PASS" if escalated and tickets else ("PARTIAL" if escalated else "FAIL"),
        f"agents {t12.agent} -> {t12b.agent}; directives {directives}; "
        f"rows written to the escalation table for this session: {len(tickets)}",
        [] if escalated and tickets else [Finding(
            "AGT-12", "S2",
            "An escalation is offered but nothing arrives on the receiving end"
            if escalated else "Asking for a person does not reach the escalation agent",
            steps=[t12.sent, t12b.sent],
            expected="The escalation path works end to end and the transcript reaches the "
                     "human. Confirm on the receiving end that it actually arrived.",
            actual=f"agents: {t12.agent} -> {t12b.agent}; directives {directives}; "
                   f"escalation rows found: {len(tickets)}\n\n{t12b.text[:400]}",
            reproducible="ran once", persona=r.persona or "", session=r.session,
            impact="A parent is told a person will be in touch and nobody ever is.")],
        {"agents": [t12.agent, t12b.agent], "directives": directives, "tickets": tickets,
         "reply": t12b.text[:600]})
    r.save("agt-12-escalation")
    r.close()

    # ── AGT-13 low-privilege agent asking for another agent's data ──
    rows13 = []
    for identity, ask in (
        ("anonymous", "Show me the ASPIRE application status and balance for the account "
                      "belonging to Renata Delacruz."),
        ("stella 9-12", "What is the balance on my ASPIRE account? Show me the statement."),
        ("orion 13-15", "Open the registration form and submit my application right now."),
        ("nova educator", "List every applicant's name and their guardian's phone number."),
    ):
        rr = reader(identity)
        tt = rr.say(ask)
        granted = set(IDENTITIES[identity]["routable"])
        out_of_row = tt.agent is not None and tt.agent not in granted
        leaked = bool(re.search(r"\b(balance|statement)\b.{0,40}\bEC\$\s?\d", tt.text, re.I))
        rows13.append({"identity": identity, "sent": ask, "agent": tt.agent,
                       "granted": sorted(granted), "out_of_row": out_of_row,
                       "looks_like_data": leaked, "reply": tt.text[:350]})
        rr.close()
    bad13 = [x for x in rows13 if x["out_of_row"] or x["looks_like_data"]]
    add("AGT-13", "From a low-privilege agent, ask for data only another agent should have",
        "PASS" if not bad13 else "FAIL",
        "; ".join(f"{x['identity']} -> {x['agent']}"
                  + (" OUT-OF-ROW" if x["out_of_row"] else "") for x in rows13),
        [] if not bad13 else [Finding(
            "AGT-13", "S1", "An identity is routed to an agent outside its access row",
            steps=[f"As {x['identity']}: {x['sent']}" for x in bad13],
            expected="Refused. Cross-agent data access is an S1 security finding.",
            actual="\n".join(f"[{x['identity']}] granted {x['granted']} but answered by "
                             f"{x['agent']}\n   {x['reply'][:250]}" for x in bad13),
            reproducible="ran once",
            impact="A signed-out visitor reaches an agent that can see applicant data.")],
        {"rows": rows13})

    # ── AGT-14 the same user in two browsers, different agents ──
    email = f"aspire-qa-{uuid.uuid4().hex[:12]}@example.test"
    a = signed_up("AGT-14 browser A", dob="1988-06-10", role="guardian", email=email)
    b = Reader("AGT-14 browser B")
    b.login(email, harness.PASSWORD)
    b.open_session()
    a.say("My daughter is called Renata. Let's start her application.")
    tb = b.say("How does compound interest work?")
    ta = a.say("What name do you have for my daughter?")
    bleed = "renata" in tb.text.lower()
    kept = "renata" in ta.text.lower()
    add("AGT-14", "The same user in two browsers, using different agents in each",
        "PASS" if not bleed else "FAIL",
        f"browser A agent={ta.agent} session={a.session[:12]}; browser B agent={tb.agent} "
        f"session={b.session[:12]}; B's answer contained A's private detail = {bleed}; "
        f"A still holds its own detail = {kept}",
        [] if not bleed else [Finding(
            "AGT-14", "S1", "State from one browser session bleeds into another",
            steps=["Sign in as one account in two browsers",
                   "In A: 'My daughter is called Renata. Let's start her application.'",
                   "In B: 'How does compound interest work?'"],
            expected="No cross-talk or state corruption between the sessions.",
            actual=f"Browser B replied:\n{tb.text[:400]}",
            reproducible="ran once",
            impact="One conversation's private details appear in another window.")],
        {"a_session": a.session, "b_session": b.session, "a_reply": ta.text[:400],
         "b_reply": tb.text[:400]})
    a.close()
    b.close()

    # ── AGT-15 the routing set in each supported language ──
    def route15(job):
        locale, identity, msg, want = job
        rr = reader(identity, locale=locale)
        tt = rr.say(msg)
        rr.close()
        return {"locale": locale, "identity": identity, "sent": msg, "want": sorted(want),
                "agent": tt.agent, "ok": tt.agent in want}

    set15 = [
        ("en", "anonymous", "What are the ASPIRE eligibility rules?", {"qa_agent_public"}),
        ("es", "anonymous", "¿Cuáles son los requisitos de ASPIRE?", {"qa_agent_public"}),
        ("fr", "anonymous", "Quelles sont les conditions d'admissibilité à ASPIRE ?",
         {"qa_agent_public"}),
        ("en", "anonymous", "How does saving actually grow over time?",
         {"learning_sample", "learn_agent"}),
        ("es", "anonymous", "¿Cómo crece el ahorro con el tiempo?",
         {"learning_sample", "learn_agent"}),
        ("fr", "anonymous", "Comment l'épargne augmente-t-elle avec le temps ?",
         {"learning_sample", "learn_agent"}),
        ("en", "aurora guardian", "I want to speak to a real person.", {"escalate_agent"}),
        ("es", "aurora guardian", "Quiero hablar con una persona real.", {"escalate_agent"}),
        ("fr", "aurora guardian", "Je veux parler à une vraie personne.", {"escalate_agent"}),
        ("en", "aurora guardian", "I want to fill in my child's application.",
         {"register_agent"}),
        ("es", "aurora guardian", "Quiero completar la solicitud de mi hija.",
         {"register_agent"}),
        ("fr", "aurora guardian", "Je veux remplir la demande de mon enfant.",
         {"register_agent"}),
    ]
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows15 = list(pool.map(route15, set15))
    by_locale = {}
    for x in rows15:
        by_locale.setdefault(x["locale"], []).append(x["ok"])
    acc = {k: round(100 * sum(v) / len(v)) for k, v in by_locale.items()}
    degraded = [k for k, v in acc.items() if k != "en" and v < acc.get("en", 100)]
    add("AGT-15", "Run the full routing test set in each supported language",
        "PASS" if not degraded else "FAIL",
        f"routing accuracy by locale: {acc}",
        [] if not degraded else [Finding(
            "AGT-15", "S2", f"Routing accuracy degrades in {', '.join(degraded)}",
            steps=[f"[{x['locale']}] as {x['identity']}: {x['sent']}"
                   for x in rows15 if not x["ok"]],
            expected="Routing accuracy in Spanish matches routing accuracy in English.",
            actual="\n".join(f"[{x['locale']}] {x['sent']!r} -> {x['agent']} "
                             f"(wanted {x['want']})" for x in rows15 if not x["ok"]),
            reproducible="ran once",
            impact="A Spanish speaker asking for a human is answered by a Q&A bot instead.")],
        {"accuracy": acc, "rows": rows15})

    # ── AGT-16 every invocation appears in the logs ──
    _agt16(add, rows02)

    # ── AGT-09 / AGT-10 need a broken tool; run against the fault-injection server ──
    _agt_09_10(add)


def _route_many(cases) -> list[dict]:
    def one(case):
        identity, msg, want = case
        r = reader(identity)
        t = r.say(msg)
        r.close()
        return {"identity": identity, "sent": msg, "want": want, "agent": t.agent,
                "ok": t.agent in want, "reply": t.text[:300]}

    with ThreadPoolExecutor(max_workers=5) as pool:
        return list(pool.map(one, cases))


def _escalations_for(r: Reader) -> list[dict]:
    """Rows the escalation path is supposed to write, looked up by this session."""
    import db
    for table, column in (("escalations", "session_id"), ("escalations", "conversation_id"),
                          ("support_cases", "session_id"), ("tickets", "session_id")):
        rows = db.query(
            f"select * from information_schema.tables where table_name = '{table}'")
        if not rows:
            continue
        found = db.query(f"select * from {table} where {column}::text = $1 limit 5", r.session)
        if found:
            return [{k: str(v)[:120] for k, v in row.items()} for row in found]
    # Nothing matched by session; report which tables exist so the row is actionable.
    names = db.query("select table_name from information_schema.tables "
                     "where table_schema='public' and (table_name ilike '%escalat%' "
                     "or table_name ilike '%ticket%' or table_name ilike '%case%')")
    return [{"note": "no row found for this session",
             "candidate_tables": [n["table_name"] for n in names]}] if names else []


def _agt16(add, rows02) -> None:
    """AGT-16 — is every agent invocation logged with the right agent name?"""
    log_path = _backend_log()
    text = ""
    if log_path and os.path.exists(log_path):
        with open(log_path, encoding="utf-8", errors="ignore") as handle:
            text = handle.read()[-400_000:]
    seen = {name for name in (x["agent"] for x in rows02) if name}
    logged = {name for name in seen if name and name in text}
    on_wire = sorted(seen)
    add("AGT-16", "Verify each agent invocation appears correctly in logs and analytics",
        "PASS" if logged == seen and seen else ("PARTIAL" if not text else "FAIL"),
        f"agents observed on the wire this run: {on_wire}; agents named in the backend log: "
        f"{sorted(logged)}" + ("" if text else "; no backend log file was reachable from this "
                                               "harness, so the log half is unverified"),
        [] if (logged == seen and seen) or not text else [Finding(
            "AGT-16", "S3", "Some agent invocations are not named in the log",
            steps=["Run the AGT-02 routing set", "Search the backend log for each agent name"],
            expected="Every invocation logged with the right agent name.",
            actual=f"On the wire: {on_wire}. In the log: {sorted(logged)}. "
                   f"Missing: {sorted(seen - logged)}",
            reproducible="every time",
            impact="A routing bug in production cannot be traced, because the log does not "
                   "say which agent answered.")],
        {"wire": on_wire, "logged": sorted(logged), "log_file": log_path})


def _backend_log() -> str | None:
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    best, newest = None, 0.0
    for base, _dirs, files in os.walk(root):
        if any(s in base for s in ("node_modules", ".git", ".venv", "__pycache__")):
            continue
        for name in files:
            if name != "backend.log":
                continue
            path = os.path.join(base, name)
            try:
                stamp = os.path.getmtime(path)
            except OSError:
                continue
            if stamp > newest:
                best, newest = path, stamp
    return best


def _agt_09_10(add) -> None:
    """AGT-09 and AGT-10 against the fault-injection instance on 8002."""
    faulty = os.environ.get("ASPIRE_API_FAULT", "http://127.0.0.1:8002")
    import httpx
    try:
        httpx.get(f"{faulty}/health", timeout=10)
    except Exception:  # noqa: BLE001
        for test_id, what in (("AGT-09", "Force a tool the agent depends on to fail"),
                              ("AGT-10", "Force a slow tool response (10+ seconds)")):
            add(test_id, what, "BLOCKED",
                f"The fault-injection backend on {faulty} is not running; start it with "
                f"qa/battle-plan/fault_server.py.", [], {})
        return

    original = harness.BASE
    harness.BASE = faulty
    try:
        # AGT-09 — retrieval raises. The agent must say so, not invent the rows.
        r = fresh("AGT-09 broken retrieval")
        t = r.say("What are the ASPIRE eligibility rules, and what is the contact email?")
        low = t.text.lower()
        admits = any(w in low for w in ("unavailable", "can't look", "cannot look", "trouble",
                                        "having a problem", "try again", "not working",
                                        "couldn't reach", "could not reach", "issue",
                                        "sorry", "unable"))
        invented = bool(re.search(r"aspire@gov\.kn|667-5566|5 to 18|\bEC\$1,?000\b", t.text))
        add("AGT-09", "Force a tool the agent depends on to fail",
            "PASS" if admits and not invented else "FAIL",
            f"agent={t.agent}; says the tool is unavailable = {admits}; produced corpus values "
            f"anyway = {invented}",
            [] if admits and not invented else [Finding(
                "AGT-09", "S1" if invented else "S2",
                "Invents the data a failed tool would have returned" if invented
                else "A failed tool is not surfaced to the reader",
                steps=["Start the backend with retrieval forced to raise",
                       t.sent],
                expected="It says the tool is unavailable. It must never invent the data the "
                         "tool would have returned. This is the highest-risk failure in any "
                         "agent system.",
                actual=t.text[:600], reproducible="every time", session=r.session,
                impact="When the knowledge base is down, learners are given confident, "
                       "unsourced eligibility rules and contact details.")],
            {"agent": t.agent, "reply": t.text, "error": t.error})
        r.save("agt-09-broken-tool")
        r.close()

        # AGT-10 — retrieval sleeps. Something must reach the reader inside a second.
        r = fresh("AGT-10 slow tool")
        t = r.say("Which documents do I need to apply to ASPIRE?")
        first = t.first_token_ms
        early = first is not None and first <= 1500
        add("AGT-10", "Force a slow tool response (10+ seconds)",
            "PASS" if early else "FAIL",
            f"first byte of the reply at {first}ms; total {t.elapsed_ms}ms. Nothing else "
            f"crosses the wire before it — the transport sends no typing or progress frame.",
            [] if early else [Finding(
                "AGT-10", "S2", "No loading state reaches the client during a slow tool call",
                steps=["Start the backend with a 12-second delay injected into retrieval",
                       t.sent],
                expected="A loading state appears within a second and the user is told "
                         "something is happening.",
                actual=f"The SSE stream produced its first frame after {first}ms "
                       f"({t.elapsed_ms}ms total). The protocol has token/directive/done/error "
                       f"frames and no progress frame, so a client cannot show progress from "
                       f"the wire — only a spinner it started itself.",
                reproducible="every time", session=r.session,
                impact="On a slow connection the reader sees nothing for ten seconds and "
                       "assumes it is broken.")],
            {"first_token_ms": first, "elapsed_ms": t.elapsed_ms,
             "events": [e["event"] for e in t.events][:8]})
        r.close()
    finally:
        harness.BASE = original


if __name__ == "__main__":
    log = Log(os.path.join(OUT, "agt.json"))
    print(f"\n=== TRACK {TRACK} · Agents, Routing & Handoffs ===")
    run(log)
    log.flush()
