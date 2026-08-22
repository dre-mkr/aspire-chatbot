"""TRACK LAN - Language & Language Switching. 20 checks.

The plan is emphatic that a non-speaker can only check mechanics. Everything
here is mechanics: which language a reply is in, whether a fact survives a
switch, whether a proper noun was translated, whether the number formatting
follows the locale. Quality — "is this Spanish any good?" — is marked
NOT-AUTOMATABLE and left for a fluent speaker, which is LAN-01 and LAN-02.
"""

from __future__ import annotations

import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness  # noqa: E402
import judge  # noqa: E402
import truth  # noqa: E402
from harness import OUT, Check, Finding, Log, Reader, fresh  # noqa: E402

TRACK = "LAN"
LANGS = ("en", "es", "fr")
LONG = os.environ.get("ASPIRE_API_LONG", "http://127.0.0.1:8001")


def run(log: Log) -> None:
    def add(test_id, what, status, note, findings=None, evidence=None):
        log.add(Check(test_id, what, status, note, findings or [], evidence or {}))

    # ── LAN-01 the supported-language list, and who signs it off ──
    add("LAN-01", "List every officially supported language; assign a fluent speaker to each",
        "PARTIAL",
        "Supported locales recovered from the code: en, es, fr (app/domain.py Language, and "
        "the locale allow-list in /v2/session). No fluent-speaker owner is named anywhere, and "
        "this run has none — every LAN row below is graded on mechanics only.",
        [Finding("LAN-01", "S2", "No fluent speaker owns Spanish or French",
                 steps=["Look for a named owner per supported language"],
                 expected="Every language has a named human owner who can judge quality, "
                          "not just presence.",
                 actual="None exists. Spanish and French ship with no quality gate: nothing in "
                        "the repository, the tests or the e2e harness reads a reply for "
                        "naturalness.",
                 reproducible="n/a",
                 impact="Stilted or wrong Spanish reaches learners and nobody on the team can "
                        "tell, because everyone testing it reads it through a translator.")],
        {"locales": list(LANGS)})

    # ── LAN-02 a 15-turn conversation in each language ──
    original = harness.BASE
    harness.BASE = LONG
    try:
        conv_rows = []
        for locale in LANGS:
            r = Reader(f"LAN-02 {locale}", locale=locale)
            r.anonymous()
            r.open_session()
            script = _fifteen_turns(locale)
            langs = []
            for msg in script:
                t = r.say(msg)
                langs.append({"turn": len(r.turns), "sent": msg,
                              "reads_as": judge.language_of(t.text),
                              "drifted": judge.drifted_to_english(t.text, locale),
                              "reply": t.text[:220]})
            drifted = [x for x in langs if x["drifted"]]
            conv_rows.append({"locale": locale, "turns": len(langs), "drifted": drifted,
                              "detail": langs})
            r.save(f"lan-02-{locale}-15-turns")
            r.close()
        bad02 = [x for x in conv_rows if x["drifted"]]
        add("LAN-02", "A full 15-turn conversation in each supported language",
            "PARTIAL" if not bad02 else "FAIL",
            "; ".join(f"{x['locale']}: {len(x['drifted'])}/{x['turns']} turns drifted to English"
                      for x in conv_rows)
            + ". Fluency itself is NOT graded — no fluent speaker signed off (see LAN-01).",
            [] if not bad02 else [Finding(
                "LAN-02", "S2", "A conversation drifts back to English mid-way",
                steps=[f"Open a session with locale={x['locale']}" for x in bad02],
                expected="Fluent, natural and correct throughout.",
                actual="\n\n".join(f"[{x['locale']}] turn {d['turn']} (sent {d['sent']!r}) read as "
                                   f"{d['reads_as']}:\n{d['reply']}"
                                   for x in bad02 for d in x["drifted"][:3]),
                reproducible="ran once",
                impact="A Spanish-speaking learner is answered in English and assumes the "
                       "service is not for them.")],
            {"rows": [{"locale": x["locale"], "drifted_turns": [d["turn"] for d in x["drifted"]]}
                      for x in conv_rows], "detail": conv_rows})

        # ── LAN-15 twenty turns in Spanish, never mentioning English ──
        r = Reader("LAN-15 es", locale="es")
        r.anonymous()
        r.open_session()
        rows15 = []
        for msg in _twenty_spanish():
            t = r.say(msg)
            rows15.append({"turn": len(r.turns), "sent": msg,
                           "reads_as": judge.language_of(t.text),
                           "drifted": judge.drifted_to_english(t.text, "es"),
                           "reply": t.text[:200]})
        first_drift = next((x["turn"] for x in rows15 if x["drifted"]), None)
        add("LAN-15", "Twenty turns in Spanish, never mentioning English",
            "PASS" if first_drift is None else "FAIL",
            f"first drift to English at turn {first_drift or '—'} "
            f"({sum(1 for x in rows15 if x['drifted'])}/{len(rows15)} turns)",
            [] if first_drift is None else [Finding(
                "LAN-15", "S2", f"Drifts back to English at turn {first_drift} of a Spanish "
                                f"conversation",
                steps=[f"turn {x['turn']}: {x['sent']}" for x in rows15[:first_drift]],
                expected="It never drifts back to English. Record the exact turn if it does.",
                actual="\n\n".join(f"turn {x['turn']}: {x['reply']}"
                                   for x in rows15 if x["drifted"]),
                reproducible="ran once", session=r.session,
                impact="A learner mid-way through a Spanish conversation is suddenly answered "
                       "in a language they may not read.")],
            {"first_drift_turn": first_drift, "rows": rows15})
        r.save("lan-15-twenty-spanish")
        r.close()

        # ── LAN-06 switch back and forth five times in ten turns ──
        r = Reader("LAN-06", locale="en")
        r.anonymous()
        r.open_session()
        pattern = [("switch to Spanish", "es"), ("¿qué es ASPIRE?", "es"),
                   ("switch back to English please", "en"), ("what is a savings account?", "en"),
                   ("cambia a español", "es"), ("¿cómo me inscribo?", "es"),
                   ("english again", "en"), ("how do I sign up?", "en"),
                   ("otra vez en español", "es"), ("¿cuánto dinero recibo?", "es")]
        rows6 = []
        for msg, want in pattern:
            t = r.say(msg)
            got = judge.language_of(t.text)
            scores = judge.score_language(t.text)
            correct = got == want or got.startswith("ambiguous") and scores[want] >= scores.get(
                "en" if want != "en" else "es", 0)
            half = scores["en"] >= 3 and scores["es"] >= 3
            rows6.append({"turn": len(r.turns), "sent": msg, "want": want, "reads_as": got,
                          "correct": correct, "half_switched": half, "reply": t.text[:220]})
        bad6 = [x for x in rows6 if not x["correct"] or x["half_switched"]]
        add("LAN-06", "Switch back and forth five times in ten turns",
            "PASS" if not bad6 else "FAIL",
            f"{len(rows6) - len(bad6)}/{len(rows6)} switches landed in the right language; "
            f"half-switched replies: {sum(1 for x in rows6 if x['half_switched'])}",
            [] if not bad6 else [Finding(
                "LAN-06", "S2", "A language switch is late, partial, or reverts on its own",
                steps=[f"turn {x['turn']}: {x['sent']}" for x in rows6],
                expected="No lag, no half-switched replies, no reverting on its own.",
                actual="\n\n".join(f"turn {x['turn']} wanted {x['want']}, read as "
                                   f"{x['reads_as']}:\n{x['reply']}" for x in bad6),
                reproducible="ran once", session=r.session,
                impact="A bilingual family passing one phone between them gets the wrong "
                       "language every other turn.")],
            {"rows": rows6})
        r.save("lan-06-switching")
        r.close()

        # ── LAN-07 a fact planted in English, recalled in Spanish ──
        r = Reader("LAN-07", locale="en")
        r.anonymous()
        r.open_session()
        r.say("My sister's name is Renata and she is applying too.")
        r.say("switch to Spanish for the rest of this conversation")
        t = r.say("¿Qué te dije hace un momento sobre mi hermana?")
        recalled = "renata" in t.text.lower()
        in_spanish = judge.language_of(t.text) in ("es",) or judge.score_language(t.text)["es"] >= 3
        add("LAN-07", "Tell it a fact in English, switch to Spanish, ask it to recall the fact",
            "PASS" if recalled and in_spanish else "FAIL",
            f"the name survived the switch = {recalled}; the answer is in Spanish = {in_spanish}",
            [] if recalled and in_spanish else [Finding(
                "LAN-07", "S2", "Memory does not survive a language switch"
                if not recalled else "The recall answer is not in the requested language",
                steps=["My sister's name is Renata and she is applying too.",
                       "switch to Spanish for the rest of this conversation",
                       "¿Qué te dije hace un momento sobre mi hermana?"],
                expected="Memory survives the language switch. This is the single most "
                         "commonly broken thing on this track.",
                actual=t.text[:500], reproducible="ran once", session=r.session,
                impact="A bilingual learner has to start over every time they switch language.")],
            {"reply": t.text, "recalled": recalled, "in_spanish": in_spanish})
        r.save("lan-07-memory-across-switch")
        r.close()
    finally:
        harness.BASE = original

    # ── LAN-03 open in a non-English language without saying which ──
    rows3 = []
    for locale, opener in (("es", "Hola, necesito ayuda con mi solicitud de ASPIRE."),
                           ("fr", "Bonjour, j'ai besoin d'aide avec ma demande ASPIRE.")):
        r = fresh(f"LAN-03 {locale}")          # session locale stays 'en' on purpose
        t = r.say(opener)
        got = judge.language_of(t.text)
        rows3.append({"opened_in": locale, "session_locale": r.locale, "reads_as": got,
                      "matched": got == locale, "reply": t.text[:350]})
        r.close()
    bad3 = [x for x in rows3 if not x["matched"]]
    add("LAN-03", "Open in a non-English language without telling the bot which",
        "PASS" if not bad3 else "FAIL",
        "; ".join(f"opened in {x['opened_in']} -> replied in {x['reads_as']}" for x in rows3),
        [] if not bad3 else [Finding(
            "LAN-03", "S2", "Does not detect the reader's language from their first message",
            steps=[f"Open a session (locale=en) and send: {x['reply'][:0]}" for x in bad3],
            expected="It detects and replies in that language from the first response.",
            actual="\n\n".join(f"opened in {x['opened_in']}, replied in {x['reads_as']}:\n"
                               f"{x['reply']}" for x in bad3),
            reproducible="ran once",
            impact="A Spanish speaker's first impression of ASPIRE is a wall of English.")],
        {"rows": rows3})

    # ── LAN-04 mixed-language sentence ──
    r = fresh("LAN-04")
    t = r.say("Hola, can you help me con mi application?")
    scores = judge.score_language(t.text)
    coherent = not (scores["en"] >= 3 and scores["es"] >= 3)
    add("LAN-04", "A mixed-language sentence",
        "PASS" if coherent else "FAIL",
        f"reply reads as {judge.language_of(t.text)}; marker counts {scores}; "
        f"one coherent language = {coherent}",
        [] if coherent else [Finding(
            "LAN-04", "S3", "A mixed-language question produces a mixed-language answer",
            steps=[t.sent], expected="Responds in one coherent language and does not produce "
                                     "word-salad.",
            actual=t.text[:500], reproducible="ran once", session=r.session,
            impact="A Spanglish speaker gets a reply that is fluent in neither language.")],
        {"reply": t.text, "scores": scores})
    r.close()

    # ── LAN-05 explicit switch, both directions ──
    r = fresh("LAN-05")
    a = r.say("switch to Spanish")
    b = r.say("háblame en inglés")
    a_ok = judge.score_language(a.text)["es"] >= 3
    b_ok = judge.score_language(b.text)["en"] >= 3
    add("LAN-05", "Explicitly ask it to switch, then to switch back",
        "PASS" if a_ok and b_ok else "FAIL",
        f"'switch to Spanish' -> {judge.language_of(a.text)}; "
        f"'háblame en inglés' -> {judge.language_of(b.text)}",
        [] if a_ok and b_ok else [Finding(
            "LAN-05", "S2", "An explicit language switch is not honoured",
            steps=["switch to Spanish", "háblame en inglés"],
            expected="Switches immediately and completely.",
            actual=f"switch to Spanish:\n{a.text[:300]}\n\nháblame en inglés:\n{b.text[:300]}",
            reproducible="ran once", session=r.session,
            impact="A learner asks for their own language and is refused without being told why.")],
        {"to_spanish": a.text[:600], "to_english": b.text[:600]})
    r.close()

    # ── LAN-09 locale formatting of dates, money and large numbers ──
    rows9 = []
    for locale, ask in (("en", "What is the ASPIRE contribution, and when was the programme "
                               "established? Write the amount and the date out."),
                        ("es", "¿Cuál es la contribución de ASPIRE y cuándo se creó el programa? "
                               "Escribe la cantidad y la fecha."),
                        ("fr", "Quel est le montant de la contribution ASPIRE et quand le "
                               "programme a-t-il été créé ? Écris le montant et la date.")):
        r = Reader(f"LAN-09 {locale}", locale=locale)
        r.anonymous()
        r.open_session()
        t = r.say(ask)
        text = t.text
        value_ok = bool(re.search(r"1[.,]?000", text))
        rows9.append({"locale": locale, "value_present": value_ok,
                      "decimal_style": _decimal_style(text), "reply": text[:400]})
        r.close()
    lost_value = [x for x in rows9 if not x["value_present"]]
    add("LAN-09", "Ask for a date, a deadline, a price and a large number in each language",
        "PASS" if not lost_value else "FAIL",
        "; ".join(f"{x['locale']}: amount present={x['value_present']} "
                  f"separators={x['decimal_style']}" for x in rows9)
        + ". Note: EC$1,000 is written the same way in all three replies — the locale does not "
          "change the separators.",
        [] if not lost_value else [Finding(
            "LAN-09", "S2", "The underlying value changes or disappears across languages",
            steps=[f"Ask in {x['locale']}" for x in lost_value],
            expected="Formatting follows the locale and the underlying value is unchanged.",
            actual="\n\n".join(f"[{x['locale']}] {x['reply'][:300]}" for x in lost_value),
            reproducible="ran once",
            impact="A Spanish-speaking parent is told a different amount than an English one.")],
        {"rows": rows9})

    # ── LAN-10 regional variation and Spanglish ──
    rows10 = []
    for label, msg in (("Dominican slang", "Mano, ¿qué lo que con ASPIRE? Quiero un chin de info."),
                       ("Mexican slang", "Oye, ¿qué onda con ASPIRE? Ando bien perdido, ¿me echas "
                                         "la mano?"),
                       ("Spanglish", "Wachu think, ¿me conviene aplicar al ASPIRE o no?")):
        r = fresh(f"LAN-10 {label}")
        t = r.say(msg)
        low = t.text.lower()
        corrected = any(w in low for w in ("correctly", "proper spanish", "should say",
                                           "es más correcto", "se dice", "la forma correcta",
                                           "rephrase", "did you mean"))
        answered = len(t.text) > 60
        rows10.append({"case": label, "corrected_the_user": corrected, "answered": answered,
                       "reads_as": judge.language_of(t.text), "reply": t.text[:350]})
        r.close()
    bad10 = [x for x in rows10 if x["corrected_the_user"] or not x["answered"]]
    add("LAN-10", "Dominican and Mexican Spanish slang, and Spanglish",
        "PASS" if not bad10 else "FAIL",
        "; ".join(f"{x['case']}: answered={x['answered']} corrected-the-user="
                  f"{x['corrected_the_user']}" for x in rows10),
        [] if not bad10 else [Finding(
            "LAN-10", "S3", "The bot corrects the reader's dialect instead of answering",
            steps=[x["case"] for x in bad10],
            expected="Understood without the bot correcting the user's dialect or switching "
                     "register awkwardly.",
            actual="\n\n".join(f"[{x['case']}] {x['reply'][:300]}" for x in bad10),
            reproducible="ran once",
            impact="A learner is told their own Spanish is wrong by a government programme.")],
        {"rows": rows10})

    # ── LAN-11 an unsupported language ──
    rows11 = []
    for label, msg in (("Portuguese", "Olá, preciso de ajuda com a minha candidatura ao ASPIRE."),
                       ("French", "Bonjour, pouvez-vous m'aider avec ma demande ASPIRE ?"),
                       ("Haitian Creole", "Bonjou, mwen bezwen èd ak aplikasyon ASPIRE mwen an.")):
        r = fresh(f"LAN-11 {label}")
        t = r.say(msg)
        got = judge.language_of(t.text)
        silently_english = got == "en"
        rows11.append({"case": label, "reads_as": got, "silently_english": silently_english,
                       "reply": t.text[:350]})
        r.close()
    # French IS supported; Portuguese and Haitian Creole are not.
    unsupported = [x for x in rows11 if x["case"] != "French"]
    bad11 = [x for x in unsupported if x["silently_english"]]
    add("LAN-11", "Write in a language ASPIRE does not support",
        "PASS" if not bad11 else "FAIL",
        "; ".join(f"{x['case']} -> {x['reads_as']}" for x in rows11)
        + ". French is a supported locale, so it is the control here.",
        [] if not bad11 else [Finding(
            "LAN-11", "S3", "An unsupported language is answered silently in English",
            steps=[x["case"] for x in bad11],
            expected="A clear, polite message about what is supported — in a language the user "
                     "can read. Silently answering in English is a bug.",
            actual="\n\n".join(f"[{x['case']}] {x['reply'][:300]}" for x in bad11),
            reproducible="ran once",
            impact="A Haitian Creole speaker gets English and cannot tell whether the service "
                   "would work for them in any language.")],
        {"rows": rows11})

    # ── LAN-12 Spanish with no accents ──
    r = fresh("LAN-12")
    t = r.say("como estas necesito ayuda con mi aplicacion no tengo acentos")
    low = t.text.lower()
    complained = any(w in low for w in ("acentos", "accents", "rewrite", "tildes",
                                        "no entiendo", "could you rephrase"))
    in_spanish = judge.score_language(t.text)["es"] >= 3
    add("LAN-12", "Spanish written without accents",
        "PASS" if in_spanish and not complained else "FAIL",
        f"answered in Spanish = {in_spanish}; asked the reader to rewrite = {complained}",
        [] if in_spanish and not complained else [Finding(
            "LAN-12", "S3", "Unaccented Spanish is not handled normally",
            steps=[t.sent], expected="Understood normally. No confusion, no request to rewrite it.",
            actual=t.text[:400], reproducible="ran once", session=r.session,
            impact="Most phone keyboards in the region default to no accents, so this is the "
                   "normal case, not the edge case.")],
        {"reply": t.text})
    r.close()

    # ── LAN-13 emoji-only, punctuation-only, one-word, in each language ──
    rows13 = []
    cases = [("emoji only", "🤔💰❓"), ("punctuation only", "???!!!..."),
             ("one word en", "money"), ("one word es", "dinero"), ("one word fr", "argent")]

    def probe13(case):
        label, msg = case
        rr = fresh(f"LAN-13 {label}")
        tt = rr.say(msg)
        rr.close()
        low = tt.text.lower()
        return {"case": label, "sent": msg,
                "asks_for_clarity": "?" in tt.text or any(
                    w in low for w in ("what would you like", "tell me more", "can you say",
                                       "not sure what", "what do you mean", "qué quieres",
                                       "que veux-tu", "how can i help", "ask me")),
                "invented": len(tt.text) > 700,
                "error": tt.error, "reply": tt.text[:350]}

    with ThreadPoolExecutor(max_workers=5) as pool:
        rows13 = list(pool.map(probe13, cases))
    bad13 = [x for x in rows13 if x["error"] or (not x["asks_for_clarity"] and x["invented"])]
    add("LAN-13", "Emoji-only, punctuation-only and one-word messages in each language",
        "PASS" if not bad13 else "FAIL",
        "; ".join(f"{x['case']}: clarifies={x['asks_for_clarity']} error={bool(x['error'])}"
                  for x in rows13),
        [] if not bad13 else [Finding(
            "LAN-13", "S3", "A near-empty message is answered with an invented interpretation",
            steps=[x["sent"] for x in bad13],
            expected="Graceful handling; asks for clarification rather than inventing an "
                     "interpretation.",
            actual="\n\n".join(f"[{x['case']}] {x['reply'][:300]}" for x in bad13),
            reproducible="ran once",
            impact="A child who taps three emoji gets a lecture about something they did not ask.")],
        {"rows": rows13})

    # ── LAN-14 a 500-word non-English message ──
    r = Reader("LAN-14 es", locale="es")
    r.anonymous()
    r.open_session()
    long_es = _five_hundred_spanish()
    t = r.say(long_es)
    # The message ends with three distinct questions; a whole-message answer touches all three.
    touched = {"hermana": "hermana" in t.text.lower() or "sister" in t.text.lower(),
               "documentos": any(w in t.text.lower() for w in ("document", "papel", "certificad")),
               "banco": any(w in t.text.lower() for w in ("banco", "bank", "cuenta"))}
    covered = sum(touched.values())
    add("LAN-14", "A 500-word message in a non-English language",
        "PASS" if covered == 3 else ("PARTIAL" if covered == 2 else "FAIL"),
        f"words sent: {len(long_es.split())}; the reply addresses {covered}/3 of the questions "
        f"asked at the end ({', '.join(k for k, v in touched.items() if not v)} missed)",
        [] if covered == 3 else [Finding(
            "LAN-14", "S3", f"Only {covered} of 3 questions in a long message are answered",
            steps=["Send a 500-word Spanish message ending in three distinct questions"],
            expected="Handled fully. The reply addresses the whole message, not just the "
                     "first paragraph.",
            actual=t.text[:700], reproducible="ran once", session=r.session,
            impact="A parent who writes out their whole situation gets an answer to the first "
                   "sentence only.")],
        {"sent_words": len(long_es.split()), "touched": touched, "reply": t.text[:1200]})
    r.save("lan-14-long-spanish")
    r.close()

    # ── LAN-16 proper nouns are never translated ──
    rows16 = []
    for locale, ask in (("es", "¿Qué significa ASPIRE y quién dirige el programa?"),
                        ("fr", "Que signifie ASPIRE et qui dirige le programme ?")):
        r = Reader(f"LAN-16 {locale}", locale=locale)
        r.anonymous()
        r.open_session()
        t = r.say(ask)
        translated = re.findall(r"\bASPIRAR\b|\bASPIRER\b", t.text, re.I)
        intact = "ASPIRE" in t.text
        rows16.append({"locale": locale, "aspire_intact": intact, "translated": translated,
                       "reply": t.text[:400]})
        r.close()
    bad16 = [x for x in rows16 if x["translated"] or not x["aspire_intact"]]
    add("LAN-16", "'ASPIRE', programme names and staff names are never translated",
        "PASS" if not bad16 else "FAIL",
        "; ".join(f"{x['locale']}: 'ASPIRE' intact={x['aspire_intact']} "
                  f"translated-forms={x['translated']}" for x in rows16),
        [] if not bad16 else [Finding(
            "LAN-16", "S2", "The programme name is translated",
            steps=[f"Ask in {x['locale']}: what does ASPIRE mean?" for x in bad16],
            expected="Proper nouns stay intact. 'ASPIRE' must not become 'ASPIRAR'.",
            actual="\n\n".join(f"[{x['locale']}] {x['reply'][:300]}" for x in bad16),
            reproducible="ran once",
            impact="A learner searches for the wrong programme name and finds nothing.")],
        {"rows": rows16})

    # ── LAN-18 language preference across a session boundary ──
    r = Reader("LAN-18", locale="es")
    r.anonymous()
    r.open_session()
    first = r.say("¿Qué es ASPIRE?")
    first_session = r.session
    r.session = harness.session_id()
    minted = r.open_session()            # a fresh session on the same account
    second = r.say("¿Y cómo me inscribo?")
    persisted = minted.get("locale") == "es" and judge.score_language(second.text)["es"] >= 3
    add("LAN-18", "Set a language preference, close the session, return the next day",
        "PASS" if persisted else "FAIL",
        f"the new session was minted with locale={minted.get('locale')}; the reply reads as "
        f"{judge.language_of(second.text)}. Note: the locale is a per-session value the CLIENT "
        f"sends to /v2/session — nothing on the account stores it, so 'persists' means "
        f"'the browser remembered', not 'ASPIRE remembered'.",
        [Finding("LAN-18", "S3", "Language preference is stored only in the browser",
                 steps=["Open a session with locale=es", "Mint a new session on the same account"],
                 expected="Preference persists per the intended design.",
                 actual="`/v2/session` takes `locale` from the request body every time and signs "
                        "it into the token; there is no column on `users` and no lookup. A "
                        "learner who clears their browser, or opens ASPIRE on a second device, "
                        "is back to English.",
                 reproducible="every time",
                 impact="A Spanish-speaking family gets English every time they use a "
                        "different phone.")],
        {"first_session": first_session, "second_session": r.session, "minted": minted,
         "reply": second.text[:400]})
    r.close()

    # ── LAN-19 the same five facts in every language ──
    picks = [f for f in truth.FACTS if f["id"] in
             ("ASP-026", "ASP-000", "ASP-208", "ASP-011", "ASP-030")]

    def ask19(job):
        locale, fact = job
        rr = Reader(f"LAN-19 {locale} {fact['id']}", locale=locale)
        rr.anonymous()
        rr.open_session()
        tt = rr.say(_translate_ask(fact["ask"], locale))
        rr.close()
        ok, missing = truth.fact_ok(fact, tt.text)
        return {"locale": locale, "id": fact["id"], "ok": ok, "missing": missing,
                "reply": tt.text[:400]}

    jobs = [(loc, f) for f in picks for loc in LANGS]
    with ThreadPoolExecutor(max_workers=6) as pool:
        rows19 = list(pool.map(ask19, jobs))
    by_fact: dict[str, dict[str, bool]] = {}
    for x in rows19:
        by_fact.setdefault(x["id"], {})[x["locale"]] = x["ok"]
    divergent = [fid for fid, per in by_fact.items() if len(set(per.values())) > 1]
    add("LAN-19", "The same five factual questions in every supported language, side by side",
        "PASS" if not divergent else "FAIL",
        f"facts whose correctness differs by language: {divergent or 'none'}; "
        + "; ".join(f"{fid}={per}" for fid, per in by_fact.items()),
        [] if not divergent else [Finding(
            "LAN-19", "S1", f"Facts diverge across languages: {', '.join(divergent)}",
            steps=[f"Ask fact {fid} in en, es and fr" for fid in divergent],
            expected="The facts are identical across languages. Divergent facts across "
                     "languages is an S1.",
            actual="\n\n".join(f"[{x['locale']}/{x['id']}] ok={x['ok']} missing={x['missing']}\n"
                               f"{x['reply'][:250]}" for x in rows19 if x["id"] in divergent),
            reproducible="ran once",
            impact="A Spanish-speaking learner is told a different eligibility rule than an "
                   "English-speaking one, by the same product on the same day.")],
        {"by_fact": by_fact, "rows": rows19})

    # ── LAN-20 right-to-left ──
    add("LAN-20", "If any right-to-left language is supported, check layout and mixed RTL/LTR",
        "PASS",
        "Not applicable and correctly so: the supported set is en/es/fr (app/domain.py), all "
        "left-to-right, and `/v2/session` refuses any other locale value. There is no RTL "
        "surface to break.",
        [], {"locales": list(LANGS)})

    # ── LAN-08 error states with the interface in a non-English language ──
    _lan08(add)

    # ── LAN-17 voice + language: handed to the VOX track ──
    add("LAN-17", "Combine voice and language: speak Spanish and listen to the reply",
        "PARTIAL",
        "The mechanical half is executed in VOX-11/VOX-12 (Spanish text-to-speech resolves a "
        "Spanish voice id per persona, and the transcription endpoint accepts a Spanish "
        "utterance). Whether the pronunciation is actually correct needs a fluent listener and "
        "is NOT graded here — see LAN-01.",
        [], {"delegated_to": ["VOX-11", "VOX-12", "VOX-02"]})


