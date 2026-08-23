"""Kaleb sits between Skye and Zion, and no answer is also a wire key.

Two rules the seed banks have to keep, both learned the hard way while writing
Kaleb's second and third sets.
"""

from __future__ import annotations

import inspect
import re
import statistics

import pytest

from app.domain import Language, Persona


def _game():
    from app.games import scramble

    cls = next(
        obj
        for obj in vars(scramble).values()
        if inspect.isclass(obj) and hasattr(obj, "sets_for")
    )
    return cls()


def _words(persona: Persona) -> set[str]:
    return {
        entry.word
        for game_set in _game().sets_for(Language.EN)
        for entry in game_set.entries
        if persona in entry.persona_bands
    }


def _syllables(word: str) -> int:
    return max(1, len(re.findall(r"[AEIOUY]+", word)))


class TestKalebSitsBetween:
    """The client's rule, stated on 23 August 2026: Kaleb's words should be
    "harder than Skye and not as hard as Zion".

    Measured when that was said: Skye 4.5 letters, Kaleb 5.7, Zion 6.6 -- the
    right shape on average, and wrong in the particulars. Kaleb shared EARN and
    SPEND with the five-to-eights, which are the two easiest words in that bank,
    and carried OWE and OWN at three letters -- shorter than Skye's AVERAGE, and
    barely a puzzle once scrambled.

    These check the shape, not the individual words, so the bank can be rewritten
    without rewriting the test.
    """

    def test_the_words_get_longer_with_the_band(self):
        lengths = {
            persona: statistics.mean(len(w) for w in _words(persona))
            for persona in (Persona.STELLA, Persona.KALEB, Persona.ORION)
        }
        assert lengths[Persona.STELLA] < lengths[Persona.KALEB] < lengths[Persona.ORION], (
            f"the gradient broke: Skye {lengths[Persona.STELLA]:.1f}, "
            f"Kaleb {lengths[Persona.KALEB]:.1f}, Zion {lengths[Persona.ORION]:.1f}"
        )

    def test_and_harder_to_say(self):
        syllables = {
            persona: statistics.mean(_syllables(w) for w in _words(persona))
            for persona in (Persona.STELLA, Persona.KALEB, Persona.ORION)
        }
        assert (
            syllables[Persona.STELLA]
            < syllables[Persona.KALEB]
            <= syllables[Persona.ORION]
        )

    def test_kaleb_is_nearer_the_middle_than_either_end(self):
        """Not merely between them — actually between them.

        A bank that crept to 6.5 would still satisfy the ordering above while
        being Zion's in all but name, which is the failure this guards.
        """
        skye = statistics.mean(len(w) for w in _words(Persona.STELLA))
        kaleb = statistics.mean(len(w) for w in _words(Persona.KALEB))
        zion = statistics.mean(len(w) for w in _words(Persona.ORION))
        assert kaleb - skye >= 0.8, "Kaleb is not meaningfully harder than Skye"
        assert zion - kaleb >= 0.3, "Kaleb has drifted up into Zion's range"

    def test_no_kaleb_word_is_shorter_than_skyes_average(self):
        """Three letters is a coin toss, not a puzzle."""
        floor = statistics.mean(len(w) for w in _words(Persona.STELLA))
        short = sorted(w for w in _words(Persona.KALEB) if len(w) < floor)
        assert not short, f"{short} are below Skye's own average of {floor:.1f}"

    def test_he_does_not_share_the_easiest_words_with_the_five_year_olds(self):
        """`interest` is the one allowed overlap.

        The client lifted it at 5-8 so ASPIRE could name the thing; Skye gets the
        word without the pricing. Anything else shared means a nine-year-old is
        being handed a five-year-old's puzzle.
        """
        shared = _words(Persona.KALEB) & _words(Persona.STELLA)
        assert shared <= {"INTEREST"}, f"also shared with Skye: {sorted(shared - {'INTEREST'})}"


