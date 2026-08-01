"""Reads and validates the seed files.

Validation is strict and happens at load, not at play. A malformed set is a
content bug, and the moment to find it is a failing build — not a child staring
at a puzzle that cannot be solved because someone mistyped a letter.

Each game type declares its own required keys and its own checks, dispatched on
the set's `game_type`. The one that earns its place for scramble: every scramble
must be an anagram of its word. The one that earns its place for true/false: a
volatile fact must carry the date someone last confirmed it.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any, Callable

import yaml

from app.games.models import (
    Bullet,
    Closing,
    Entry,
    GameSet,
    Language,
    Persona,
    ScrambleEntry,
    StatementEntry,
    Volatility,
)
from app.games.normalise import letters_of, normalise

logger = logging.getLogger(__name__)

WORD_SCRAMBLE = "word_scramble"
TRUE_FALSE = "true_false"


class SeedError(ValueError):
    """A seed file is malformed. Always fatal — never played around."""


def _require(condition: bool, where: str, message: str) -> None:
    if not condition:
        raise SeedError(f"{where}: {message}")


def _text(raw: dict, key: str, where: str, *, required: bool = True) -> str:
    value = str(raw.get(key, "") or "").strip()
    if required:
        _require(bool(value), where, f"{key} is empty or missing")
    return value


def _common(raw: dict, *, set_language: Language, where: str) -> dict[str, Any]:
    """The fields every game's item carries, whatever the game."""
    entry_id = _text(raw, "id", where)
    where = f"{where} entry {entry_id!r}"

    language = Language(str(raw.get("language", set_language.value)))
    _require(
        language is set_language,
        where,
        f"language {language.value!r} does not match its set ({set_language.value!r})",
    )

    bands_raw = raw.get("persona_bands") or []
    _require(bool(bands_raw), where, "persona_bands is empty")
    try:
        bands = tuple(Persona(str(b)) for b in bands_raw)
    except ValueError as exc:
        raise SeedError(f"{where}: unknown persona in persona_bands — {exc}") from exc

    try:
        volatility = Volatility(str(raw.get("volatility", "stable")))
    except ValueError as exc:
        raise SeedError(f"{where}: unknown volatility — {exc}") from exc

    verified_raw = raw.get("verified_on")
    verified_on: date | None = None
    if verified_raw not in (None, ""):
        if isinstance(verified_raw, date):
            verified_on = verified_raw
        else:
            try:
                verified_on = date.fromisoformat(str(verified_raw))
            except ValueError as exc:
                raise SeedError(
                    f"{where}: verified_on must be YYYY-MM-DD, got {verified_raw!r}"
                ) from exc

    # A volatile item with no date can never be served, which is the safe
    # outcome — but it is almost always an authoring slip, so say so loudly.
    if volatility is Volatility.VOLATILE and verified_on is None:
        logger.warning(
            "%s: marked volatile with no verified_on, so it will never be served.",
            where,
        )

    return {
        "id": entry_id,
        "language": language,
        "difficulty_band": _text(raw, "difficulty_band", where),
        "persona_bands": bands,
        "topic": _text(raw, "topic", where, required=False) or None,
        "volatility": volatility,
        "verified_on": verified_on,
        "source_document": _text(raw, "source_document", where, required=False) or None,
    }


def _scramble_entry(raw: dict, *, set_language: Language, where: str) -> ScrambleEntry:
    common = _common(raw, set_language=set_language, where=where)
    where = f"{where} entry {common['id']!r}"

    word = _text(raw, "word", where)
    scramble = _text(raw, "scramble", where)

    # The check this module exists for.
    _require(
        letters_of(scramble) == letters_of(word),
        where,
        f"scramble {scramble!r} is not an anagram of {word!r} — "
        "letters differ, so the puzzle has no solution",
    )
    _require(
        normalise(scramble) != normalise(word),
        where,
        f"scramble {scramble!r} is identical to the word; that is not a puzzle",
    )

    return ScrambleEntry(
        **common,
        word=word,
        scramble=scramble,
        hint=_text(raw, "hint", where),
        definition=_text(raw, "definition", where),
    )


