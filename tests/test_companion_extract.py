import pytest

from memory_machine.companion_memory import CompanionMemory
from memory_machine.tape import MemoryRecord


def _question(memory, turn_id, text):
    return memory.tape.append(MemoryRecord(
        type="question", summary=text, why=text, source=f"companion#{turn_id}",
    ))


def test_report_has_turn_provenance_and_cascades_with_source(tmp_path):
    memory = CompanionMemory(tmp_path)
    turn = _question(memory, "u-41", "I am composing for my sister.")
    report = memory.add_candidate(
        {"type": "person_report", "summary": "composing for sister",
         "quote": "composing for my sister"},
        author="person", turn_id="u-41", source_text=turn.why,
        source_memory_id=turn.id,
    )
    assert report.source == "u-41"
    assert report.origin["turn_ids"] == ["u-41"]
    assert report.derived_from == [turn.id]
    assert report.type == "person_report"
    assert set(memory.delete(turn.id)) == {turn.id, report.id}


def test_hypothesis_remains_tentative_and_requires_review(tmp_path):
    memory = CompanionMemory(tmp_path)
    turn = _question(memory, "u-42", "I like shorter questions.")
    hypothesis = memory.add_candidate(
        {"type": "hypothesis", "summary": "possibly prefers concise questions",
         "quote": "shorter questions", "confidence": 0.6,
         "review_at": "2026-10-24T00:00:00+00:00"},
        author="system", turn_id="u-42", source_text=turn.why,
        source_memory_id=turn.id,
    )
    assert hypothesis.type == "hypothesis"
    assert hypothesis.origin["confidence"] == 0.6
    with pytest.raises(ValueError, match="preserves"):
        memory.supersede(hypothesis.id, MemoryRecord(
            type="person_report", summary="prefers concise questions",
        ))


@pytest.mark.parametrize("change", [
    {"quote": "I never said this"},
    {"confidence": 1.1},
    {"confidence": float("nan")},
    {"review_at": ""},
])
def test_invalid_hypotheses_do_not_write(tmp_path, change):
    memory = CompanionMemory(tmp_path)
    turn = _question(memory, "u-43", "Maybe I like short questions.")
    proposal = {
        "type": "hypothesis", "summary": "may prefer short questions",
        "quote": "short questions", "confidence": 0.5,
        "review_at": "2026-10-24T00:00:00+00:00",
    }
    proposal.update(change)
    with pytest.raises(ValueError):
        memory.add_candidate(
            proposal, author="system", turn_id="u-43", source_text=turn.why,
            source_memory_id=turn.id,
        )
    assert len(memory.tape.read()) == 1


def test_persona_and_story_keep_fictional_origin(tmp_path):
    memory = CompanionMemory(tmp_path)
    persona = memory.add_candidate(
        {"type": "persona", "summary": "Lia plays guitar", "approved_version": "v1"},
        author="joint",
    )
    turn = _question(memory, "u-44", "In our story, we visited a library.")
    story = memory.add_candidate(
        {"type": "story", "summary": "visited fictional library",
         "quote": "we visited a library", "event_id": "e1"},
        author="joint", turn_id="u-44", source_text=turn.why,
        source_memory_id=turn.id,
    )
    assert persona.origin == {"kind": "persona_revision", "version": "v1"}
    assert story.origin["kind"] == "story_event"
    assert story.origin["event_id"] == "e1"


def test_episode_uses_real_turn_and_forged_source_text_is_rejected(tmp_path):
    memory = CompanionMemory(tmp_path)
    turn = _question(memory, "u-46", "We made a melody together.")
    episode = memory.add_candidate(
        {"type": "episode", "summary": "discussed a melody",
         "quote": "made a melody together"},
        author="joint", turn_id="u-46", source_text=turn.why,
        source_memory_id=turn.id,
    )
    assert episode.origin["kind"] == "turn"
    with pytest.raises(ValueError, match="source turn slot"):
        memory.add_candidate(
            {"type": "episode", "summary": "visited a castle",
             "quote": "visited a castle"},
            author="joint", turn_id="u-46",
            source_text="We visited a castle.", source_memory_id=turn.id,
        )


def test_rejects_cross_root_turn_and_wrong_author(tmp_path):
    first = CompanionMemory(tmp_path / "person-a")
    second = CompanionMemory(tmp_path / "person-b")
    turn = _question(first, "u-45", "I compose music.")
    proposal = {"type": "person_report", "summary": "composes music",
                "quote": "compose music"}
    with pytest.raises(ValueError, match="source turn slot"):
        second.add_candidate(
            proposal, author="person", turn_id="u-45", source_text=turn.why,
            source_memory_id=turn.id,
        )
    with pytest.raises(ValueError, match="invalid author"):
        first.add_candidate(
            proposal, author="system", turn_id="u-45", source_text=turn.why,
            source_memory_id=turn.id,
        )
