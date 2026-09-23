"""Turn slots: paired question/reply records, dedup, pairing, secret gate."""

from __future__ import annotations

from memory_machine.coordinator import Machine


def test_question_slot_written_with_type_and_views(tmp_path):
    m = Machine(tmp_path)
    result = m.add_turn_slot("question", "onde está o valor de $300?",
                             message_id="msg-1")
    assert result["ok"] is True
    record = result["record"]
    assert record["type"] == "question"
    assert record["source"] == "opencode#msg-1"
    assert "type/question" in record["views"]
    assert record["id"] == "M0001"


def test_question_slot_dedupes_by_message_id(tmp_path):
    m = Machine(tmp_path)
    first = m.add_turn_slot("question", "primeira pergunta", message_id="msg-1")
    second = m.add_turn_slot("question", "pergunta duplicada", message_id="msg-1")
    assert first["ok"] and second["ok"]
    assert second.get("deduped") is True
    assert second["record"]["id"] == first["record"]["id"]
    assert len(m.tape.read()) == 1


def test_reply_slot_pairs_with_question(tmp_path):
    m = Machine(tmp_path)
    m.add_turn_slot("question", "quanto foi?", message_id="msg-1")
    reply = m.add_turn_slot("reply", "foi $300 na nota final",
                            message_id="msg-2", pair_message_id="msg-1")
    assert reply["ok"] is True
    assert reply["paired"] == ["M0001"]
    assert reply["record"]["type"] == "reply"
    assert reply["record"]["derived_from"] == ["M0001"]
    assert reply["record"]["source"] == "opencode#msg-2"


def test_orphan_reply_is_explicit(tmp_path):
    m = Machine(tmp_path)
    reply = m.add_turn_slot("reply", "resposta sem par",
                            message_id="msg-9", pair_message_id="missing")
    assert reply["ok"] is True
    assert reply["paired"] == []
    assert reply["record"]["derived_from"] == []


def test_secret_like_reply_refused(tmp_path):
    m = Machine(tmp_path)
    result = m.add_turn_slot("reply", "a chave é sk-abcdefghijklmnopqrstuvwx",
                             message_id="msg-3")
    assert result["ok"] is False
    assert "secret" in result["error"]
    assert m.tape.read() == []


def test_unknown_slot_and_empty_text_refused(tmp_path):
    m = Machine(tmp_path)
    assert m.add_turn_slot("note", "x", message_id="m")["ok"] is False
    assert m.add_turn_slot("reply", "   ", message_id="m")["ok"] is False
    assert m.tape.read() == []


def test_summary_is_bounded_and_single_line(tmp_path):
    m = Machine(tmp_path)
    long_text = "linha um\n" + "a" * 500
    result = m.add_turn_slot("question", long_text, message_id="msg-4")
    summary = result["record"]["summary"]
    assert "\n" not in summary
    assert len(summary) <= 200
    assert result["record"]["why"] == long_text.strip()
