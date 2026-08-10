"""Turn 706 Q&A rows into teachable concepts."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

REPO = BACKEND.parent
LEARNING = REPO / "learning"
CHECKPOINTS = LEARNING / ".seed"
KB_CSV = BACKEND / "data" / "knowledge_base.csv"

logger = logging.getLogger("seed_concepts")


# ── the shape of the corpus ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class KBRow:
    """One knowledge-base row, as the CSV holds it."""

    id: str
    category: str
    subcategory: str
    question: str
    answer: str
    keywords: str
    audience: str

    @property
    def is_programme(self) -> bool:
        """Whether this row is about ASPIRE itself rather than about money."""
        return self.id.upper().startswith("ASP-")

    def for_taxonomy(self) -> str:
        return f"{self.id} | {self.category} / {self.subcategory} | {self.question}"

    def for_body(self) -> str:
        return f"[{self.id}] Q: {self.question}\n    A: {self.answer}"

    def searchable(self) -> str:
        return " ".join((self.question, self.answer, self.keywords)).lower()


def load_kb(path: Path = KB_CSV) -> list[KBRow]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [
            KBRow(
                id=(row.get("id") or "").strip(),
                category=(row.get("category") or "").strip(),
                subcategory=(row.get("subcategory") or "").strip(),
                question=(row.get("question") or "").strip(),
                answer=(row.get("answer") or "").strip(),
                keywords=(row.get("keywords") or "").strip(),
                audience=(row.get("audience") or "").strip(),
            )
            for row in csv.DictReader(handle)
        ]
    return [row for row in rows if row.id and row.question]


# ── model access ─────────────────────────────────────────────────────────────

#: Batch size for Pass A.
TAXONOMY_BATCH = 80

#: Batch size for Pass B.
ASSIGN_BATCH = 40

#: How many Pass C calls run at once.
CONCURRENCY = 4


class Models:
    """The two model tiers this script uses, and the client that calls them."""

    def __init__(self, *, strong: str, cheap: str) -> None:
        from openai import AsyncOpenAI

        self.strong = strong
        self.cheap = cheap
        self.client = AsyncOpenAI()
        self.calls = 0

    async def json_call(
        self,
        *,
        model: str,
        system: str,
        user: str,
        attempts: int = 3,
    ) -> dict[str, Any] | None:
        """One JSON-mode call, retried on transport failure and on unparseable output."""
        for attempt in range(1, attempts + 1):
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                self.calls += 1
                text = (response.choices[0].message.content or "").strip()
                return json.loads(text)
            except json.JSONDecodeError:
                logger.warning("Attempt %d returned unparseable JSON.", attempt)
            except Exception as error:  # transport, rate limit, 403
                logger.warning("Attempt %d failed: %s", attempt, error)
                await asyncio.sleep(min(2**attempt, 20))
        return None


# ── Pass A: taxonomy ─────────────────────────────────────────────────────────

_TAXONOMY_SYSTEM = """You are designing the concept taxonomy for a financial-literacy
programme for citizens aged 5-18 in St. Kitts and Nevis.

You are given a batch of knowledge-base questions. Propose the TEACHABLE CONCEPTS they
cover -- the ideas a tutor would explain, not the questions themselves. "What documents
do I need?" and "Can I apply without a birth certificate?" are two questions about ONE
concept.

For each concept give:
  slug        lower_snake_case, 2-4 words, stable and specific: compound_interest,
              needs_vs_wants, aspire_eligibility. Never a question.
  title       how a person would name it: "Compound interest"
  domain      one of: saving, investing, budgeting, credit, scams, earning, goals,
              aspire_programme
  band_min    the youngest of 5-8, 9-12, 13-15, 16-18, adult that could meet this idea
  band_max    the oldest band it is still worth teaching to; "adult" for most
  aliases     3-6 phrases a learner might actually use for it, including childlike ones
              ("interest on interest", "money growing by itself")

Rules:
- A concept about how the ASPIRE programme works has domain aspire_programme and
  band_min 9-12 at the youngest (a five-year-old is not the one enrolling).
- band_min 5-8 only for ideas a six-year-old can hold: saving, spending, wanting,
  waiting, coins, a goal. Never a rate, never a percentage, never a contract.
