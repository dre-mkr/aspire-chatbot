"""Drive the ASPIRE chat surface the way the QA Battle Plan asks a tester to.

One class, `Reader`, is one person at one keyboard: it holds an account token, a
graph session token, a conversation id, and the transcript of everything it has
said and been told. Every check in the plan is written against that object.

Evidence is the point. Each turn records the exact text sent, the exact text
returned, every directive, the agent that answered, the latency, and the wall
clock -- because a finding without those is, in the plan's own words, an opinion.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

BASE = os.environ.get("ASPIRE_API", "http://127.0.0.1:8010")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "evidence")
os.makedirs(OUT, exist_ok=True)

PASSWORD = "Aspire-QA-2026-Battle!"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def device_id() -> str:
    return uuid.uuid4().hex[:32]


def session_id() -> str:
    return uuid.uuid4().hex


# ── findings ──


@dataclass
class Finding:
    test_id: str
    severity: str
    title: str
    steps: list[str] = field(default_factory=list)
    expected: str = ""
    actual: str = ""
    reproducible: str = ""
    impact: str = ""
    persona: str = ""
    session: str = ""
    at: str = field(default_factory=now)

    def as_dict(self) -> dict[str, Any]:
        return dict(
            test_id=self.test_id,
            severity=self.severity,
            title=self.title,
            steps=self.steps,
            expected=self.expected,
            actual=self.actual,
            reproducible=self.reproducible,
            impact=self.impact,
            persona=self.persona,
            session=self.session,
            at=self.at,
        )


@dataclass
class Check:
    """One row of one track's table."""

    test_id: str
    what: str
    status: str  # PASS | FAIL | PARTIAL | BLOCKED | NOT-AUTOMATABLE
    note: str = ""
    findings: list[Finding] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    at: str = field(default_factory=now)


