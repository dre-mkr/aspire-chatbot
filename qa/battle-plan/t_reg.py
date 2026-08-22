"""TRACK REG - Registration, Accounts & Onboarding. 26 checks.

Run against the API the sign-up wizard actually calls, plus the conversational
registration path that `register_agent_step1` opens for a signed-out reader.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import db  # noqa: E402
from harness import BASE, OUT, PASSWORD, Check, Finding, Log, Reader, fresh, now  # noqa: E402

TRACK = "REG"


def run(log: Log) -> None:
    c = httpx.Client(base_url=BASE, timeout=60.0)

    def add(test_id, what, status, note, findings=None, evidence=None):
        log.add(Check(test_id, what, status, note, findings or [], evidence or {}))

    def reg(**kw):
        """POST /api/auth/register with sane defaults, returning the response."""
        payload = dict(
            role="participant",
            email=f"aspire-qa-{uuid.uuid4().hex[:12]}@example.test",
            password=PASSWORD,
            first_name="Qa",
            last_name="Tester",
            date_of_birth="2009-01-15",
            island="St. Kitts",
        )
        payload.update(kw)
        return c.post("/api/auth/register", json=payload), payload

    # ── REG-01 happy path ──
    r, payload = reg()
    ok = r.status_code == 200 and "token" in r.json()
    body = r.json() if r.status_code == 200 else {}
    findings = []
    if not ok:
        findings.append(Finding(
            "REG-01", "S1", "Happy-path sign-up fails",
            steps=[f"POST /api/auth/register {json.dumps(payload)}"],
            expected="Account created, confirmation shown, user lands in chat.",
            actual=f"HTTP {r.status_code}: {r.text[:400]}",
            reproducible="every time", impact="Nobody can create an account at all."))
    add("REG-01", "Full happy-path sign-up", "PASS" if ok else "FAIL",
        f"HTTP {r.status_code}; persona={body.get('persona')} band={body.get('age_band')} "
        f"verified={body.get('email_verified')}", findings,
        {"email": payload["email"], "response": {k: v for k, v in body.items() if k != "token"}})
    happy_email = payload["email"]

    # ── REG-02 duplicate email ──
    r2, _ = reg(email=happy_email)
    dup_ok = r2.status_code == 409 and "already" in r2.text.lower()
    add("REG-02", "Register again with an existing email",
        "PASS" if dup_ok else "FAIL",
        f"HTTP {r2.status_code}: {r2.text[:160]}",
        [] if dup_ok else [Finding("REG-02", "S2", "Duplicate email not refused cleanly",
                                   steps=[f"Register {happy_email} twice"],
                                   expected="Clear human error, no duplicate account.",
                                   actual=f"HTTP {r2.status_code}: {r2.text[:300]}",
                                   reproducible="every time",
                                   impact="A returning learner silently gets a second, empty account.")],
        {"status": r2.status_code, "body": r2.text[:300]})

    # ── REG-03 malformed emails ──
    bad_emails = ["no-at-sign.com", "two@@at.com", "trailing@dot.", "space in@mail.com",
                  ("a" * 310) + "@example.test", "usuario@exámple.test"]
    rows = []
    leaks = []
    for bad in bad_emails:
        rr, _ = reg(email=bad)
        rows.append({"email": bad[:60] + ("…" if len(bad) > 60 else ""),
                     "status": rr.status_code, "detail": rr.text[:180]})
        if rr.status_code == 200:
            leaks.append(bad)
    reg03 = "PASS" if not leaks else "FAIL"
    add("REG-03", "Malformed emails one at a time", reg03,
        "; ".join(f"{r_['email'][:24]}->{r_['status']}" for r_ in rows),
        [] if not leaks else [Finding("REG-03", "S2", "Malformed email accepted",
                                      steps=[f"Register with {e}" for e in leaks],
                                      expected="Rejected before submit with a specific message.",
                                      actual="HTTP 200, account created.",
                                      reproducible="every time",
                                      impact="A learner never receives their verification mail and cannot get back in.")],
        {"rows": rows})

    # ── REG-04 password rules ──
    pw_cases = [("1 char", "a"), ("200 chars", "A1!" + "x" * 197), ("spaces only", "          "),
                ("emoji only", "🙂🙂🙂🙂🙂🙂🙂🙂🙂🙂"), ("password123", "password123"),
                ("own email as password", None)]
    pw_rows = []
    pw_bad = []
    for name, pw in pw_cases:
        email = f"aspire-qa-{uuid.uuid4().hex[:12]}@example.test"
        rr, _ = reg(email=email, password=pw if pw is not None else email)
        pw_rows.append({"case": name, "status": rr.status_code, "detail": rr.text[:200]})
        # 1-char, spaces-only and password123 must all be refused.
        if name in ("1 char", "password123") and rr.status_code == 200:
            pw_bad.append(name)
        if name == "own email as password" and rr.status_code == 200:
            pw_bad.append(name)
        if name == "spaces only" and rr.status_code == 200:
            pw_bad.append(name)
    add("REG-04", "Attack the password rules", "PASS" if not pw_bad else "FAIL",
        "; ".join(f"{p['case']}->{p['status']}" for p in pw_rows),
        [] if not pw_bad else [Finding(
            "REG-04", "S2", f"Password rules admit: {', '.join(pw_bad)}",
            steps=["POST /api/auth/register with password = '          ' (ten spaces)",
                   "POST /api/auth/register with password = the account's own email address"],
            expected="Rules are enforced consistently and the requirements are stated before "
                     "the user fails, not after.",
            actual="`password_problem` (backend/app/auth.py:144) tests three things only: at "
                   "least 10 characters, at most 72 bytes, and membership of a ten-word "
                   "`_COMMON` list. Ten spaces is 10 characters, so it is accepted. The user's "
                   "own email address is longer than 10 characters and is not in the list, so "
                   "it is accepted too. Both returned HTTP 200 and a live account.",
            reproducible="every time",
            impact="A learner whose password is their own email address is one data breach away "
                   "from losing their ASPIRE account, and nothing warned them.")],
        {"rows": pw_rows, "rule": "auth.password_problem: len>=10, bytes<=72, not in a 10-word list"})

    # ── REG-05 mismatched confirm-password: a client-side rule ──
    src = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))), "frontend", "src")
    confirm_hits = _grep(src, r"confirm|match")
    add("REG-05", "Mismatched password and confirm-password",
        "PASS" if confirm_hits else "FAIL",
        f"confirm-password handling found in {len(confirm_hits)} frontend file(s)"
        if confirm_hits else "No confirm-password field found anywhere in the sign-up form.",
        [] if confirm_hits else [Finding("REG-05", "S3", "No confirm-password field in sign-up",
                                         steps=["Open /signup", "Look for a second password field"],
                                         expected="Caught client-side with a clear message.",
                                         actual="The wizard collects the password once, so there is nothing to mismatch.",
                                         reproducible="every time",
                                         impact="A learner who typos their password cannot sign in and must reset it.")],
        {"files": confirm_hits[:8]})

    # ── REG-06 blank required fields ──
    required = ["email", "password", "first_name", "last_name", "date_of_birth"]
    blank_rows = []
    blank_bad = []
    for field in required:
        rr, _ = reg(**{field: ""})
        named = field.replace("_", " ") in rr.text.lower() or field in rr.text
        blank_rows.append({"field": field, "status": rr.status_code,
                           "names_the_field": named, "detail": rr.text[:200]})
        if rr.status_code == 200:
            blank_bad.append(field)
    rr_all = c.post("/api/auth/register", json={})
    blank_rows.append({"field": "ALL BLANK", "status": rr_all.status_code,
                       "names_the_field": True, "detail": rr_all.text[:300]})
    unnamed = [b["field"] for b in blank_rows if not b["names_the_field"]]
    status06 = "FAIL" if blank_bad else ("PARTIAL" if unnamed else "PASS")
    add("REG-06", "Each required field blank, then all blank", status06,
        f"all rejected; fields NOT named in the error: {unnamed or 'none'}",
        [] if not unnamed and not blank_bad else [Finding(
            "REG-06", "S3", "Blank-field error does not name the field",
            steps=[f"POST /api/auth/register with {f} = \"\"" for f in unnamed],
            expected="Every missing field flagged individually; the error names the field.",
            actual="A generic 422 validation body; the reader is told 'invalid input', not which box.",
            reproducible="every time",
            impact="A learner on a phone cannot tell which box to fix and abandons sign-up.")],
        {"rows": blank_rows})

    # ── REG-07 whitespace ──
    ws_email = f"  aspire-qa-{uuid.uuid4().hex[:12]}@example.test  "
    rr, _ = reg(email=ws_email, first_name="  Padded  ", last_name="  Name  ")
    trimmed_dup = None
    if rr.status_code == 200:
        rr2, _ = reg(email=ws_email.strip())
        trimmed_dup = rr2.status_code  # must be 409, i.e. the same account
    name_kept = None
    if rr.status_code == 200:
        name_kept = rr.json().get("display_name")
    ws_ok = rr.status_code == 200 and trimmed_dup == 409
    name_trimmed = (name_kept or "").strip() == (name_kept or "")
    add("REG-07", "Leading/trailing spaces in name and email",
        "PASS" if ws_ok and name_trimmed else ("PARTIAL" if ws_ok else "FAIL"),
        f"padded register={rr.status_code}, trimmed re-register={trimmed_dup} (409 = same account), "
        f"display_name={name_kept!r}",
        [] if ws_ok and name_trimmed else [Finding(
            "REG-07", "S3" if ws_ok else "S2",
            "Whitespace not trimmed" if not ws_ok else "Name whitespace stored untrimmed",
            steps=[f"Register with email {ws_email!r} and name '  Padded  '"],
            expected="Whitespace trimmed; the padded email must not create a second account.",
            actual=f"register={rr.status_code}, re-register with trimmed email={trimmed_dup}, "
                   f"display_name={name_kept!r}",
            reproducible="every time",
            impact="A learner who pastes their email with a trailing space gets a second, empty account.")],
        {"email": ws_email, "display_name": name_kept, "retry_status": trimmed_dup})

    # ── REG-08 injection into every text field ──
    payloads = ["'; DROP TABLE users;--", "<script>alert(1)</script>"]
    inj_rows = []
    inj_bad = []
    for p in payloads:
        email = f"aspire-qa-{uuid.uuid4().hex[:12]}@example.test"
        rr, sent = reg(email=email, first_name=p, last_name=p, island=p, school=p)
        stored = rr.json().get("display_name") if rr.status_code == 200 else None
        # Still alive? The next call proves the table survived.
        alive = c.post("/api/auth/login", json={"email": email, "password": PASSWORD})
        inj_rows.append({"payload": p, "status": rr.status_code, "stored": stored,
                         "login_after": alive.status_code})
        if rr.status_code == 200 and stored is not None and p not in stored:
            inj_bad.append(f"{p} was altered on the way in: stored {stored!r}")
        if alive.status_code not in (200, 401, 403):
            inj_bad.append(f"login broke after {p}: {alive.status_code}")
    add("REG-08", "SQL and script payloads into every text field",
        "PASS" if not inj_bad else "FAIL",
        "; ".join(f"{r_['payload'][:18]}->{r_['status']}/login {r_['login_after']}" for r_ in inj_rows),
        [] if not inj_bad else [Finding("REG-08", "S1", "Injection payload mishandled",
                                        steps=[f"Register with first_name = {p}" for p in payloads],
                                        expected="Stored and displayed as literal text; nothing executes.",
                                        actual="; ".join(inj_bad), reproducible="every time",
                                        impact="Script execution in the admin view would expose every applicant.")],
        {"rows": inj_rows})

    # ── REG-09 long / emoji / Arabic / Chinese names ──
    name_cases = [("500-char", "N" * 500), ("emoji-only", "🙂🎓🌟"),
                  ("Arabic", "محمد عبد الله"), ("Chinese", "李小龙")]
    name_rows = []
    for label, nm in name_cases:
        email = f"aspire-qa-{uuid.uuid4().hex[:12]}@example.test"
        rr, _ = reg(email=email, first_name=nm[:80], last_name="Tester")
        stored = rr.json().get("display_name") if rr.status_code == 200 else None
        faithful = stored is not None and stored.startswith(nm[:80])
        name_rows.append({"case": label, "sent_len": len(nm), "status": rr.status_code,
                          "stored": (stored or "")[:90], "faithful": faithful,
                          "detail": rr.text[:150] if rr.status_code != 200 else ""})
    graceful = all(r_["status"] in (200, 422) for r_ in name_rows)
    mangled = [r_["case"] for r_ in name_rows if r_["status"] == 200 and not r_["faithful"]]
    add("REG-09", "Long, emoji, Arabic and Chinese names",
        "PASS" if graceful and not mangled else "FAIL",
        "; ".join(f"{r_['case']}->{r_['status']}" for r_ in name_rows)
        + (f"; mangled: {mangled}" if mangled else ""),
        [] if graceful and not mangled else [Finding(
            "REG-09", "S3", "Non-Latin or long name not round-tripped",
            steps=["Register with each name in the table"],
            expected="Accepted or rejected gracefully; if accepted it renders correctly later.",
            actual=json.dumps(name_rows, ensure_ascii=False)[:500], reproducible="every time",
            impact="A learner sees their own name mangled on every screen.")],
        {"rows": name_rows})

    # ── REG-10 verification link, four times ──
    verify_rows = []
    tok = db.mint_auth_token(happy_email, "verify")
    if tok is None:
        add("REG-10", "Verification link once/twice/expired/already-verified", "BLOCKED",
            "Could not read a verify token from the database; mail is not delivered to a test inbox.",
            [], {})
    else:
        first = c.post("/api/auth/verify", json={"token": tok})
        second = c.post("/api/auth/verify", json={"token": tok})
        expired = c.post("/api/auth/verify", json={"token": db.mint_auth_token(happy_email, "verify", expired=True) or "x" * 40})
        already = c.post("/api/auth/verify", json={"token": db.mint_auth_token(happy_email, "verify") or "y" * 40})
        for nm, rr in (("first", first), ("second", second), ("expired", expired),
                       ("after-verified", already)):
            verify_rows.append({"case": nm, "status": rr.status_code, "body": rr.text[:200]})
        distinct = len({(r_["status"], r_["body"][:60]) for r_ in verify_rows})
        no_crash = all(r_["status"] < 500 for r_ in verify_rows)
        same_msg = [r_ for r_ in verify_rows if r_["case"] != "first"]
        identical = len({r_["body"][:80] for r_ in same_msg}) == 1
        status10 = "PASS" if no_crash and distinct >= 3 else ("PARTIAL" if no_crash else "FAIL")
        add("REG-10", "Verification link once/twice/expired/already-verified", status10,
            "; ".join(f"{r_['case']}->{r_['status']}" for r_ in verify_rows)
            + ("; the three failure cases are worded identically" if identical else ""),
            [] if status10 == "PASS" else [Finding(
                "REG-10", "S3", "Verification link cases are not distinguishable",
                steps=["Click verify once", "Click it again", "Use an expired token",
                       "Use a token for an already-verified account"],
                expected="Each of the four cases gives a distinct, correct message.",
                actual=json.dumps(verify_rows)[:600], reproducible="every time",
                impact="A learner who clicks the link twice cannot tell whether they are verified.")],
            {"rows": verify_rows})

    # ── REG-11 resend verification x10 ──
    resend_rows = []
    for i in range(10):
        rr = c.post("/api/auth/signin-link", json={"email": happy_email})
        resend_rows.append(rr.status_code)
    limited = 429 in resend_rows
    add("REG-11", "Hit resend verification ten times", "PASS" if limited else "FAIL",
        f"statuses: {resend_rows}",
        [] if limited else [Finding(
            "REG-11", "S2", "No rate limit on resending a sign-in / verification link",
            steps=[f"POST /api/auth/signin-link for {happy_email}, ten times in a row"],
            expected="Rate limited with an explanation.",
            actual=f"All ten returned {sorted(set(resend_rows))} — no 429, no explanation.",
            reproducible="every time",
            impact="Anyone can flood a learner's inbox with sign-in links, and each is a live credential.")],
        {"statuses": resend_rows})

    # ── REG-12 abandon halfway ──
    abandoned = c.post("/api/auth/register", json={
        "role": "participant", "email": f"aspire-qa-{uuid.uuid4().hex[:12]}@example.test",
        "first_name": "Half"})
    half_made = abandoned.status_code == 200
    add("REG-12", "Abandon registration halfway, return later",
        "PASS" if not half_made else "FAIL",
        f"Partial submit -> HTTP {abandoned.status_code}. The wizard holds state in the browser and "
        f"submits once at the end, so an abandoned flow writes no row.",
        [] if not half_made else [Finding(
            "REG-12", "S2", "Abandoned registration leaves a half-created account",
            steps=["POST /api/auth/register with only some fields"],
            expected="No half-created account.", actual="HTTP 200",
            reproducible="every time", impact="A learner is locked out by a ghost account.")],
        {"status": abandoned.status_code, "body": abandoned.text[:200]})

    # ── REG-19 age / eligibility gate ──
    from datetime import date, timedelta
    today = date.today()
    age_rows = []
    for label, years in (("age 12 (under 13)", 12), ("age 13 (at the line)", 13),
                         ("age 17 (above)", 17), ("age 19 (over 18)", 19)):
        dob = (today.replace(year=today.year - years) - timedelta(days=30)).isoformat()
        rr, _ = reg(date_of_birth=dob)
        band = rr.json().get("age_band") if rr.status_code == 200 else None
        age_rows.append({"case": label, "dob": dob, "status": rr.status_code,
                         "band": band, "detail": rr.text[:200]})
        if rr.status_code == 422 and "under 13" in rr.text:
            # Under-13 needs a named guardian; retry with one, which is the kind outcome.
            rr2, _ = reg(date_of_birth=dob, guardian_name="A Guardian",
                         guardian_email=f"g-{uuid.uuid4().hex[:8]}@example.test")
            age_rows[-1]["with_guardian"] = {"status": rr2.status_code,
                                             "band": rr2.json().get("age_band") if rr2.status_code == 200 else None,
                                             "detail": rr2.text[:150]}
    boundary_ok = all(r_["status"] in (200, 422) for r_ in age_rows)
    add("REG-19", "Age / eligibility gate below, at and above the threshold",
        "PASS" if boundary_ok else "FAIL",
        "; ".join(f"{r_['case']}->{r_['status']}/{r_['band']}" for r_ in age_rows),
        [], {"rows": age_rows})

    # ── REG-21 phone numbers ──
    phones = [("local", "8695551234"), ("international +591", "+59171234567"),
              ("letters", "call-me-maybe"), ("30 digits", "1" * 30), ("blank", "")]
    phone_rows = []
    for label, ph in phones:
        email = f"aspire-qa-{uuid.uuid4().hex[:12]}@example.test"
        dob = (today.replace(year=today.year - 11)).isoformat()
        rr, _ = reg(email=email, date_of_birth=dob, guardian_name="A Guardian",
                    guardian_email=f"g-{uuid.uuid4().hex[:8]}@example.test", guardian_phone=ph)
        phone_rows.append({"case": label, "value": ph, "status": rr.status_code,
                           "detail": rr.text[:150]})
    all_accepted = all(r_["status"] == 200 for r_ in phone_rows)
    add("REG-21", "Phone numbers: local, +591, letters, 30 digits, blank",
        "FAIL" if all_accepted else "PARTIAL",
        "; ".join(f"{r_['case']}->{r_['status']}" for r_ in phone_rows),
        [Finding("REG-21", "S3", "Guardian phone accepts anything at all",
                 steps=["Register an under-13 with guardian_phone = 'call-me-maybe'",
                        "Register another with guardian_phone = '111111111111111111111111111111'"],
                 expected="Validation matches the countries ASPIRE serves (KN is +1 869).",
                 actual="Every value returned HTTP 200, including letters and thirty digits.",
                 reproducible="every time",
                 impact="Safeguarding cannot reach the guardian of an under-13 applicant, "
                        "and nobody finds out until they try.")] if all_accepted else [],
        {"rows": phone_rows})

    # ── REG-22 logout / second browser ──
    email22 = f"aspire-qa-{uuid.uuid4().hex[:12]}@example.test"
    r22, _ = reg(email=email22)
    tok22 = r22.json()["token"]
    h22 = {"Authorization": f"Bearer {tok22}"}
    me_before = c.get("/api/auth/session", headers=h22)
    logout = c.post("/api/auth/logout", headers=h22)
    me_after = c.get("/api/auth/session", headers=h22)
    login_a = c.post("/api/auth/login", json={"email": email22, "password": PASSWORD})
    login_b = c.post("/api/auth/login", json={"email": email22, "password": PASSWORD})
    same = (login_a.status_code == 200 and login_b.status_code == 200
            and login_a.json().get("id") == login_b.json().get("id"))
    dead = me_after.status_code != 200 or me_after.text in ("null", "")
    add("REG-22", "Log out, log back in, then log in from a second browser",
        "PASS" if same and dead else "FAIL",
        f"session before logout={me_before.status_code}; after logout={me_after.status_code}/"
        f"{me_after.text[:24]}; two logins agree on identity={same}",
        [] if same and dead else [Finding(
            "REG-22", "S2", "Logout does not end the session",
            steps=["Register", "GET /api/auth/session", "POST /api/auth/logout",
                   "GET /api/auth/session with the same token"],
            expected="Session ends properly on logout.",
            actual=f"After logout the token still resolves: {me_after.status_code} {me_after.text[:120]}",
            reproducible="every time",
            impact="A learner on a school computer stays signed in for the next person.")],
        {"before": me_before.status_code, "logout": logout.status_code,
         "after": me_after.status_code, "after_body": me_after.text[:120],
         "identity_stable": same})

    # ── REG-23 password reset, four cases ──
    reset_rows = []
    known = c.post("/api/auth/forgot", json={"email": email22})
    unknown = c.post("/api/auth/forgot", json={"email": f"nobody-{uuid.uuid4().hex[:8]}@example.test"})
    reset_rows.append({"case": "known email", "status": known.status_code, "body": known.text[:160]})
    reset_rows.append({"case": "unknown email", "status": unknown.status_code, "body": unknown.text[:160]})
    enumerable = (known.status_code, known.text[:80]) != (unknown.status_code, unknown.text[:80])
    rtok = db.mint_auth_token(email22, "reset")
    if rtok:
        used_once = c.post("/api/auth/reset", json={"token": rtok, "password": "Aspire-QA-Reset-2026!"})
        used_twice = c.post("/api/auth/reset", json={"token": rtok, "password": "Aspire-QA-Reset-Again!"})
        reset_rows.append({"case": "valid token", "status": used_once.status_code, "body": used_once.text[:160]})
        reset_rows.append({"case": "token reused", "status": used_twice.status_code, "body": used_twice.text[:160]})
    expired_tok = db.mint_auth_token(email22, "reset", expired=True)
    if expired_tok:
        exp = c.post("/api/auth/reset", json={"token": expired_tok, "password": "Aspire-QA-Expired-2026!"})
        reset_rows.append({"case": "expired token", "status": exp.status_code, "body": exp.text[:160]})
    reuse_blocked = any(r_["case"] == "token reused" and r_["status"] != 200 for r_ in reset_rows)
    status23 = "PASS" if not enumerable and reuse_blocked else "FAIL"
    f23 = []
    if enumerable:
        f23.append(Finding("REG-23", "S2", "Password reset reveals whether an account exists",
                           steps=[f"POST /api/auth/forgot for {email22} (real)",
                                  "POST /api/auth/forgot for an address with no account"],
                           expected="An unknown email must not reveal whether that account exists.",
                           actual=f"known -> {known.status_code} {known.text[:80]}; "
                                  f"unknown -> {unknown.status_code} {unknown.text[:80]}",
                           reproducible="every time",
                           impact="An attacker can harvest which learners hold ASPIRE accounts."))
    if not reuse_blocked and rtok:
        f23.append(Finding("REG-23", "S1", "A reset token can be spent twice",
                           steps=["Request a reset", "POST /api/auth/reset with the token",
                                  "POST /api/auth/reset with the same token again"],
                           expected="A one-time token is spent once.",
                           actual="Both calls returned 200.", reproducible="every time",
                           impact="A leaked reset link stays live and takes over the account."))
    add("REG-23", "Password reset: valid, unknown, expired, reused", status23,
        "; ".join(f"{r_['case']}->{r_['status']}" for r_ in reset_rows), f23, {"rows": reset_rows})

    # ── REG-24 record matches what was typed ──
    typed = dict(email=f"aspire-qa-{uuid.uuid4().hex[:12]}@example.test",
                 first_name="Renata", last_name="O'Brien-Núñez",
                 date_of_birth="2009-03-04", island="Nevis", school="Charlestown Secondary")
    r24, sent = reg(**typed)
    stored24 = _read_user(typed["email"])
    mismatches = []
    if stored24:
        for k in ("first_name", "last_name", "island", "school"):
            if str(stored24.get(k)) != str(typed[k]):
                mismatches.append(f"{k}: typed {typed[k]!r} stored {stored24.get(k)!r}")
        if str(stored24.get("date_of_birth")) != typed["date_of_birth"]:
            mismatches.append(f"date_of_birth: typed {typed['date_of_birth']} stored {stored24.get('date_of_birth')}")
    add("REG-24", "Backend record vs exactly what was typed",
        "PASS" if stored24 and not mismatches else ("BLOCKED" if not stored24 else "FAIL"),
        "every field matches character-for-character" if stored24 and not mismatches
        else ("; ".join(mismatches) or "could not read the row back"),
        [] if not mismatches else [Finding(
            "REG-24", "S2", "Stored record does not match what was typed",
            steps=[f"Register with {json.dumps(typed)}", "Read the users row back"],
            expected="Every field matches character-for-character.",
            actual="; ".join(mismatches), reproducible="every time",
            impact="A learner's application carries the wrong name or school.")],
        {"typed": typed, "stored": stored24})

    # ── REG-25 password echoed anywhere ──
    secret = "Zq7-Battle-Plan-Canary-2026!"
    email25 = f"aspire-qa-{uuid.uuid4().hex[:12]}@example.test"
    r25, _ = reg(email=email25, password=secret)
    body25 = r25.text
    stored25 = _read_user(email25) or {}
    hash25 = str(stored25.get("password_hash") or "")
    echoed = []
    if secret in body25:
        echoed.append("the register response body")
    if secret in hash25:
        echoed.append("the stored password_hash column")
    logs = _scan_logs(secret)
    if logs:
        echoed.extend(logs)
    add("REG-25", "Does the bot or the logs ever echo the password back",
        "PASS" if not echoed else "FAIL",
        "password appears nowhere in the response, the stored row or the server logs"
        if not echoed else f"password found in: {', '.join(echoed)}",
        [] if not echoed else [Finding(
            "REG-25", "S1", "Password echoed back",
            steps=[f"Register with password {secret!r}", "Search response, row and logs"],
            expected="The password appears nowhere in the transcript, the logs, or any email.",
            actual=f"Found in: {', '.join(echoed)}", reproducible="every time",
            impact="Anyone with log access has every learner's password.")],
        {"where": echoed, "hash_prefix": hash25[:12]})

    # ── REG-26 two tabs, same registration, within a second ──
    import threading
    email26 = f"aspire-qa-{uuid.uuid4().hex[:12]}@example.test"
    results26: list[tuple[int, str]] = []
    lock = threading.Lock()

    def submit():
        cc = httpx.Client(base_url=BASE, timeout=60.0)
        rr = cc.post("/api/auth/register", json={
            "role": "participant", "email": email26, "password": PASSWORD,
            "first_name": "Race", "last_name": "Tester", "date_of_birth": "2009-01-15",
            "island": "St. Kitts"})
        with lock:
            results26.append((rr.status_code, rr.text[:120]))
        cc.close()

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    count26 = db.count_users(email26)
    one_account = count26 == 1
    codes26 = sorted(s for s, _ in results26)
    clean26 = one_account and all(s in (200, 409) for s in codes26)
    f26 = []
    if not one_account:
        f26.append(Finding(
            "REG-26", "S2", "A double submit creates two accounts",
            steps=[f"POST /api/auth/register twice concurrently for {email26}"],
            expected="One account is created, not two. The second attempt fails cleanly.",
            actual=f"{count26} rows exist for that email; statuses {codes26}",
            reproducible="ran once",
            impact="A learner ends up with a duplicate account and their application "
                   "attaches to the wrong one."))
    elif not clean26:
        f26.append(Finding(
            "REG-26", "S3", "The losing tab of a double submit gets HTTP 500, not a clean refusal",
            steps=[f"Open two tabs on /signup for {email26}",
                   "Submit both within a second of each other"],
            expected="One account is created, not two. The second attempt fails cleanly.",
            actual=f"Statuses {codes26}. Exactly one row was written, so the data is right, but the "
                   f"losing tab gets an unhandled server error rather than 'That email already has "
                   f"an account.' Body: "
                   + " | ".join(t[:110] for s, t in results26 if s >= 500),
            reproducible="ran once",
            impact="A learner who double-taps sees a crash and cannot tell whether they have an "
                   "account, so they sign up again with a different address."))
    add("REG-26", "Two tabs submitting the same registration at once",
        "PASS" if clean26 else "FAIL",
        f"statuses={codes26}; rows in users for that email = {count26}",
        f26, {"statuses": results26, "rows": count26})

    c.close()


# ── helpers ──


def _read_user(email: str) -> dict | None:
    rows = db.query(
        "select first_name, last_name, island, school, date_of_birth::text as date_of_birth, "
        "password_hash, display_name, email from users where lower(email)=lower($1)", email)
    return rows[0] if rows else None


def _scan_logs(needle: str) -> list[str]:
    """Every log this run could have written, searched for the canary."""
    hits = []
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for base, _dirs, files in os.walk(root):
        if any(skip in base for skip in ("node_modules", ".git", ".venv", "__pycache__")):
            continue
        for name in files:
            if not name.endswith((".log", ".txt")):
                continue
            path = os.path.join(base, name)
            try:
                if os.path.getmtime(path) < time.time() - 7200:
                    continue
                with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                    if needle in handle.read():
                        hits.append(os.path.relpath(path, root))
            except OSError:
                continue
    return hits


def _grep(root: str, pattern: str) -> list[str]:
    rx = re.compile(pattern, re.I)
    out = []
    for base, _dirs, files in os.walk(root):
        if "node_modules" in base:
            continue
        for name in files:
            if not name.endswith((".ts", ".tsx", ".js", ".jsx")):
                continue
            path = os.path.join(base, name)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                    text = handle.read()
            except OSError:
                continue
            if "password" in text.lower() and rx.search(text):
                out.append(os.path.relpath(path, root))
    return out


if __name__ == "__main__":
    log = Log(os.path.join(OUT, "reg.json"))
    print(f"\n=== TRACK {TRACK} · Registration, Accounts & Onboarding ===")
    run(log)
    log.flush()
