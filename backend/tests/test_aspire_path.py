"""ASPIRE Path: it must be true, quiet, and unable to cost anybody an answer."""

from __future__ import annotations

import pytest

from app.graph.path import STAGES, emit, labels, should_show, title, visible_index


class TestTheStagesAreTheReadersNotTheGraphs:
    @pytest.mark.parametrize("persona", ["stella", "kaleb", "orion", "aurora", "nova", "guest"])
    @pytest.mark.parametrize("locale", ["en", "es", "fr"])
    def test_every_guide_speaks_every_language(self, persona, locale):
        names = labels(persona, locale)
        assert names, f"{persona}/{locale} has no stages"
        assert all(name.strip() for name in names)

    @pytest.mark.parametrize("persona", ["stella", "kaleb", "orion", "aurora", "nova", "guest"])
    def test_no_more_than_four_and_no_fewer_than_three(self, persona):
        """A reader glancing at a strip reads four things and skims six."""
        assert 3 <= len(labels(persona, "en")) <= 4

    def test_no_stage_ever_names_the_machinery(self):
        """A reader is shown the work, never the graph."""
        forbidden = (
            "classif", "retriev", "rerank", "node", "agent", "llm", "model",
            "token", "prompt", "score", "embedding", "vector", "tool call",
        )
        for persona in ("stella", "kaleb", "orion", "aurora", "nova", "guest"):
            for locale in ("en", "es", "fr"):
                for name in labels(persona, locale):
                    lowered = name.lower()
                    for word in forbidden:
                        assert word not in lowered, f"{persona}/{locale}: {name!r}"

    def test_an_unknown_guide_falls_back_rather_than_failing(self):
        assert labels("nobody", "en") == labels("guest", "en")
        assert labels("orion", "de") == labels("orion", "en")

    def test_the_title_is_translated_too(self):
        assert title("es") != title("en")
        assert title("fr") != title("en")


class TestItErrsTowardsSilence:
    def test_a_plain_question_to_a_non_agentic_agent_shows_nothing(self):
        assert should_show({"active_agent": "servicing_agent"}) is False
        assert should_show({"active_agent": "escalate_agent"}) is False

    def test_a_story_shows_nothing(self):
        """One long generation is not a sequence of steps."""
        assert should_show({"active_agent": "qa_agent", "story_topic": "saving"}) is False
        assert should_show({"active_agent": "qa_agent", "story_arc": {"beat": 2}}) is False

    def test_the_multi_step_agents_do_show(self):
        for agent in ("qa_agent", "learn_agent", "register_agent", "register_agent_step1"):
            assert should_show({"active_agent": agent}) is True

    def test_no_agent_at_all_shows_nothing(self):
        assert should_show({}) is False


class TestItCannotCostAnybodyAnAnswer:
    def test_emitting_outside_a_graph_run_is_a_no_op(self):
        """There is no stream writer under test, and that must be fine."""
        emit({"active_agent": "qa_agent", "persona": "orion"}, "aim")

    def test_an_unknown_stage_is_logged_not_raised(self, caplog):
        emit({"active_agent": "qa_agent"}, "not_a_stage")
        assert "Unknown Path stage" in caplog.text

    def test_every_wired_stage_name_is_real(self):
        """A typo in a call site would silently stop that stage appearing."""
        for stage in ("aim", "source", "plan", "interact", "recommend", "enable"):
            assert stage in STAGES


# ── the vocabulary, which is a decision and not an accident ──────────────────


class TestThePathIsNotCalledASpine:
    """Five things here are already called a spine and they agree about what
    the word means: a governing contract about how ASPIRE SPEAKS to a
    particular audience -- the Voice Spine (the client's own source of truth),
    the Educator Spine, the Hook Spine, the Adult Learner spine, and
    `teach._spine()`.

    The Path is about what ASPIRE DOES. A sixth meaning, and the first that is
    not about speech, would cost the other five their precision -- and the
    Voice Spine arrives from the client, so the word is not ours to widen.

    This is the kind of thing that drifts back in one careless docstring, which
    is why it is a test rather than a paragraph.
    """

    @staticmethod
    def _sources() -> list[tuple[str, str]]:
        from pathlib import Path as FsPath

        root = FsPath(__file__).resolve().parents[1]
        files = [
            root / "app" / "graph" / "path.py",
            root.parent / "docs" / "ASPIRE_PATH.md",
            root.parent / "frontend" / "src" / "components" / "chat" / "AspirePath.tsx",
        ]
        return [(f.name, f.read_text(encoding="utf-8")) for f in files if f.is_file()]

    def test_the_path_never_calls_itself_one(self):
        for name, text in self._sources():
            for line in text.splitlines():
                lowered = line.lower()
                if "spine" not in lowered:
                    continue
                # Naming the OTHER spines in order to distinguish them is the
                # whole point of the section that does it.
                # Naming an existing spine, or the filename of one, is what
                # the distinguishing section is FOR. What is forbidden is the
                # word attaching to this feature.
                allowed = (
                    "voice spine", "educator spine", "hook spine",
                    "adult learner spine", "_spine()",
                    "hook_spine.md", "educator_spine.md",
                    "aspire_personas.yaml",
                    # The section that exists to say it is not one.
                    "not a spine", "not one of them", "on the word",
                    "already called", "called one", "five things",
                    "sixth meaning", "the word is not ours", "the word means",
                )
                assert any(token in lowered for token in allowed), (
                    f"{name}: {line.strip()!r} uses 'spine' for the Path itself"
                )

    def test_the_stages_spell_the_product(self):
        """The acronym is the asset, and it is why no other noun is needed."""
        assert "".join(stage[0] for stage in STAGES).upper() == "ASPIRE"

    def test_the_last_stage_is_enable_rather_than_execute(self):
        """This assistant is bounded: it can prepare and hand off, never act on
        an account. A stage named for authority it does not have would be the
        one dishonest word in the sequence."""
        assert STAGES[-1] == "enable"
        assert "execute" not in STAGES