class Log:
    """The master log the QA Lead owns."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.checks: list[Check] = []

    def add(self, check: Check) -> Check:
        self.checks.append(check)
        marker = {
            "PASS": "PASS",
            "FAIL": "FAIL",
            "PARTIAL": "PART",
            "BLOCKED": "BLKD",
            "NOT-AUTOMATABLE": "MANL",
        }.get(check.status, check.status)
        sev = ",".join(sorted({f.severity for f in check.findings}))
        print(f"  [{marker}] {check.test_id}  {check.note[:110]}" + (f"   <{sev}>" if sev else ""))
        self.flush()
        return check

    def flush(self) -> None:
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(
                [
                    dict(
                        test_id=c.test_id,
                        what=c.what,
                        status=c.status,
                        note=c.note,
                        at=c.at,
                        findings=[f.as_dict() for f in c.findings],
                        evidence=c.evidence,
                    )
                    for c in self.checks
                ],
                handle,
                indent=1,
                ensure_ascii=False,
                default=str,
            )


# ── one reader ──


@dataclass
class Turn:
    sent: str
    text: str
    agent: str | None
    directives: list[dict[str, Any]]
    events: list[dict[str, Any]]
    elapsed_ms: int
    first_token_ms: int | None
    status: int
    error: dict[str, Any] | None
    at: str = field(default_factory=now)


class Reader:
    """One person, one browser, one conversation."""

    def __init__(
        self,
        label: str,
        *,
        locale: str = "en",
        persona: str | None = None,
        timeout: float = 180.0,
    ) -> None:
        self.label = label
        self.locale = locale
        self.requested_persona = persona
        self.device = device_id()
        self.session = session_id()
        self.account_token: str | None = None
        self.graph_token: str | None = None
        self.persona: str | None = None
        self.age_band: str | None = None
        self.account_status: str | None = None
        self.persona_refused: bool | None = None
        self.turns: list[Turn] = []
        self.http = httpx.Client(base_url=BASE, timeout=timeout)
        self.email: str | None = None

    # -- identity --

    def anonymous(self) -> dict[str, Any]:
        r = self.http.post("/api/auth/anonymous", json={"device_id": self.device})
        r.raise_for_status()
        body = r.json()
        self.account_token = body["token"]
        return body

    def register(self, **fields: Any) -> httpx.Response:
        payload = dict(
            role="participant",
            email=fields.pop("email", None) or self.new_email(),
            password=fields.pop("password", None) or PASSWORD,
            first_name="Qa",
            last_name="Tester",
            date_of_birth="2009-01-15",
            island="St. Kitts",
        )
        payload.update(fields)
        self.email = payload.get("email")
        headers = self.auth_headers()
        r = self.http.post("/api/auth/register", json=payload, headers=headers)
        if r.status_code == 200:
            self.account_token = r.json()["token"]
        return r

    def login(self, email: str, password: str) -> httpx.Response:
        r = self.http.post("/api/auth/login", json={"email": email, "password": password})
        if r.status_code == 200:
            self.account_token = r.json()["token"]
        return r

    def new_email(self) -> str:
        return f"aspire-qa-{uuid.uuid4().hex[:12]}@example.test"

    def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.account_token}"} if self.account_token else {}

    def open_session(self, *, locale: str | None = None, persona: str | None = None,
                     session: str | None = None) -> dict[str, Any]:
        """Mint the graph token. This is what /v2/chat/stream authenticates with."""
        if locale:
            self.locale = locale
        if session:
            self.session = session
        body = {
            "session_id": self.session,
            "device_id": self.device,
            "locale": self.locale,
        }
        want = persona if persona is not None else self.requested_persona
        if want:
            body["persona"] = want
        r = self.http.post("/v2/session", json=body, headers=self.auth_headers())
        r.raise_for_status()
        data = r.json()
        self.graph_token = data["token"]
        self.persona = data.get("persona")
        self.age_band = data.get("age_band")
        self.account_status = data.get("account_status")
        self.persona_refused = data.get("persona_refused")
        return data

    # -- talking --

    def say(self, message: str, *, simple_mode: bool = False, raw_body: dict | None = None,
            timeout: float | None = None) -> Turn:
        body = raw_body if raw_body is not None else {"message": message, "simple_mode": simple_mode}
        headers = {"Authorization": f"Bearer {self.graph_token}"} if self.graph_token else {}
        started = time.monotonic()
        first_token: float | None = None
        events: list[dict[str, Any]] = []
        text_parts: list[str] = []
        directives: list[dict[str, Any]] = []
        agent: str | None = None
        error: dict[str, Any] | None = None
        status = 0

        try:
            with self.http.stream(
                "POST", "/v2/chat/stream", json=body, headers=headers,
                timeout=timeout or self.http.timeout,
            ) as response:
                status = response.status_code
                if response.headers.get("content-type", "").startswith("application/json"):
                    error = json.loads(response.read().decode("utf-8"))
                else:
                    name = ""
                    data = ""
                    for line in response.iter_lines():
                        if line.startswith("event: "):
                            name = line[7:].strip()
                        elif line.startswith("data: "):
                            data = line[6:]
                        elif line == "":
                            if not name:
                                continue
                            try:
                                payload = json.loads(data)
                            except json.JSONDecodeError:
                                name, data = "", ""
                                continue
                            events.append({"event": name, "data": payload})
                            if name == "token":
                                if first_token is None:
                                    first_token = time.monotonic()
                                text_parts.append(payload.get("t", ""))
                            elif name == "directive":
                                directives.append(payload.get("d", {}))
                            elif name == "done":
                                agent = (payload.get("usage") or {}).get("agent")
                            elif name == "error":
                                error = payload
                            name, data = "", ""
        except Exception as exc:  # a transport failure is itself a result
            error = {"code": "transport", "message": f"{type(exc).__name__}: {exc}"}

        turn = Turn(
            sent=message,
            text="".join(text_parts),
            agent=agent,
            directives=directives,
            events=events,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            first_token_ms=int((first_token - started) * 1000) if first_token else None,
            status=status,
            error=error,
        )
        self.turns.append(turn)
        return turn

    def transcript(self) -> str:
        out = [f"# {self.label} · persona={self.persona} band={self.age_band} locale={self.locale}",
               f"session={self.session}", ""]
        for i, t in enumerate(self.turns, 1):
            out.append(f"## turn {i} · {t.at} · agent={t.agent} · {t.elapsed_ms}ms")
            out.append(f"**> {t.sent}**")
            out.append("")
            out.append(t.text or f"(no prose; error={t.error})")
            if t.directives:
                out.append("")
                out.append("directives: " + ", ".join(d.get("t", "?") for d in t.directives))
            out.append("")
        return "\n".join(out)

    def save(self, name: str) -> str:
        path = os.path.join(OUT, f"{name}.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(self.transcript())
        return path

    def close(self) -> None:
        self.http.close()


def fresh(label: str, **kwargs: Any) -> Reader:
    """An anonymous reader with a live graph session, ready to talk."""
    r = Reader(label, **kwargs)
    r.anonymous()
    r.open_session()
    return r


def signed_up(label: str, *, dob: str, role: str = "participant", locale: str = "en",
              persona: str | None = None, **extra: Any) -> Reader:
    """A registered reader, whose date of birth chooses the persona."""
    r = Reader(label, locale=locale, persona=persona)
    r.anonymous()
    response = r.register(date_of_birth=dob, role=role, **extra)
    if response.status_code != 200:
        raise RuntimeError(f"sign-up for {label} failed: {response.status_code} {response.text[:300]}")
    r.open_session()
    return r
