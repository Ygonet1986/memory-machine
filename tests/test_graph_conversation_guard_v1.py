"""graph-conversation-guard-v1: candidate rescue, fixture and recorded verdicts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from memory_machine.graph import GraphStore
from memory_machine.graph_recall import (
    GraphEvidence, GraphPath, conversation_rescue,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "eval" / "fixtures" / "graph_conversation_guard_v1"
OUT = ROOT / "eval" / "results" / "graph_conversation_guard_v1"


def test_fixture_hash_matches_manifest():
    text = (FIXTURE / "cases.json").read_text(encoding="utf-8")
    manifest = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == \
        manifest["cases_sha256"]


def test_recorded_verdicts():
    report = json.loads((OUT / "report.json").read_text(encoding="utf-8"))
    assert report["all_pass"] is True
    assert report["linked"] == {"plain": 3, "promoted": 0, "candidate": 3}
    assert report["noise"] == {"plain": 1, "promoted": 0, "candidate": 0}
    assert report["gates"] == {
        "C1_candidate_recovers_links": True, "C2_beats_promoted": True,
        "C3_noise_bounded": True, "C4_determinism": True,
        "C5_bounded_rescue": True,
    }
    assert "lab mechanism test" in report["scope"]


def _index(tmp_path):
    store = GraphStore(tmp_path / "graph")
    store.add_entity("Lia", "person", "M1", entity_id="E1")
    store.add_entity("jardim", "place", "M1", entity_id="E2")
    store.add_relation("E1", "related_to", "E2", "M1", 0.9, relation_id="R1")
    store.add_relation("E1", "cross", "E2", "M1", 0.9, relation_id="R2")
    return store.index()


def _item(memory_id: str, score: float, relation_id: str) -> GraphEvidence:
    item = GraphEvidence(memory_id=memory_id, score=score, via="path")
    item.paths = [GraphPath(nodes=["E1", "E2"], relations=[relation_id],
                            score=score, semantic_depth=1)]
    return item


def test_rescue_admits_association_only_above_floor(tmp_path):
    index = _index(tmp_path)
    association = _item("M2", 0.65, "R1")
    non_association = _item("M3", 0.95, "R2")
    below_floor = _item("M4", 0.40, "R1")
    mention = GraphEvidence(memory_id="M5", score=0.9, via="mention")

    rescued = conversation_rescue(
        [association, non_association, below_floor, mention], index)
    assert [item.memory_id for item in rescued] == ["M2"]


def test_rescue_cap_bounds_the_extra_items(tmp_path):
    index = _index(tmp_path)
    items = [_item(f"M{index + 2}", 0.9, "R1") for index in range(4)]
    assert len(conversation_rescue(items, index)) == 2
    assert len(conversation_rescue(items, index, max_items=0)) == 0
