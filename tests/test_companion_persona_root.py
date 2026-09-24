import json
from pathlib import Path

import pytest

from memory_machine.companion_persona import CompanionPersona
from memory_machine.secrets import SecretError


TEMPLATE = Path(__file__).resolve().parents[1] / "personas" / "lia" / "v1.json"


def sheet():
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def test_create_idempotent_and_private_history(tmp_path):
    root = tmp_path / "companion" / "person-a" / "lia" / "continuity-a"
    persona = CompanionPersona(root)
    created = persona.create(sheet())
    assert len(created) == len(sheet()["bio"])
    before = (root / "tape.jsonl").read_bytes()
    assert [r.id for r in persona.create(sheet())] == [r.id for r in created]
    assert (root / "tape.jsonl").read_bytes() == before
    assert persona.load() == sheet()
    assert json.loads((root / "persona/history/v1.json").read_text()) == sheet()
    assert all(r.author == "joint" and r.origin["version"] == "v1" for r in created)
    with pytest.raises(ValueError):
        persona.create({**sheet(), "voice": "different"})


def test_revise_supersedes_v1_and_recall_uses_only_v2(tmp_path):
    persona = CompanionPersona(tmp_path / "person-a" / "lia" / "a")
    old = persona.create(sheet())
    new = persona.revise({"bio": ["Novo fato um", "Novo fato dois", "Novo fato três"],
                          "voice": "Voz mais serena"})
    assert persona.load()["version"] == 2
    assert len(new) == 3
    assert {r.supersedes for r in new} == {r.id for r in old[:3]}
    assert all(r.status == "superseded" for r in persona.memory.tape.read()
               if r.id in {old_record.id for old_record in old})
    assert len(persona.facts()) == 3
    assert persona.memory.search("Novo fato um")[0].summary == "Novo fato um"
    assert all(r.id not in {item.id for item in old} for r in persona.memory.active())
    assert json.loads((persona.persona_dir / "history/v1.json").read_text()) == sheet()
    assert (persona.persona_dir / "history/v2.json").exists()
    assert persona.memory.evidence([old[0].id]) == []


def test_growth_and_shrink_keep_only_current_facts(tmp_path):
    persona = CompanionPersona(tmp_path / "root")
    persona.create(sheet())
    persona.revise({"bio": ["A", "B", "C", "D", "E"]})
    assert [r.summary for r in persona.facts()] == ["A", "B", "C", "D", "E"]
    persona.revise({"bio": ["F", "G", "H"]})
    assert [r.summary for r in persona.facts()] == ["F", "G", "H"]
    assert len([r for r in persona.memory.active() if r.type == "persona"]) == 3


def test_secret_rejected_before_any_root_write(tmp_path):
    root = tmp_path / "private"
    persona = CompanionPersona(root)
    secret = "sk-" + "x" * 30
    with pytest.raises(SecretError):
        persona.create({**sheet(), "bio": [secret, "B", "C"]})
    assert not root.exists()
    persona.create(sheet())
    before = (root / "tape.jsonl").read_bytes()
    with pytest.raises(SecretError):
        persona.revise({"voice": secret})
    assert (root / "tape.jsonl").read_bytes() == before
    assert not (root / "persona/history/v2.json").exists()


def test_roots_with_colliding_ids_do_not_leak(tmp_path):
    a = CompanionPersona(tmp_path / "a" / "lia" / "c")
    b = CompanionPersona(tmp_path / "b" / "lia" / "c")
    a.create(sheet())
    b.create(sheet())
    a.revise({"bio": ["Somente A", "Outra A", "Terceira A"]})
    assert b.load()["version"] == 1
    assert not b.memory.search("Somente A")
    assert "Somente A" not in (b.root / "tape.jsonl").read_text()