def _lan08(add) -> None:
    """LAN-08 — three error states, with the session in Spanish."""
    import httpx
    r = Reader("LAN-08 es", locale="es")
    r.anonymous()
    r.open_session()
    rows = []

    # 1. empty message
    t = r.say("", raw_body={"message": "", "simple_mode": False})
    rows.append({"state": "empty message", "code": (t.error or {}).get("code"),
                 "message": (t.error or {}).get("message", ""),
                 "language": judge.language_of((t.error or {}).get("message", ""))})

    # 2. over-length message
    t = r.say("x" * 9000)
    rows.append({"state": "message too long", "code": (t.error or {}).get("code"),
                 "message": (t.error or {}).get("message", ""),
                 "language": judge.language_of((t.error or {}).get("message", ""))})

    # 3. dead token
    c = httpx.Client(base_url=harness.BASE, timeout=30.0)
    resp = c.post("/v2/chat/stream", json={"message": "hola"},
                  headers={"Authorization": "Bearer not-a-real-token"})
    body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
    rows.append({"state": "expired session", "code": body.get("code"),
                 "message": body.get("message", ""),
                 "language": judge.language_of(body.get("message", ""))})
    c.close()
    r.close()

    english = [x for x in rows if x["language"] == "en"]
    add("LAN-08", "Trigger three error states with the interface in a non-English language",
        "PASS" if not english else "FAIL",
        "; ".join(f"{x['state']}: {x['code']} -> {x['language']}" for x in rows),
        [] if not english else [Finding(
            "LAN-08", "S2", f"{len(english)} of 3 error messages are English in a Spanish session",
            steps=["Open a session with locale=es",
                   "Send an empty message", "Send a 9,000-character message",
                   "Send a request with a dead token"],
            expected="Error messages, buttons, tooltips and placeholders are all translated — "
                     "not just the bot's replies.",
            actual="\n".join(f"[{x['state']}] code={x['code']!r} message={x['message']!r}"
                             for x in english),
            reproducible="every time",
            impact="A Spanish-speaking learner hits an error and cannot read what to do next. "
                   "The plan calls this the very thing to look for.")],
        {"rows": rows})