- Do not propose a concept for a question that is pure administration ("what are your
  opening hours"). Those are Q&A, not teaching.
- Prefer 8-14 concepts per batch. Merging happens later; over-splitting is worse than
  under-splitting because two near-identical slugs both draw too few sources.

Return JSON: {"concepts": [{"slug","title","domain","band_min","band_max","aliases":[]}]}"""


@dataclass
class ProposedConcept:
    slug: str
    title: str
    domain: str
    band_min: str
    band_max: str
    aliases: list[str] = field(default_factory=list)
    #: Filled by Pass B.
    kb_ids: list[str] = field(default_factory=list)


_VALID_DOMAINS = {
    "saving",
    "investing",
    "budgeting",
    "credit",
    "scams",
    "earning",
    "goals",
    "aspire_programme",
}
_VALID_BANDS = ("5-8", "9-12", "13-15", "16-18", "adult")


def _clean_proposal(raw: dict[str, Any]) -> ProposedConcept | None:
    slug = re.sub(r"[^a-z0-9_]", "", str(raw.get("slug") or "").strip().lower().replace(" ", "_"))
    title = str(raw.get("title") or "").strip()
    if not slug or not title or len(slug) < 3:
        return None
    domain = str(raw.get("domain") or "").strip().lower()
    if domain not in _VALID_DOMAINS:
        domain = "saving"
    band_min = str(raw.get("band_min") or "9-12").strip()
    band_max = str(raw.get("band_max") or "adult").strip()
    if band_min not in _VALID_BANDS:
        band_min = "9-12"
    if band_max not in _VALID_BANDS:
        band_max = "adult"
    if _VALID_BANDS.index(band_min) > _VALID_BANDS.index(band_max):
        band_min, band_max = band_max, band_min
    aliases = [
        str(alias).strip()
        for alias in (raw.get("aliases") or [])
        if str(alias).strip()
    ][:8]
    return ProposedConcept(
        slug=slug, title=title, domain=domain, band_min=band_min, band_max=band_max,
        aliases=aliases,
    )


async def pass_a(models: Models, rows: list[KBRow]) -> list[ProposedConcept]:
    """Propose a taxonomy over the whole corpus, in batches, then merge."""
    batches = [rows[i : i + TAXONOMY_BATCH] for i in range(0, len(rows), TAXONOMY_BATCH)]
    logger.info("Pass A: %d rows in %d batches.", len(rows), len(batches))

    async def one(batch: list[KBRow]) -> list[ProposedConcept]:
        user = "\n".join(row.for_taxonomy() for row in batch)
        data = await models.json_call(model=models.strong, system=_TAXONOMY_SYSTEM, user=user)
        if not data:
            return []
        proposals = [_clean_proposal(entry) for entry in (data.get("concepts") or [])]
        return [proposal for proposal in proposals if proposal]

    results = await _gather_limited([one(batch) for batch in batches], CONCURRENCY)
    proposed = [concept for batch in results for concept in batch]
    merged = _merge_taxonomy(proposed)
    logger.info("Pass A: %d proposals merged to %d concepts.", len(proposed), len(merged))
    return merged


_STOP = {"a", "an", "the", "of", "and", "or", "to", "vs", "for", "your", "my", "in", "on"}


def _title_tokens(text: str) -> frozenset[str]:
    return frozenset(
        word for word in re.findall(r"[a-z]+", text.lower()) if word not in _STOP
    )


def _merge_taxonomy(proposals: list[ProposedConcept]) -> list[ProposedConcept]:
    """Deduplicate by slug, then by title overlap."""
    by_slug: dict[str, ProposedConcept] = {}
    for proposal in proposals:
        existing = by_slug.get(proposal.slug)
        if existing is None:
            by_slug[proposal.slug] = proposal
            continue
        # Same slug from two batches: keep the wider band range and pool aliases.
        existing.aliases = list(dict.fromkeys(existing.aliases + proposal.aliases))[:8]
        if _VALID_BANDS.index(proposal.band_min) < _VALID_BANDS.index(existing.band_min):
            existing.band_min = proposal.band_min
        if _VALID_BANDS.index(proposal.band_max) > _VALID_BANDS.index(existing.band_max):
            existing.band_max = proposal.band_max

    kept: list[ProposedConcept] = []
    for proposal in by_slug.values():
        tokens = _title_tokens(proposal.title)
        duplicate = None
        for other in kept:
            other_tokens = _title_tokens(other.title)
            union = tokens | other_tokens
            if not union:
                continue
            if len(tokens & other_tokens) / len(union) >= 0.7:
                duplicate = other
                break
        if duplicate is None:
            kept.append(proposal)
        else:
            duplicate.aliases = list(
                dict.fromkeys(duplicate.aliases + proposal.aliases + [proposal.title])
            )[:8]
    return kept


# ── Pass B: assignment ───────────────────────────────────────────────────────

_ASSIGN_SYSTEM = """You are assigning knowledge-base rows to teaching concepts.

You are given the full concept list and a batch of rows. For each row, name every
concept it provides EVIDENCE for -- material a tutor could teach that concept from.

Rules:
- A row may support several concepts. A row may support none; say so with an empty list
  rather than reaching for the nearest one. A wrong assignment puts an unrelated fact in
  front of the model that writes the lesson, which is how a lesson goes wrong.
- Assign on what the ANSWER contains, not on what the question asks. "Can I apply at 12?"
  answered with the full eligibility rule supports aspire_eligibility.
- Pure administration rows (opening hours, phone numbers) usually support nothing.

Return JSON: {"assignments": [{"kb_id": "ASP-001", "slugs": ["aspire_overview"]}]}"""


async def pass_b(
    models: Models, rows: list[KBRow], taxonomy: list[ProposedConcept]
) -> list[ProposedConcept]:
    """Assign every KB row to zero or more concepts."""
    menu = "\n".join(
        f"{concept.slug} | {concept.title} | {concept.domain}" for concept in taxonomy
    )
    known = {concept.slug for concept in taxonomy}
    by_slug = {concept.slug: concept for concept in taxonomy}

    batches = [rows[i : i + ASSIGN_BATCH] for i in range(0, len(rows), ASSIGN_BATCH)]
    logger.info("Pass B: %d rows in %d batches over %d concepts.", len(rows), len(batches), len(taxonomy))

    async def one(batch: list[KBRow]) -> list[tuple[str, list[str]]]:
        user = f"CONCEPTS:\n{menu}\n\nROWS:\n" + "\n".join(row.for_body() for row in batch)
        data = await models.json_call(model=models.cheap, system=_ASSIGN_SYSTEM, user=user)
        if not data:
            return []
        out: list[tuple[str, list[str]]] = []
        for entry in data.get("assignments") or []:
            kb_id = str(entry.get("kb_id") or "").strip()
            slugs = [
                str(slug).strip()
                for slug in (entry.get("slugs") or [])
                if str(slug).strip() in known
            ]
            if kb_id:
                out.append((kb_id, slugs))
        return out

    results = await _gather_limited([one(batch) for batch in batches], CONCURRENCY)
    for batch in results:
        for kb_id, slugs in batch:
            for slug in slugs:
                by_slug[slug].kb_ids.append(kb_id)

    for concept in taxonomy:
        concept.kb_ids = sorted(dict.fromkeys(concept.kb_ids))
    return taxonomy


def coverage_report(rows: list[KBRow], taxonomy: list[ProposedConcept]) -> dict[str, Any]:
    """How much of the corpus landed somewhere, and which concepts are thin."""
    assigned: set[str] = {kb_id for concept in taxonomy for kb_id in concept.kb_ids}
    orphans = [row.id for row in rows if row.id not in assigned]
    thin = [concept.slug for concept in taxonomy if len(concept.kb_ids) < 3]
    starved = [concept.slug for concept in taxonomy if len(concept.kb_ids) < 2]
    return {
        "kb_rows": len(rows),
        "assigned": len(assigned),
        "coverage_pct": round(100.0 * len(assigned) / max(len(rows), 1), 1),
        "orphan_ids": orphans,
        "concepts": len(taxonomy),
        "thin_concepts": thin,
        "starved_concepts": starved,
    }


# ── Pass C: bodies ───────────────────────────────────────────────────────────

_BODY_SYSTEM = """You are writing teaching material for a government financial-literacy
programme in St. Kitts and Nevis. You are given a concept and the ONLY source rows you
may use.

Write FIVE bodies for the concept: ages 5-8, 9-12, 13-15, 16-18, and adult. Each is 2-4
short paragraphs. Each must be independently complete -- a 7-year-old reads only
body_5_8 and must come away understanding the idea.

Rules:
- Every fact must be supported by a source row. Cite nothing inline; the rows are
  recorded separately.
- Currency is EC$ (XCD). Examples are St. Kitts and Nevis: a patty, bus fare, school
  supplies, a bicycle, a Carnival costume, a snow cone. Never USD, never American schools
  or stores.
- The 5-8 body uses sentences of 12 words or fewer and no word a Grade 2 reader would not
  know. It never says "interest", "percent", "invest" or "account".
- The 9-12 body may say "interest" but never "compound", "percentage" or "dividend".
- Do not moralise. Do not tell a child their family should save more.
- Write PROSE. No headings, no bullet lists, no markdown.
- If the concept does not suit a band at all, return "" for that body rather than
  stretching it. An empty body is honest; a bad one is served to a child.

LENGTH, and this is a floor not a target. Thin material is the failure being designed
out:
  body_5_8    45-110 words
  body_9_12   70-150 words
  body_13_15  110-220 words
  body_16_18  130-260 words
  body_adult  140-280 words

Also produce:
  local_example     one concrete EC$ scenario in St. Kitts and Nevis, 1-2 sentences
  misconceptions    2-3 items as {"wrong": "...", "right": "..."}
  numeric_anchors   the SMALL set of numbers your examples are built on, as a flat
                    object: {"weekly_saving_xcd": 5, "weeks": 4, "total_xcd": 20}.
                    EVERY number appearing in any body must be here or in a source row.
  check_bank        at least three items per band that has a body. Each:
                    {"id","band","type","question","answer","accept":[],"hints":[h1,h2,h3],
                     "explanation_on_correct","explanation_on_wrong"}
                    band is one of "5_8","9_12","13_15","16_18","adult".
                    type is one of "numeric","multiple_choice","short_answer","true_false".
                    The three hints are a LADDER: nudge, then method, then nearly the
                    answer. The third hint never states the answer outright.
  widget_hints      2-4 of: simulator, growth_stack, compare, sort_buckets, allocator,
                    flow_diagram, timeline, reveal_cards, proportion -- the interactive
                    forms that would genuinely help THIS idea. Fewer is better.
  unsupported_claims  a list of everything you wanted to include and left out because
                    the source rows do not support it. BE THOROUGH. This list is the
                    point of the exercise: it becomes the authoring backlog.

Return JSON with exactly these keys: body_5_8, body_9_12, body_13_15, body_16_18,
body_adult, local_example, misconceptions, numeric_anchors, check_bank, widget_hints,
unsupported_claims."""


async def pass_c(
    models: Models, taxonomy: list[ProposedConcept], rows: list[KBRow], limit: int | None
) -> dict[str, dict[str, Any]]:
    """Generate bodies for every concept that drew at least one source row."""
    by_id = {row.id: row for row in rows}
    targets = [concept for concept in taxonomy if concept.kb_ids]
    if limit:
        targets = targets[:limit]
    logger.info("Pass C: generating bodies for %d concepts.", len(targets))

    async def one(concept: ProposedConcept) -> tuple[str, dict[str, Any] | None]:
        sources = [by_id[kb_id] for kb_id in concept.kb_ids if kb_id in by_id]
        user = (
            f"CONCEPT: {concept.title} ({concept.slug})\n"
            f"Domain: {concept.domain}. Taught to bands {concept.band_min} through "
            f"{concept.band_max}.\n"
            f"Learners might call it: {', '.join(concept.aliases) or concept.title}\n\n"
            f"SOURCE ROWS -- the only material you may use:\n"
            + "\n".join(row.for_body() for row in sources)
        )
        data = await models.json_call(model=models.strong, system=_BODY_SYSTEM, user=user)
        return concept.slug, data

    results = await _gather_limited([one(concept) for concept in targets], CONCURRENCY)
    bodies = {slug: data for slug, data in results if data}
    logger.info("Pass C: %d of %d concepts generated.", len(bodies), len(targets))
    return bodies


# ── Pass D: grounding validation, in code ────────────────────────────────────

#: Numbers that are prose scaffolding rather than claims.
_STRUCTURAL_NUMBERS = frozenset({0, 1, 2, 3})

#: Words that make a claim about ASPIRE itself rather than about money.
_PROGRAMME_TERMS = re.compile(
    r"\b(?:aspire|eligib\w*|enrol\w*|enroll\w*|apply|application|applicant|"
    r"seed(?:ed|ing)?|deposit\w*|account\s+open\w*|guardian\s+consent|"
    r"birth\s+certificate|national\s+id|programme|program)\b",
    re.IGNORECASE,
)

_WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100, "thousand": 1000,
}

_NUMERIC = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(%?)")


def numbers_in(text: str) -> set[float]:
    """Every number a reader would take as a claim."""
    found: set[float] = set()
    for match in _NUMERIC.finditer(text):
        raw = match.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        found.add(value)
        if match.group(2) == "%":
            found.add(value / 100.0)
    for word, value in _WORD_NUMBERS.items():
        if re.search(rf"\b{word}\b", text, re.IGNORECASE):
            found.add(float(value))
    return found


def _anchor_values(anchors: dict[str, Any]) -> set[float]:
    values: set[float] = set()
    for value in (anchors or {}).values():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            values.add(float(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, (int, float)) and not isinstance(item, bool):
                    values.add(float(item))
    return values


def derivable_from(anchors: dict[str, Any]) -> set[float]:
    """Every figure the anchors legitimately produce, via the formula registry."""
    values = _anchor_values(anchors)
    derived: set[float] = set(values)

    ordered = sorted(values)
    for i, left in enumerate(ordered):
        for right in ordered[i:]:
            derived.add(left + right)
            derived.add(left * right)
            derived.add(abs(left - right))
            if right:
                derived.add(left / right)

    # Registry results, guarded: these take specific parameter names and a body's anchors are named freely, so the…
    try:
        from app.widgets.formulas import registry
    except Exception:  # pragma: no cover - the registry is always importable
        return {round(value, 2) for value in derived}

    money = [value for value in values if value >= 1]
    rates = [value for value in values if 0 < value < 1]
    periods = [value for value in values if 1 <= value <= 50 and float(value).is_integer()]

    for principal in money[:6]:
        for rate in rates[:4]:
            for years in periods[:6]:
                for call in (registry.simple_interest, registry.compound_interest):
                    try:
                        result = call(int(round(principal * 100)), rate, years)
                    except Exception:
                        continue
                    for figure in _result_figures(result):
                        derived.add(figure)

    return {round(value, 2) for value in derived}


def _result_figures(result: Any) -> set[float]:
    """Every number a formula result exposes, in dollars and in cents."""
    figures: set[float] = set()
    value = getattr(result, "value", None)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        figures.add(float(value))
        figures.add(round(float(value) / 100.0, 2))
    for step in getattr(result, "series", None) or ():
        if isinstance(step, (int, float)) and not isinstance(step, bool):
            figures.add(float(step))
            figures.add(round(float(step) / 100.0, 2))
    return figures


@dataclass
class Violation:
    band: str
    kind: str
    detail: str

    def quoted(self) -> str:
        return f"{self.kind} in {self.band}: {self.detail}"


def validate_grounding(
    *,
    bodies: dict[str, Any],
    sources: list[KBRow],
) -> list[Violation]:
    """Every number traced and every programme claim sourced."""
    violations: list[Violation] = []
    source_text = " ".join(row.searchable() for row in sources)
    source_numbers = numbers_in(source_text)
    anchors = bodies.get("numeric_anchors") or {}
    permitted = source_numbers | derivable_from(anchors) | _STRUCTURAL_NUMBERS
    has_programme_source = any(row.is_programme for row in sources)

    from app.learning.concepts import BODY_COLUMNS

    for band, column in BODY_COLUMNS.items():
        body = str(bodies.get(column) or "").strip()
        if not body:
            continue

        ungrounded = sorted(
            value
            for value in numbers_in(body)
            if not any(abs(value - candidate) < 0.011 for candidate in permitted)
        )
        if ungrounded:
            violations.append(
                Violation(band, "NUMBER", f"{ungrounded} appear in no source row or anchor")
            )

        if not has_programme_source:
            claims = sorted({match.group(0).lower() for match in _PROGRAMME_TERMS.finditer(body)})
            if claims:
                violations.append(
                    Violation(
                        band,
                        "PROGRAMME",
                        f"claims about the programme ({claims}) with no ASP- source row",
                    )
                )

    return violations


_REGENERATE_SUFFIX = """

YOUR PREVIOUS ATTEMPT FAILED GROUNDING VALIDATION. The violations were:

{violations}

Every number you write must appear in a source row above or in numeric_anchors, or be
arithmetic on numeric_anchors. If you want a figure, put it in numeric_anchors. If the
sources do not support a claim, leave it out and record it in unsupported_claims.
Rewrite all five bodies."""


async def pass_d(
    models: Models,
    taxonomy: list[ProposedConcept],
    bodies: dict[str, dict[str, Any]],
    rows: list[KBRow],
    *,
    offline: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    """Validate, regenerate once, then null what still fails."""
    by_id = {row.id: row for row in rows}
    by_slug = {concept.slug: concept for concept in taxonomy}
    surviving: dict[str, list[str]] = {}

    for slug, generated in list(bodies.items()):
        concept = by_slug.get(slug)
        if concept is None:
            continue
        sources = [by_id[kb_id] for kb_id in concept.kb_ids if kb_id in by_id]

        violations = validate_grounding(bodies=generated, sources=sources)
        if not violations:
            continue

        logger.info("Pass D: %s failed with %d violation(s); regenerating.", slug, len(violations))
        if offline:
            surviving[slug] = [violation.quoted() for violation in violations]
            _null_offending(generated, violations)
            continue

        user = (
            f"CONCEPT: {concept.title} ({concept.slug})\n"
            f"Domain: {concept.domain}. Bands {concept.band_min} to {concept.band_max}.\n\n"
            "SOURCE ROWS -- the only material you may use:\n"
            + "\n".join(row.for_body() for row in sources)
            + _REGENERATE_SUFFIX.format(
                violations="\n".join(f"  - {violation.quoted()}" for violation in violations)
            )
        )
        retried = await models.json_call(model=models.strong, system=_BODY_SYSTEM, user=user)
        if retried:
            second = validate_grounding(bodies=retried, sources=sources)
            if not second:
                bodies[slug] = retried
                logger.info("Pass D: %s passed on retry.", slug)
                continue
            generated = retried
            bodies[slug] = retried
            violations = second

        surviving[slug] = [violation.quoted() for violation in violations]
        _null_offending(generated, violations)
        logger.warning("Pass D: %s still fails; nulling %d band(s).", slug, len(violations))

    return bodies, surviving


def _null_offending(generated: dict[str, Any], violations: list[Violation]) -> None:
    """Remove only the bands that failed."""
    from app.learning.concepts import BODY_COLUMNS

    for violation in violations:
        column = BODY_COLUMNS.get(violation.band)
        if column:
            generated[column] = ""


# ── Pass E: embed and write ──────────────────────────────────────────────────


def _concept_id(index: int) -> str:
    return f"CON-{index:04d}"


async def pass_e(
    taxonomy: list[ProposedConcept],
    bodies: dict[str, dict[str, Any]],
    failures: dict[str, list[str]],
    *,
    write: bool,
    embed: bool = True,
) -> list[dict[str, Any]]:
    """Embed, upsert, and export the review CSV."""
    from app.learning.concepts import BODY_COLUMNS, TeachingConcept

    records: list[dict[str, Any]] = []
    next_index = 1

    for concept in taxonomy:
        generated = bodies.get(concept.slug)
        if not generated:
            continue

        body_map = {
            band: str(generated.get(column) or "").strip()
            for band, column in BODY_COLUMNS.items()
        }
        if not any(body_map.values()):
            logger.info("Skipping %s: every body was empty or nulled.", concept.slug)
            continue

        # `needs_review` for two independent reasons and both exclude it from runtime: too few sources to be trustworth…
        thin = len(concept.kb_ids) < 2
        status = "needs_review" if (thin or concept.slug in failures) else "draft"

        record = {
            "id": _concept_id(next_index),
            "slug": concept.slug,
            "locale": "en",
            "title": concept.title,
            "domain": concept.domain,
            "band_min": concept.band_min,
            "band_max": concept.band_max,
            "aliases": concept.aliases,
            **{column: body_map[band] for band, column in BODY_COLUMNS.items()},
            "local_example": str(generated.get("local_example") or "").strip(),
            "misconceptions": _clean_misconceptions(generated.get("misconceptions")),
            "check_bank": _clean_check_bank(generated.get("check_bank")),
            "numeric_anchors": generated.get("numeric_anchors") or {},
            "widget_hints": _clean_widget_hints(generated.get("widget_hints")),
            "source_kb_ids": concept.kb_ids,
            "status": status,
            "_thin": thin,
            "_violations": failures.get(concept.slug, []),
            "_unsupported": [
                str(claim) for claim in (generated.get("unsupported_claims") or [])
            ],
        }
        records.append(record)
        next_index += 1

    logger.info(
        "Pass E: %d concepts (%d draft, %d needs_review).",
        len(records),
        sum(1 for r in records if r["status"] == "draft"),
        sum(1 for r in records if r["status"] == "needs_review"),
    )

    if write:
        if embed:
            try:
                await _embed_records(records)
            except Exception:
                # The bodies are already generated and validated.
                logger.warning(
                    "Embedding failed; writing %d concepts WITHOUT vectors. "
                    "Resolution will fall back to lexical matching until "
                    "`--from e` is re-run.",
                    len(records),
                    exc_info=True,
                )
        await _upsert(records)

    _write_review_csv(records)
    return records


_WIDGET_KINDS = frozenset(
    {
        "simulator", "growth_stack", "compare", "sort_buckets", "allocator",
        "flow_diagram", "timeline", "reveal_cards", "proportion",
    }
)


def _clean_widget_hints(raw: Any) -> list[str]:
    return [str(kind).strip() for kind in (raw or []) if str(kind).strip() in _WIDGET_KINDS][:4]


def _clean_misconceptions(raw: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        wrong = str(entry.get("wrong") or "").strip()
        right = str(entry.get("right") or "").strip()
        if wrong and right:
            out.append({"wrong": wrong, "right": right})
    return out[:4]


_CHECK_TYPES = frozenset({"numeric", "multiple_choice", "short_answer", "true_false"})
_CHECK_BANDS = frozenset({"5_8", "9_12", "13_15", "16_18", "adult"})


def _clean_check_bank(raw: Any) -> list[dict[str, Any]]:
    """Keep the well-formed items and drop the rest."""
    out: list[dict[str, Any]] = []
    for index, entry in enumerate(raw or [], start=1):
        if not isinstance(entry, dict):
            continue
        question = str(entry.get("question") or "").strip()
        answer = str(entry.get("answer") or "").strip()
        if not question or not answer:
            continue
        band = str(entry.get("band") or "").strip().replace("-", "_")
        if band not in _CHECK_BANDS:
            continue
        kind = str(entry.get("type") or "short_answer").strip()
        if kind not in _CHECK_TYPES:
            kind = "short_answer"
        hints = [str(hint).strip() for hint in (entry.get("hints") or []) if str(hint).strip()]
        accept = [str(a).strip() for a in (entry.get("accept") or []) if str(a).strip()]
        if answer not in accept:
            accept.append(answer)
        out.append(
            {
                "id": str(entry.get("id") or f"chk_{index}"),
                "band": band,
                "type": kind,
                "question": question,
                "answer": answer,
                "accept": accept[:8],
                "hints": hints[:3],
                "explanation_on_correct": str(entry.get("explanation_on_correct") or "").strip(),
                "explanation_on_wrong": str(entry.get("explanation_on_wrong") or "").strip(),
            }
        )
    return out


async def _embed_records(records: list[dict[str, Any]]) -> None:
    """Embed title + aliases + the 9-12 body, with the product's embedding model."""
    from app.learning.concepts import TeachingConcept

    from app.rag import get_embeddings

    embeddings = get_embeddings()
    texts = []
    for record in records:
        concept = TeachingConcept.from_row(record)
        texts.append(concept.embedding_text())

    logger.info("Pass E: embedding %d concepts.", len(texts))
    vectors = await embeddings.aembed_documents(texts)
    for record, vector in zip(records, vectors, strict=False):
        record["embedding"] = vector


_UPSERT = """
INSERT INTO concepts (
    id, slug, locale, name, title, domain, band_min, band_max, aliases,
    body_5_8, body_9_12, body_13_15, body_16_18, body_adult,
    local_example, misconceptions, check_bank, numeric_anchors,
    widget_hints, source_kb_ids, status, embedding, vocabulary
) VALUES (
    :id, :slug, :locale, :title, :title, :domain, :band_min, :band_max, :aliases,
    :body_5_8, :body_9_12, :body_13_15, :body_16_18, :body_adult,
    :local_example, CAST(:misconceptions AS jsonb), CAST(:check_bank AS jsonb),
    CAST(:numeric_anchors AS jsonb),
    :widget_hints, :source_kb_ids, :status, CAST(:embedding AS vector), '{}'
)
ON CONFLICT (slug, locale) DO UPDATE SET
    title = EXCLUDED.title,
    name = EXCLUDED.name,
    domain = EXCLUDED.domain,
    band_min = EXCLUDED.band_min,
    band_max = EXCLUDED.band_max,
    aliases = EXCLUDED.aliases,
    body_5_8 = EXCLUDED.body_5_8,
    body_9_12 = EXCLUDED.body_9_12,
    body_13_15 = EXCLUDED.body_13_15,
    body_16_18 = EXCLUDED.body_16_18,
    body_adult = EXCLUDED.body_adult,
    local_example = EXCLUDED.local_example,
    misconceptions = EXCLUDED.misconceptions,
    check_bank = EXCLUDED.check_bank,
    numeric_anchors = EXCLUDED.numeric_anchors,
    widget_hints = EXCLUDED.widget_hints,
    source_kb_ids = EXCLUDED.source_kb_ids,
    status = EXCLUDED.status,
    embedding = EXCLUDED.embedding
"""


async def _upsert(records: list[dict[str, Any]]) -> None:
    """Write every concept."""
    from sqlalchemy import text

    from app.db.engine import get_sessionmaker

    maker = get_sessionmaker()
    if maker is None:
        logger.error("No database configured; nothing written.")
        return

    statement = text(_UPSERT)
    async with maker() as session:
        for record in records:
            payload = {
                key: value
                for key, value in record.items()
                if not key.startswith("_") and key != "embedding"
            }
            payload["misconceptions"] = json.dumps(record["misconceptions"])
            payload["check_bank"] = json.dumps(record["check_bank"])
            payload["numeric_anchors"] = json.dumps(record["numeric_anchors"])
            vector = record.get("embedding")
            payload["embedding"] = (
                "[" + ",".join(f"{value:.7f}" for value in vector) + "]" if vector else None
            )
            await session.execute(statement, payload)
        await session.commit()
    logger.info("Pass E: %d concepts written.", len(records))


# ── deliverables ─────────────────────────────────────────────────────────────


def _write_review_csv(records: list[dict[str, Any]]) -> None:
    path = LEARNING / "concepts-review.csv"
    columns = [
        "id", "slug", "title", "domain", "band_min", "band_max", "status",
        "source_kb_ids", "aliases", "widget_hints", "check_items",
        "body_5_8", "body_9_12", "body_13_15", "body_16_18", "body_adult",
        "local_example", "misconceptions", "numeric_anchors", "review_note",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for record in records:
            note = []
            if record["_thin"]:
                note.append(f"only {len(record['source_kb_ids'])} source row(s)")
            note.extend(record["_violations"])
            writer.writerow(
                {
                    **{key: record.get(key, "") for key in columns if key in record},
                    "source_kb_ids": " ".join(record["source_kb_ids"]),
                    "aliases": " | ".join(record["aliases"]),
                    "widget_hints": " ".join(record["widget_hints"]),
                    "check_items": len(record["check_bank"]),
                    "misconceptions": json.dumps(record["misconceptions"], ensure_ascii=False),
                    "numeric_anchors": json.dumps(record["numeric_anchors"], ensure_ascii=False),
                    "review_note": "; ".join(note),
                }
            )
    logger.info("Wrote %s", path)


def _write_kb_gaps(records: list[dict[str, Any]]) -> None:
    """The authoring backlog: what the model wanted to teach and could not source."""
    path = LEARNING / "KB-GAPS.md"
    with_gaps = [record for record in records if record["_unsupported"]]
    total = sum(len(record["_unsupported"]) for record in with_gaps)

    lines = [
        "# KB gaps — the authoring backlog",
        "",
        "Every entry below is something the body generator wanted to say and left out",
        "because no source row supported it. This is not a list of errors; it is a list",
        "of facts the ASPIRE knowledge base does not yet contain, discovered by trying to",
        "teach from it.",
        "",
        "For the task force: each line is a candidate KB row. A line marked **PROGRAMME**",
        "needs an authoritative source (policy document, task-force decision) before it can",
        "be written — these are claims about ASPIRE itself, which is where a wrong answer",
        "costs the most.",
        "",
        f"**{total} gaps across {len(with_gaps)} concepts.**",
        "",
    ]
    for record in sorted(with_gaps, key=lambda r: -len(r["_unsupported"])):
        lines.append(f"## {record['title']} (`{record['slug']}`, {record['id']})")
        lines.append("")
        lines.append(
            f"Domain `{record['domain']}` · bands {record['band_min']}–{record['band_max']} · "
            f"status `{record['status']}` · built from "
            f"{len(record['source_kb_ids'])} row(s): "
            f"{', '.join(record['source_kb_ids'][:12]) or '—'}"
        )
        lines.append("")
        for claim in record["_unsupported"]:
            flag = "**PROGRAMME** " if _PROGRAMME_TERMS.search(claim) else ""
            lines.append(f"- {flag}{claim}")
        lines.append("")

    if not with_gaps:
        lines.append("_No unsupported claims were reported. Either the corpus is complete for")
        lines.append("these concepts, or Pass C was not run._")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s", path)


# ── plumbing ─────────────────────────────────────────────────────────────────


async def _gather_limited(coroutines: Sequence[Any], limit: int) -> list[Any]:
    """`asyncio.gather` with a concurrency ceiling."""
    semaphore = asyncio.Semaphore(limit)

    async def guarded(coroutine: Any) -> Any:
        async with semaphore:
            return await coroutine

    return await asyncio.gather(*(guarded(coroutine) for coroutine in coroutines))


def _checkpoint(name: str) -> Path:
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    return CHECKPOINTS / f"pass_{name}.json"


def _save(name: str, payload: Any) -> None:
    _checkpoint(name).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("Checkpoint pass_%s written.", name)


def _load(name: str) -> Any | None:
    path = _checkpoint(name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        logger.warning("Checkpoint pass_%s is corrupt; ignoring it.", name)
        return None


_PASSES = ("a", "b", "c", "d", "e")


async def run(args: argparse.Namespace) -> int:
    rows = load_kb()
    logger.info("Knowledge base: %d rows (%d ASP-, %d FIN-).",
                len(rows),
                sum(1 for row in rows if row.is_programme),
                sum(1 for row in rows if not row.is_programme))

    start = _PASSES.index(args.start)

    if args.dry_run:
        print(_dry_run_plan(rows, args))
        return 0

    models = Models(strong=args.strong_model, cheap=args.cheap_model)

    # ── A ────────────────────────────────────────────────────────────────────
    taxonomy_raw = None if args.force else _load("a")
    if start <= 0 or taxonomy_raw is None:
        taxonomy = await pass_a(models, rows)
        _save("a", [asdict(concept) for concept in taxonomy])
    else:
        taxonomy = [ProposedConcept(**entry) for entry in taxonomy_raw]
        logger.info("Pass A: resumed %d concepts from checkpoint.", len(taxonomy))
    (LEARNING / "taxonomy.json").write_text(
        json.dumps([asdict(concept) for concept in taxonomy], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # ── B ────────────────────────────────────────────────────────────────────
    assigned_raw = None if args.force else _load("b")
    if start <= 1 or assigned_raw is None:
        taxonomy = await pass_b(models, rows, taxonomy)
        _save("b", [asdict(concept) for concept in taxonomy])
    else:
        taxonomy = [ProposedConcept(**entry) for entry in assigned_raw]
        logger.info("Pass B: resumed assignments from checkpoint.")

    report = coverage_report(rows, taxonomy)
    logger.info(
        "Coverage: %s%% of rows assigned (%d orphans). %d concepts, %d thin, %d starved.",
        report["coverage_pct"],
        len(report["orphan_ids"]),
        report["concepts"],
        len(report["thin_concepts"]),
        len(report["starved_concepts"]),
    )
    (LEARNING / "taxonomy.json").write_text(
        json.dumps(
            {"coverage": report, "concepts": [asdict(c) for c in taxonomy]},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # ── C ────────────────────────────────────────────────────────────────────
    bodies_raw = None if args.force else _load("c")
    if start <= 2 or bodies_raw is None:
        bodies = await pass_c(models, taxonomy, rows, args.limit)
        _save("c", bodies)
    else:
        bodies = bodies_raw
        logger.info("Pass C: resumed %d bodies from checkpoint.", len(bodies))

    # ── D ────────────────────────────────────────────────────────────────────
    bodies, failures = await pass_d(models, taxonomy, bodies, rows, offline=args.no_retry)
    _save("d", {"bodies": bodies, "failures": failures})
    logger.info("Pass D: %d concept(s) carry surviving violations.", len(failures))

    # ── E ────────────────────────────────────────────────────────────────────
    records = await pass_e(
        taxonomy, bodies, failures, write=not args.no_write, embed=not args.no_embed
    )
    _write_kb_gaps(records)

    servable = sum(1 for record in records if record["status"] == "draft")
    logger.info(
        "Done. %d concepts, %d servable, %d model calls.",
        len(records),
        servable,
        models.calls,
    )
    return 0


def _dry_run_plan(rows: list[KBRow], args: argparse.Namespace) -> str:
    batches_a = (len(rows) + TAXONOMY_BATCH - 1) // TAXONOMY_BATCH
    batches_b = (len(rows) + ASSIGN_BATCH - 1) // ASSIGN_BATCH
    estimate = 55 if not args.limit else args.limit
    lines = [
        "seed_concepts.py --dry-run: the plan, no calls made and nothing written.",
        "",
        f"  knowledge base      {len(rows)} rows from {KB_CSV.relative_to(REPO)}",
        f"                      {sum(1 for r in rows if r.is_programme)} ASP-, "
        f"{sum(1 for r in rows if not r.is_programme)} FIN-",
        f"  strong model        {args.strong_model}",
        f"  cheap model         {args.cheap_model}",
        f"  concurrency         {CONCURRENCY}",
        "",
        f"  Pass A  taxonomy    {batches_a} calls ({TAXONOMY_BATCH} questions each)  [{args.strong_model}]",
        f"  Pass B  assignment  {batches_b} calls ({ASSIGN_BATCH} rows each)       [{args.cheap_model}]",
        f"  Pass C  bodies      ~{estimate} calls (one per concept)         [{args.strong_model}]",
        "  Pass D  grounding    0 calls, plus one retry per failing concept",
        "  Pass E  embed+write  1 embedding batch, 1 transaction",
        "",
        f"  estimated model calls   ~{batches_a + batches_b + estimate}",
        "",
        "  writes:",
        f"    {(LEARNING / 'taxonomy.json').relative_to(REPO)}",
        f"    {(LEARNING / 'concepts-review.csv').relative_to(REPO)}",
        f"    {(LEARNING / 'KB-GAPS.md').relative_to(REPO)}",
        f"    {CHECKPOINTS.relative_to(REPO)}/pass_{{a,b,c,d}}.json",
        "    postgres: concepts (upsert on slug, locale)",
        "",
        "  acceptance targets: >=40 concepts, >=90% of rows assigned, 0 grounding escapes.",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="report the plan; call nothing")
    parser.add_argument("--from", dest="start", choices=_PASSES, default="a",
                        help="resume at this pass, reading earlier checkpoints")
    parser.add_argument("--force", action="store_true", help="ignore checkpoints")
    parser.add_argument("--limit", type=int, default=None,
                        help="generate bodies for only the first N concepts")
    parser.add_argument("--no-write", action="store_true",
                        help="run every pass but do not touch the database")
    parser.add_argument("--no-retry", action="store_true",
                        help="Pass D nulls failing bodies without regenerating")
    parser.add_argument("--no-embed", action="store_true",
                        help="write concepts without vectors; resolution falls back to lexical")
    parser.add_argument("--strong-model", default=os.environ.get("SEED_STRONG_MODEL", "gpt-5.5"))
    parser.add_argument("--cheap-model", default=os.environ.get("SEED_CHEAP_MODEL", "gpt-4o"))
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)

    try:
        from dotenv import load_dotenv

        load_dotenv(BACKEND / ".env")
    except ImportError:  # pragma: no cover
        pass

    LEARNING.mkdir(parents=True, exist_ok=True)
    return asyncio.run(run(args))


if __name__ == "__main__":
    raise SystemExit(main())