# ── the fold, which was wrong in a way only a list could show ────────────────


class TestEveryLabelLightsAndNoneLightsTwice:
    """The first fold spread six stages across the labels arithmetically. Listed
    against the words, `source` landed on "Your goal", `plan` landed on "Facts
    checked", and "Your plan" never lit at all -- so the strip said the facts
    were being checked while the answer was being written."""

    def test_the_stages_land_where_they_belong_for_zion(self):
        names = labels("orion", "en")
        landed = {stage: names[visible_index(stage, len(names))] for stage in STAGES}
        assert landed["aim"] == "Your goal"
        assert landed["source"] == "Facts checked"
        assert landed["plan"] == "Your plan"
        assert landed["enable"] == "Next move"

    @pytest.mark.parametrize("persona", ["stella", "kaleb", "orion", "aurora", "nova", "guest"])
    def test_every_label_is_reachable(self, persona):
        """A label that no stage can light is a promise the strip cannot keep."""
        names = labels(persona, "en")
        reached = {visible_index(stage, len(names)) for stage in STAGES}
        assert reached == set(range(len(names))), (
            f"{persona}: unreachable labels "
            f"{[names[i] for i in range(len(names)) if i not in reached]}"
        )

    @pytest.mark.parametrize("persona", ["stella", "kaleb", "orion", "aurora", "nova", "guest"])
    def test_the_strip_never_goes_backwards(self, persona):
        names = labels(persona, "en")
        indexes = [visible_index(stage, len(names)) for stage in STAGES]
        assert indexes == sorted(indexes), f"{persona}: {indexes}"


class TestEveryStageIsActuallyEmitted:
    """Two of the six were declared and never wired, so a four-label strip could
    only ever light three of them."""

    def test_every_stage_has_a_call_site(self):
        import re
        from pathlib import Path as FsPath

        root = FsPath(__file__).resolve().parents[1] / "app"
        wired: set[str] = set()
        # The whole call, braces and all: one call site passes a dict literal
        # as its first argument, and a naive "up to the first comma" pattern
        # reported `aim` as unwired when it is the best-wired stage there is.
        call = re.compile(r"emit_path\((?:[^()]|\([^()]*\)|\{[^{}]*\})*\)", re.S)
        for source in root.rglob("*.py"):
            text = source.read_text(encoding="utf-8")
            for match in call.finditer(text):
                wired.update(set(re.findall(r'"(\w+)"', match.group(0))) & set(STAGES))
        assert set(STAGES) <= wired, f"declared but never emitted: {sorted(set(STAGES) - wired)}"


class TestKalebIsDescribedByHisWorkNotHisReply:
    """"The answer" lit while the router was still choosing who would answer --
    a progress strip claiming a thing exists before it does."""

    def test_the_first_label_does_not_claim_the_answer_exists(self):
        first = labels("kaleb", "en")[0].lower()
        assert first != "the answer"
        assert "finding" in first

    def test_his_rhythm_survives(self):
        """Answer, reason, challenge -- still in that order, every time."""
        names = [n.lower() for n in labels("kaleb", "en")]
        assert "answer" in names[0]
        assert "why" in names[1] or "reason" in names[1]
        assert "challenge" in names[2]


class TestEveryReaderSeesIt:
    """The Path must not depend on having an account.

    Observed on production, 27 Aug: an anonymous session streamed `directive`,
    `token` and `done` and nothing else -- no Path frame reached the client at
    all. `should_show` listed `qa_agent` and not the two variants everybody
    else is actually routed to, so the strip appeared only for a reader with a
    proven identity. Every first visit, and every anonymous evaluation of this
    product, saw an answer arrive with no sign that anything had been worked
    out. The capability was there and invisible, which is indistinguishable
    from not having it.
    """

    #: The three names `access.py` routes readers to, by identity.
    QA_AGENTS = ("qa_agent", "qa_agent_limited", "qa_agent_public")

    @pytest.mark.parametrize("agent", QA_AGENTS)
    def test_every_qa_variant_earns_a_path(self, agent):
        assert should_show({"active_agent": agent}) is True

    def test_the_anonymous_reader_is_not_the_exception(self):
        """`qa_agent_public` is what a reader with no account gets."""
        from app.graph.access import _ANONYMOUS

        served = [a for a in _ANONYMOUS if a.startswith("qa_agent")]
        assert served, "anonymous readers reach no QA agent at all"
        for agent in served:
            assert should_show({"active_agent": agent}) is True, (
                f"{agent} is what an anonymous reader gets and it shows no Path"
            )

    def test_the_youngest_reader_is_not_the_exception(self):
        """Skye is routed to `qa_agent_limited`, and five-year-olds count."""
        from app.graph.access import _STELLA

        served = [a for a in _STELLA if a.startswith("qa_agent")]
        for agent in served:
            assert should_show({"active_agent": agent}) is True

    def test_silence_still_means_silence(self):
        """Widening the allowlist must not have turned the quiet cases on."""
        for agent in ("servicing_agent", "escalate_agent", ""):
            assert should_show({"active_agent": agent}) is False
        assert should_show({"active_agent": "qa_agent_public", "story_arc": {"beat": 1}}) is False
        assert should_show({"active_agent": "qa_agent_public", "story_topic": "saving"}) is False