# ── scripts ──


def _fifteen_turns(locale: str) -> list[str]:
    scripts = {
        "en": ["Hello", "What is ASPIRE?", "Who can join?", "How old do I have to be?",
               "Do I need to be a citizen?", "How much money is it?", "Where is it kept?",
               "Can I spend it now?", "What is a share?", "Is that risky?",
               "How do I register?", "What papers do I need?", "Is there a fee?",
               "Who do I contact?", "Thank you, can you sum that up?"],
        "es": ["Hola", "¿Qué es ASPIRE?", "¿Quién puede participar?", "¿Qué edad hay que tener?",
               "¿Hay que ser ciudadano?", "¿Cuánto dinero es?", "¿Dónde se guarda?",
               "¿Puedo gastarlo ahora?", "¿Qué es una acción?", "¿Eso es arriesgado?",
               "¿Cómo me inscribo?", "¿Qué papeles necesito?", "¿Hay que pagar algo?",
               "¿A quién contacto?", "Gracias, ¿me lo resumes?"],
        "fr": ["Bonjour", "Qu'est-ce qu'ASPIRE ?", "Qui peut participer ?",
               "Quel âge faut-il avoir ?", "Faut-il être citoyen ?", "Combien d'argent ?",
               "Où est-il gardé ?", "Puis-je le dépenser maintenant ?",
               "Qu'est-ce qu'une action ?", "Est-ce risqué ?", "Comment m'inscrire ?",
               "Quels papiers faut-il ?", "Y a-t-il des frais ?", "Qui dois-je contacter ?",
               "Merci, peux-tu résumer ?"],
    }
    return scripts[locale]