class TestNoAnswerIsAlsoAWireKey:
    """An answer that is a substring of a field name cannot be guarded.

    `test_no_endpoint_leaks_an_answer_outside_a_reveal` searches the serialised
    payload for each answer. CHOICE failed it -- not because anything leaked, but
    because `choices` is a field in every scramble payload, so the guard cannot
    tell an answer from the protocol naming itself. It is right not to try.

    OPTION fails the same way against `options`; VALUE against `value`, which is
    a quick-reply field and therefore invisible to the games-only leak test --
    it passed by which endpoint happened to be checked, which is not the same as
    being safe.

    So the rule is checked here, against the schemas rather than a remembered
    list: the word moves, never the guard.
    """

    @staticmethod
    def _keys_in(payload) -> set[str]:
        """Every field name that actually appears, at any depth.

        Walks dataclasses and pydantic models as well as dicts: the engine
        returns `StartResult`, a dataclass, and reading only its `__dict__`
        would miss `prompt.choices` -- which is the exact field CHOICE collided
        with, so a walker that stopped at the top level would pass on the bug
        this file exists for.
        """
        import dataclasses

        found: set[str] = set()
        stack = [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                found |= set(node)
                stack.extend(node.values())
            elif isinstance(node, (list, tuple)):
                stack.extend(node)
            elif dataclasses.is_dataclass(node) and not isinstance(node, type):
                fields = {f.name for f in dataclasses.fields(node)}
                found |= fields
                stack.extend(getattr(node, name) for name in fields)
            elif hasattr(node, "model_fields"):
                fields = set(type(node).model_fields)
                found |= fields
                stack.extend(getattr(node, name, None) for name in fields)
        return found

    def _live_keys(self, engine, game_type: str) -> set[str]:
        """The keys a REAL payload for this game carries.

        Read from a started game rather than from every schema in the module.
        The schema-wide version was stricter than the risk: it flagged PLAN, in
        Skye's bank since long before this, because `explanation` contains it --
        and `explanation` belongs to the true/false payload, which a scramble
        never returns. A guard that fails on a word that cannot collide teaches
        people to edit the guard.
        """
        found = set(self._keys_in(engine.start("keys-probe", game_type=game_type)))
        # EVERY NON-REVEAL PAYLOAD, not just the first.
        #
        # A reveal is exempt by design -- `test_no_endpoint_leaks_an_answer
        # OUTSIDE a reveal` says so in its name, because the reveal is where the
        # answer is supposed to be. That exemption is why PLAN survives
        # `explanation`: the field only appears inside a reveal, and by then the
        # word is already on screen.
        #
        # CHOICE was different. `choices` rides in `prompt`, which is on every
        # payload from the first one onward, so it collides while the puzzle is
        # still unsolved. Probing only `start` came within one field of missing
        # the hint and wrong-answer shapes, which carry `text` and
        # `teaching_note` and are just as unsolved.
        for _ in range(3):
            found |= self._keys_in(engine.hint("keys-probe"))
        found |= self._keys_in(engine.submit("keys-probe", "definitely-not-it"))
        # Plus the directive fields a turn carrying a game also puts on the wire.
        return found | {"options", "label", "value", "quick_replies", "citations"}

    def test_no_scramble_answer_collides(self, engine):
        keys = self._live_keys(engine, "word_scramble")
        offenders = []
        for language in Language:
            for game_set in _game().sets_for(language):
                for entry in game_set.entries:
                    hit = [k for k in keys if entry.word.lower() in k.lower()]
                    if hit:
                        offenders.append(f"{entry.word} in {hit}")
        assert not offenders, (
            "these answers are substrings of wire field names, so the leak guard "
            f"cannot distinguish them from the protocol: {offenders}"
        )

    def test_the_key_set_is_not_empty(self, engine):
        """A guard reading zero keys would pass on everything."""
        assert len(self._live_keys(engine, "word_scramble")) > 10

    def test_it_would_still_catch_the_word_that_started_this(self, engine):
        """CHOICE, against a live payload — the case this exists for."""
        keys = self._live_keys(engine, "word_scramble")
        assert any("choice" in k.lower() for k in keys)
        assert any("value" in k.lower() for k in keys)
