"""Seed content checks."""

from __future__ import annotations

import pytest

from app.games.config import GameSettings
from app.games.loader import SeedError, load_sets
from app.games.models import Language, Persona
from app.games.normalise import letters_of, normalise
from app.games.scramble import WordScrambleGame

# The ECCB handout, verbatim.
CLIENT_HANDOUT = {
    "MONEY": "NOEYM",
    "INTEREST": "STERINTE",
    "INVEST": "SNEVIT",
    "SAVE": "EASV",
}


def all_entries(game: WordScrambleGame):
    return [
        (game_set, entry)
        for language in Language
        for game_set in game.sets_for(language)
        for entry in game_set.entries
    ]


def test_every_scramble_unscrambles_to_its_word(game):
    """The single most embarrassing possible bug, caught in CI."""
    for game_set, entry in all_entries(game):
        assert letters_of(entry.scramble) == letters_of(entry.word), (
            f"{game_set.id}/{entry.id}: {entry.scramble!r} is not an anagram of "
            f"{entry.word!r} — this puzzle cannot be solved"
        )


def test_no_scramble_is_just_the_word(game):
    for _, entry in all_entries(game):
        assert normalise(entry.scramble) != normalise(entry.word)


def test_client_handout_is_seeded_verbatim(game):
    seeded = {
        entry.word: entry.scramble
        for game_set, entry in all_entries(game)
        if game_set.id == "warmup-01"
    }
    assert seeded == CLIENT_HANDOUT


def test_warmup_set_is_four_words_in_handout_order(game):
    """The handout is a printed sequence, and it still leads.

    This used to assert there was exactly ONE English scramble set, which made
    the handout contract and the size of the word bank the same statement -- so
    adding any word to the game failed a test about the ECCB sheet. The contract
    worth keeping is narrower: the four printed words, in the printed order, in
    their own set, served before anything authored later.
    """
    sets = game.sets_for(Language.EN)
    handout = next(s for s in sets if s.id == "warmup-01")
    words = [e.word for e in handout.entries]
    assert words == ["MONEY", "INTEREST", "INVEST", "SAVE"]
    # The engine walks sets in load order and the handout must come first, or a
    # child meets a later bank before the sheet they were given in class.
    assert sets[0].id == "warmup-01"


def test_the_word_bank_is_tiered_by_persona(game):
    """Every set beyond the handout targets one audience, not all of them."""
    for game_set in game.sets_for(Language.EN):
        if game_set.id == "warmup-01":
            continue
        for entry in game_set.entries:
            assert len(entry.persona_bands) == 1, (
                f"{game_set.id}/{entry.id} targets {entry.persona_bands}; a bank "
                "authored for one reading level should not be served to another"
            )


@pytest.mark.parametrize(
    ("persona", "least"),
    [(Persona.STELLA, 8), (Persona.ORION, 8), (Persona.EVERYONE, 6)],
)
def test_each_playing_persona_has_a_bank_worth_playing(game, persona, least):
    """The pool a reader actually draws from, not the total on disk."""
    available = [
        entry
        for game_set in game.sets_for(Language.EN)
        for entry in game_set.entries
        if persona in entry.persona_bands
    ]
    assert len(available) >= least


def test_every_entry_has_teaching_content(game):
    for game_set, entry in all_entries(game):
        where = f"{game_set.id}/{entry.id}"
        assert entry.definition.strip(), f"{where}: no definition to teach from"
        assert entry.hint.strip(), f"{where}: no hint"
        # A hint that contains the answer defeats the whole hint ladder.
        assert normalise(entry.word) not in normalise(entry.hint), (
            f"{where}: the hint gives the word away"
        )
        assert normalise(entry.word) not in normalise(entry.definition), (
            f"{where}: the definition gives the word away"
        )


def test_every_entry_targets_at_least_one_persona(game):
    for _, entry in all_entries(game):
        assert entry.persona_bands
        assert all(isinstance(p, Persona) for p in entry.persona_bands)


def test_spanish_and_french_are_empty_pending_authoring(game):
    """Not a gap — a deliberate refusal to machine-translate a letter puzzle."""
    assert game.sets_for(Language.ES) == []
    assert game.sets_for(Language.FR) == []


# --- loader rejects bad content -------------------------------------------


def _write_set(tmp_path, language: str, body: str):
    folder = tmp_path / language
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "broken.yaml").write_text(body, encoding="utf-8")
    return tmp_path


VALID_BODY = """
id: broken-01
game_type: word_scramble
language: en
title: Test
entries:
  - id: broken-01-a
    language: en
    word: SAVE
    scramble: EASV
    hint: an action word
    definition: putting money aside
    difficulty_band: warmup
    persona_bands: [stella]
"""


def test_loader_accepts_a_well_formed_set(tmp_path):
    root = _write_set(tmp_path, "en", VALID_BODY)
    sets = load_sets(root)
    assert len(sets[Language.EN]) == 1


def test_loader_rejects_a_scramble_that_is_not_an_anagram(tmp_path):
    root = _write_set(tmp_path, "en", VALID_BODY.replace("EASV", "XXXX"))
    with pytest.raises(SeedError, match="not an anagram"):
        load_sets(root)


def test_loader_rejects_a_translated_set(tmp_path):
    """What a translation pass actually produces: right word, wrong letters."""
    translated = VALID_BODY.replace("word: SAVE", "word: AHORRAR").replace(
        "language: en", "language: es"
    )
    root = _write_set(tmp_path, "es", translated)
    with pytest.raises(SeedError, match="not an anagram"):
        load_sets(root)


def test_loader_rejects_a_set_filed_under_the_wrong_language(tmp_path):
    root = _write_set(tmp_path, "en", VALID_BODY.replace("language: en", "language: fr"))
    with pytest.raises(SeedError, match="sits in"):
        load_sets(root)


def test_loader_rejects_an_unknown_persona(tmp_path):
    root = _write_set(tmp_path, "en", VALID_BODY.replace("[stella]", "[teacher]"))
    with pytest.raises(SeedError, match="unknown persona"):
        load_sets(root)


def test_real_seed_directory_loads_clean(settings: GameSettings):
    """The shipped seeds pass every rule above."""
    load_sets(settings.resolved(settings.seed_dir))