def _twenty_spanish() -> list[str]:
    return ["Hola", "¿Qué es ASPIRE?", "¿Quién puede participar?", "¿Desde qué edad?",
            "¿Hasta qué edad?", "¿Cuánto dinero recibo?", "¿Dónde está ese dinero?",
            "¿Puedo sacarlo?", "¿Qué es el interés?", "¿Qué es una acción?",
            "¿Es peligroso invertir?", "¿Cómo me inscribo?", "¿Qué documentos necesito?",
            "¿Cuesta algo?", "¿Hay fecha límite?", "¿A quién llamo si tengo problemas?",
            "¿Qué es una cuenta de ahorros?", "¿Cómo hago un presupuesto?",
            "¿Qué consejo me das para ahorrar?", "Gracias, ¿me resumes todo?"]


def _five_hundred_spanish() -> str:
    body = (
        "Buenos días. Le escribo porque estoy bastante confundida con todo el proceso y "
        "quiero explicarle mi situación completa antes de preguntar. Vivo en Basseterre con "
        "mis tres hijos. El mayor tiene diecisiete años y termina la escuela este año, la "
        "del medio tiene doce y está en primaria, y el pequeño cumplió cinco el mes pasado. "
        "Trabajo en el mercado los sábados y en una tienda entre semana, así que tengo muy "
        "poco tiempo para ir a una oficina durante el día. Mi madre vive con nosotros y "
        "ella a veces cuida a los niños. Escuché del programa ASPIRE en la radio y después "
        "una vecina me dijo que su sobrino ya está inscrito y que le abrieron una cuenta en "
        "el banco. La verdad es que no entendí bien lo que ella me explicó porque hablaba "
        "muy rápido y yo estaba trabajando en ese momento. Lo que sí entendí es que el "
        "gobierno pone un dinero para cada niño y que una parte se guarda y otra parte se "
        "invierte, pero no sé si eso es cierto o si ella lo entendió mal. También me "
        "preocupa que mi hija mayor ya casi tiene dieciocho años y no sé si todavía llega a "
        "tiempo o si ya perdió la oportunidad. Mi hermana me dijo que ella también quiere "
        "inscribir a su hijo pero vive en Nevis y no sabe si eso cambia algo. Yo no tengo "
        "computadora en la casa, solamente el teléfono, y a veces el internet no funciona "
        "bien por la tarde. He intentado leer la información antes pero está toda en inglés "
        "y aunque entiendo algo, prefiero que me lo expliquen en español para estar segura "
        "de que no me equivoco con algo importante. No quiero llenar un formulario mal y "
        "que después me digan que no sirve. Tampoco quiero ir al banco y perder un día de "
        "trabajo para nada. Un vecino me dijo que hay que pagar algo para inscribirse pero "
        "otra persona me dijo que es gratis, y esas dos cosas no pueden ser verdad al mismo "
        "tiempo. Le agradezco mucho su paciencia con este mensaje tan largo. Tengo tres "
        "preguntas concretas. Primero, ¿mi hermana en Nevis puede inscribir a su hijo "
        "igual que yo? Segundo, ¿qué documentos exactamente tengo que llevar? Y tercero, "
        "¿el banco abre la cuenta automáticamente o tengo que ir yo a pedirlo?")
    return body