def _statement_entry(raw: dict, *, set_language: Language, where: str) -> StatementEntry:
    common = _common(raw, set_language=set_language, where=where)
    where = f"{where} entry {common['id']!r}"

    answer = raw.get("answer")
    _require(
        isinstance(answer, bool),
        where,
        f"answer must be true or false, got {answer!r} — quote it in YAML and it "
        "becomes a string, which is not a verdict",
    )

    statement = _text(raw, "statement", where)
    # A statement phrased as a question cannot be judged true or false. This is
    # exactly the defect flagged in item 9 of the ECCB bank.
    _require(
        not statement.rstrip().endswith("?"),
        where,
        "statement ends in a question mark — a true/false item must assert "
        "something, not ask it",
    )

    # Optional layout for teaching that runs longer than a sentence. Absent is
    # normal — `explanation` alone is always enough to render.
    bullets_raw = raw.get("bullets") or []
    bullets = []
    for i, b in enumerate(bullets_raw):
        _require(isinstance(b, dict), where, f"bullet {i} must be a mapping")
        bullets.append(
            Bullet(
                marker=_text(b, "marker", f"{where} bullet {i}"),
                label=_text(b, "label", f"{where} bullet {i}", required=False),
                text=_text(b, "text", f"{where} bullet {i}"),
            )
        )

    paragraphs = tuple(
        str(p).strip() for p in (raw.get("paragraphs") or []) if str(p).strip()
    )

    return StatementEntry(
        **common,
        statement=statement,
        answer=bool(answer),
        explanation=_text(raw, "explanation", where),
        takeaway=_text(raw, "takeaway", where, required=False) or None,
        paragraphs=paragraphs,
        bullets=tuple(bullets),
        after=_text(raw, "after", where, required=False) or None,
        topic_line=_text(raw, "topic_line", where, required=False) or None,
    )


_ENTRY_PARSERS: dict[str, Callable[..., Entry]] = {
    WORD_SCRAMBLE: _scramble_entry,
    TRUE_FALSE: _statement_entry,
}


def _set_from(path: Path) -> GameSet:
    where = path.name
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SeedError(f"{where}: not valid YAML — {exc}") from exc

    _require(isinstance(raw, dict), where, "top level must be a mapping")
    for key in ("id", "game_type", "language", "title", "entries"):
        _require(key in raw, where, f"missing required key {key!r}")

    game_type = str(raw["game_type"]).strip()
    parser = _ENTRY_PARSERS.get(game_type)
    _require(
        parser is not None,
        where,
        f"unknown game_type {game_type!r}; expected one of "
        f"{', '.join(sorted(_ENTRY_PARSERS))}",
    )
    assert parser is not None

    try:
        language = Language(str(raw["language"]))
    except ValueError as exc:
        raise SeedError(f"{where}: unknown language {raw['language']!r}") from exc

    # The folder is the authority: a file claiming `language: es` under en/ is a
    # copy-paste that would otherwise serve Spanish items to English players.
    folder = path.parent.name
    _require(
        folder == language.value,
        where,
        f"declares language {language.value!r} but sits in {folder!r}/",
    )

    entries_raw = raw["entries"] or []
    _require(bool(entries_raw), where, "set has no entries")

    entries = tuple(
        parser(e, set_language=language, where=where) for e in entries_raw
    )

    seen: set[str] = set()
    for entry in entries:
        _require(entry.id not in seen, where, f"duplicate entry id {entry.id!r}")
        seen.add(entry.id)

    closing_raw = raw.get("closing")
    closing = None
    if closing_raw:
        _require(isinstance(closing_raw, dict), where, "closing must be a mapping")
        closing = Closing(
            lead=_text(closing_raw, "lead", f"{where} closing"),
            text=_text(closing_raw, "text", f"{where} closing"),
        )

    return GameSet(
        id=str(raw["id"]).strip(),
        game_type=game_type,
        closing=closing,
        draft=bool(raw.get("draft", False)),
        language=language,
        title=str(raw["title"]).strip(),
        source=str(raw.get("source", "")).strip(),
        entries=entries,
    )


def load_sets(
    seed_dir: Path, *, game_type: str | None = None
) -> dict[Language, list[GameSet]]:
    """Load sets under `seed_dir`, grouped by language.

    Pass `game_type` to load only one game's content. A language folder with no
    matching YAML is normal — that is how the Spanish and French sets sit until
    someone authors them.
    """
    by_language: dict[Language, list[GameSet]] = {lang: [] for lang in Language}
    seen_ids: set[str] = set()

    if not seed_dir.is_dir():
        raise SeedError(f"seed directory does not exist: {seed_dir}")

    for path in sorted(seed_dir.glob("*/*.yaml")):
        game_set = _set_from(path)
        if game_set.id in seen_ids:
            raise SeedError(f"{path.name}: duplicate set id {game_set.id!r}")
        seen_ids.add(game_set.id)
        if game_type is not None and game_set.game_type != game_type:
            continue
        by_language[game_set.language].append(game_set)

    loaded = {lang: sets for lang, sets in by_language.items() if sets}
    logger.info(
        "Loaded %d %s set(s), %d entries: %s",
        sum(len(s) for s in loaded.values()),
        game_type or "game",
        sum(len(s) for sets in loaded.values() for s in sets),
        ", ".join(f"{lang.value}={len(sets)}" for lang, sets in loaded.items())
        or "none",
    )
    return by_language
