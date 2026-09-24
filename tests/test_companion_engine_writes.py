"""F3b: save-on writes (turn slots + validated extraction) and policies."""

from __future__ import annotations

import json

from test_companion_engine import _handler, _setup

from fakes import FakeClient
from memory_machine.companion_engine import CompanionEngine
from memory_machine.companion_memory import CompanionMemory

MESSAGE = "estou compondo uma música para minha irmã"
LIA_REPLY = "Que bom. Como está a letra?"


def _reply(proposals, used=None):
    trailer = {"used": used or [], "memories": proposals}
    return f"{LIA_REPLY}\n{json.dumps(trailer, ensure_ascii=False)}"


def _by_source(tape, source):
    return next(record for record in tape.read() if record.source == source)


def test_save_writes_slots_and_extraction(tmp_path):
    session, _ids = _setup(tmp_path)
    proposal = {"type": "person_report", "summary": "compõe para a irmã",
                "quote": "compondo uma música para minha irmã",
                "source": "person"}
    client = FakeClient(_handler(_reply([proposal])))
    result = CompanionEngine(session, client).reply(MESSAGE, save=True)

    saved = result["saved"]
    turn = saved["turn_id"]
    question = _by_source(CompanionMemory(session.root).tape, f"companion#{turn}")
    answer = _by_source(CompanionMemory(session.root).tape, f"companion#{turn}-r")
    assert saved["question_slot"] == question.id
    assert saved["reply_slot"] == answer.id
    assert question.type == "question" and question.why == MESSAGE
    assert answer.type == "reply" and answer.derived_from == [question.id]

    extracted = _by_source(CompanionMemory(session.root).tape, turn)
    assert extracted.type == "person_report"
    assert extracted.derived_from == [question.id]
    assert extracted.origin["turn_ids"] == [turn]
    assert extracted.author == "person"
    assert saved["records"] == [extracted.id]
    assert result["violations"] == []
    assert not (session.root / "recall_cache.json").exists()


def test_person_report_must_quote_person(tmp_path):
    session, _ids = _setup(tmp_path)
    proposal = {"type": "person_report", "summary": "algo",
                "quote": "Como está a letra?", "source": "lia"}
    client = FakeClient(_handler(_reply([proposal])))
    result = CompanionEngine(session, client).reply(MESSAGE, save=True)
    assert result["saved"]["records"] == []
    assert result["violations"] == [
        {"kind": "rejected_proposal", "type": "person_report",
         "reason": "person_report must quote the person"},
    ]


def test_episode_may_quote_lia(tmp_path):
    session, _ids = _setup(tmp_path)
    proposal = {"type": "episode", "summary": "a Lia perguntou sobre a letra",
                "quote": "Como está a letra?", "source": "lia"}
    client = FakeClient(_handler(_reply([proposal])))
    result = CompanionEngine(session, client).reply(MESSAGE, save=True)
    saved = result["saved"]
    episode = _by_source(CompanionMemory(session.root).tape, f"{saved['turn_id']}-r")
    assert episode.type == "episode"
    assert episode.derived_from == [saved["reply_slot"]]
    assert result["violations"] == []


def test_persona_proposal_rejected(tmp_path):
    session, _ids = _setup(tmp_path)
    proposal = {"type": "persona", "summary": "Lia odeia chuva",
                "approved_version": "v9"}
    client = FakeClient(_handler(_reply([proposal])))
    result = CompanionEngine(session, client).reply(MESSAGE, save=True)
    assert result["saved"]["records"] == []
    assert result["violations"] == [
        {"kind": "rejected_proposal", "type": "persona",
         "reason": "persona is approved out of band"},
    ]


def test_invalid_quote_skipped_but_slots_written(tmp_path):
    session, _ids = _setup(tmp_path)
    proposal = {"type": "episode", "summary": "inventado",
                "quote": "nós viajamos para o mar", "source": "person"}
    client = FakeClient(_handler(_reply([proposal])))
    result = CompanionEngine(session, client).reply(MESSAGE, save=True)
    assert result["saved"]["records"] == []
    assert result["violations"][0]["kind"] == "rejected_proposal"
    assert "literal quote" in result["violations"][0]["reason"]
    assert result["saved"]["question_slot"]
    assert result["saved"]["reply_slot"]


def test_unknown_type_rejected(tmp_path):
    session, _ids = _setup(tmp_path)
    proposal = {"type": "note", "summary": "x", "quote": "x",
                "source": "person"}
    client = FakeClient(_handler(_reply([proposal])))
    result = CompanionEngine(session, client).reply(MESSAGE, save=True)
    assert result["violations"][0]["kind"] == "rejected_proposal"
    assert result["saved"]["records"] == []


def test_store_request_writes_story(tmp_path):
    session, _ids = _setup(tmp_path)
    message = ("Vamos inventar uma aventura: uma caverna com um mapa. "
               "Guarde isso como nossa história.")
    client = FakeClient(_handler(_reply([])))
    result = CompanionEngine(session, client).reply(message, save=True)

    saved = result["saved"]
    tape = CompanionMemory(session.root).tape
    stories = [record for record in tape.read()
               if record.type == "story"
               and record.derived_from == [saved["question_slot"]]]
    assert len(stories) == 1
    story = stories[0]
    assert (story.origin or {}).get("kind") == "story_event"
    assert story.origin["event_id"] == f"conv-{saved['turn_id']}"
    assert "Guarde isso como nossa história" in story.origin["quote"]
    assert saved["records"] == [story.id]


def test_no_store_request_no_story(tmp_path):
    session, _ids = _setup(tmp_path)
    client = FakeClient(_handler(_reply([])))
    result = CompanionEngine(session, client).reply(MESSAGE, save=True)
    tape = CompanionMemory(session.root).tape
    question_slot = result["saved"]["question_slot"]
    assert not [record for record in tape.read()
                if record.type == "story"
                and record.derived_from == [question_slot]]
    assert result["saved"]["records"] == []


def test_trailer_story_takes_precedence_over_trigger(tmp_path):
    session, _ids = _setup(tmp_path)
    proposal = {"type": "story", "summary": "caverna guardada",
                "quote": "Guarde isso como nossa história.", "event_id": "e9",
                "source": "person"}
    message = ("Vamos inventar uma caverna. "
               "Guarde isso como nossa história.")
    client = FakeClient(_handler(_reply([proposal])))
    result = CompanionEngine(session, client).reply(message, save=True)
    tape = CompanionMemory(session.root).tape
    question_slot = result["saved"]["question_slot"]
    stories = [record for record in tape.read()
               if record.type == "story"
               and record.derived_from == [question_slot]]
    assert len(stories) == 1
    assert stories[0].origin["event_id"] == "e9"
    assert result["saved"]["records"] == [stories[0].id]