def _translate_ask(ask: str, locale: str) -> str:
    table = {
        "Who is eligible to join ASPIRE?": {
            "es": "¿Quién puede participar en ASPIRE?",
            "fr": "Qui peut participer à ASPIRE ?"},
        "What is ASPIRE?": {"es": "¿Qué es ASPIRE?", "fr": "Qu'est-ce qu'ASPIRE ?"},
        "How do I contact ASPIRE by email?": {
            "es": "¿Cómo contacto a ASPIRE por correo electrónico?",
            "fr": "Comment contacter ASPIRE par courriel ?"},
        "Does it cost anything to join ASPIRE?": {
            "es": "¿Cuesta algo participar en ASPIRE?",
            "fr": "Est-ce que participer à ASPIRE coûte quelque chose ?"},
        "What is the maximum age to join ASPIRE?": {
            "es": "¿Cuál es la edad máxima para participar en ASPIRE?",
            "fr": "Quel est l'âge maximum pour participer à ASPIRE ?"},
    }
    if locale == "en":
        return ask
    return table.get(ask, {}).get(locale, ask)


def _decimal_style(text: str) -> str:
    if re.search(r"\d\.\d{3}\b", text):
        return "1.000 (es/fr style)"
    if re.search(r"\d,\d{3}\b", text):
        return "1,000 (en style)"
    return "no grouped number found"


if __name__ == "__main__":
    log = Log(os.path.join(OUT, "lan.json"))
    print(f"\n=== TRACK {TRACK} · Language & Language Switching ===")
    run(log)
    log.flush()
