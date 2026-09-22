#!/usr/bin/env python3
"""Lifecycle v1 fixture generator (deterministic, anti-leakage).

Writes `eval/fixtures/lifecycle_v1/`:

  records.jsonl  CLASSIFIER INPUT ONLY: memory_id, session, seq, text, tape_type
  gold.jsonl     separate file: gold_class, pattern, notes (never read by rules)
  probes.jsonl   probe_id, session, after_seq, question, required_ids
  manifest.json  seed, counts, sha1s, contract and anti-leakage assertions

The seed only composes/orders; every record, class and probe below is explicit
and inspectable. Regenerating with the same seed is byte-identical.

Run: PYTHONPATH=src python3 eval/gen_lifecycle_fixture.py [--out DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "src"))

SEED = 20260922
POLICY_VERSION = "lifecycle-v1"

CLASSES = ("semantic", "episodic", "event_only", "reject")
PATTERNS = (
    "greeting", "ack", "operational", "decision", "preference", "restriction",
    "lesson", "bugfix", "build", "experiment_result", "failure_context",
    "action_taken", "temporary_state", "temporary_preference",
    "weak_future_intent", "correction", "decision_change", "negation",
    "valid_repetition", "semantic_duplicate", "duplicate_exact",
    "duplicate_normalized", "invalid_record", "useful_low_appearance",
    "important_never_used", "unrecoverable_due_to_ingestion",
)

# (memory_id, session, seq, text, tape_type, gold_class, pattern)
RECORDS: list[tuple] = [
    # session S1 — decisions and chatter
    ("M0001", "S1", 1, "oi, tudo bem?", "memory", "event_only", "greeting"),
    ("M0002", "S1", 2, "Olá! Em que posso ajudar hoje?", "memory", "event_only", "ack"),
    ("M0003", "S1", 3, "Decidimos usar PostgreSQL como banco primário do serviço Aurora.",
     "decision", "semantic", "decision"),
    ("M0004", "S1", 4, "Ótima escolha; já configuro o pool de conexões.", "memory",
     "event_only", "operational"),
    ("M0005", "S1", 5, "ok", "memory", "event_only", "ack"),
    ("M0006", "S1", 6, "Importante: nunca sugerir trocar o banco primário sem um benchmark que comprove ganho.",
     "preference", "semantic", "restriction"),
    ("M0007", "S1", 7, "Por hoje é isso, obrigado!", "memory", "event_only", "operational"),
    # session S2 — experiments, failure, low-salience fact, temporary preference
    ("M0008", "S2", 8, "Rodamos o teste de carga com 500 usuários; o p95 ficou em 820 ms.",
     "build", "episodic", "experiment_result"),
    ("M0009", "S2", 9, "Rodamos o teste de carga com 500 usuários; o p95 ficou em 820 ms.",
     "memory", "reject", "duplicate_exact"),
    ("M0018", "S2", 10, "rodamos  o teste de carga com 500 usuários, o p95 ficou em 820 ms!",
     "memory", "reject", "duplicate_normalized"),
    ("M0010", "S2", 11, "O deploy falhou por falta de permissão no bucket; corrigi criando a role nova.",
     "bugfix", "episodic", "failure_context"),
    ("M0011", "S2", 12, "No fim do dia, a rotação da chave de deploy acontece a cada 90 dias.",
     "memory", "semantic", "useful_low_appearance"),
    ("M0012", "S2", 13, "Para a demonstração de amanhã, use a porta 8080.", "memory",
     "episodic", "temporary_preference"),
    ("M0013", "S2", 14, "A propósito: agora usamos SQLite para o cache local; não usamos mais Redis para isso.",
     "decision", "semantic", "correction"),
    ("M0014", "S2", 15, "O Redis continua sendo usado no serviço de sessões; isso não mudou.",
     "memory", "semantic", "negation"),
    ("M0015", "S2", 16, "Talvez devêssemos considerar Kafka no futuro, mas nenhuma decisão foi tomada.",
     "memory", "episodic", "weak_future_intent"),
    ("M0016", "S2", 17, "ok, obrigado", "memory", "event_only", "ack"),
    # session S3 — decision change + normalized duplicate + valid repetition
    ("M0017", "S3", 17, "Atualização: trocamos o banco primário de PostgreSQL para CockroachDB na semana passada.",
     "decision", "semantic", "decision_change"),
    ("M0019", "S3", 19, "Como combinado, o banco primário do Aurora segue sendo o PostgreSQL até a migração.",
     "memory", "semantic", "valid_repetition"),
    ("M0020", "S3", 20, "Vamos migrar para Kubernetes no Q1; ainda sem data definida.",
     "decision", "semantic", "important_never_used"),
    # session S4 — lesson, procedure, semantic duplicate, invalid
    ("M0021", "S4", 21, "Lição: sempre rodar o teste de carga antes de trocar o pool de conexões.",
     "lesson", "semantic", "lesson"),
    ("M0022", "S4", 22, "Procedimento de release: congelar a fita de memória antes de cada deploy grande.",
     "build", "semantic", "build"),
    ("M0023", "S4", 23, "Como combinado, o banco primário do Aurora continua sendo o PostgreSQL por enquanto.",
     "memory", "semantic", "semantic_duplicate"),
    ("M0024", "S4", 24, "   ", "memory", "reject", "invalid_record"),
    ("M0025", "S4", 25, "beleza", "memory", "event_only", "ack"),
    # session S5 — state, confirmation, more chatter
    ("M0026", "S5", 26, "Estado atual: o cluster de staging está com 3 nós ativos.",
     "memory", "episodic", "temporary_state"),
    ("M0027", "S5", 27, "Confirmado: o p95 do último teste foi 820 ms.", "memory",
     "episodic", "experiment_result"),
    ("M0028", "S5", 28, "combinado", "memory", "event_only", "ack"),
    ("M0029", "S5", 29, "O time combinou de revisar o runbook na sexta-feira.", "memory",
     "episodic", "temporary_state"),
    # session S6 — later repetition and closure
    ("M0030", "S6", 30, "Relembrando a regra: nunca trocar o banco primário sem benchmark que comprove ganho.",
     "memory", "semantic", "valid_repetition"),
    ("M0031", "S6", 31, "A rotação da chave de deploy passou a ser a cada 60 dias.", "decision",
     "semantic", "correction"),
    ("M0032", "S6", 32, "valeu!", "memory", "event_only", "ack"),
]

# Probes measure utility AFTER the admission decision (temporal order).
PROBES: list[dict[str, Any]] = [
    {"probe_id": "P01", "session": "S2", "after_seq": 7,
     "question": "qual banco primário foi decidido para o serviço Aurora?",
     "required_ids": ["M0003"]},
    {"probe_id": "P02", "session": "S3", "after_seq": 16,
     "question": "qual foi o resultado do teste de carga com 500 usuários?",
     "required_ids": ["M0008"]},
    {"probe_id": "P03", "session": "S3", "after_seq": 16,
     "question": "o que fazer quando o deploy falha por permissão no bucket?",
     "required_ids": ["M0010"]},
    {"probe_id": "P04", "session": "S3", "after_seq": 16,
     "question": "com que frequência a chave de deploy é rotacionada?",
     "required_ids": ["M0011"]},
    {"probe_id": "P05", "session": "S3", "after_seq": 16,
     "question": "qual porta usar na demonstração?",
     "required_ids": ["M0012"]},
    {"probe_id": "P06", "session": "S3", "after_seq": 16,
     "question": "o que usamos para o cache local agora?",
     "required_ids": ["M0013"]},
    {"probe_id": "P07", "session": "S3", "after_seq": 16,
     "question": "o Redis ainda é usado em algum lugar?",
     "required_ids": ["M0014"]},
    {"probe_id": "P08", "session": "S3", "after_seq": 16,
     "question": "quais restrições existem para trocar o banco primário?",
     "required_ids": ["M0006"]},
    {"probe_id": "P09", "session": "S4", "after_seq": 20,
     "question": "qual é o banco primário atual do Aurora?",
     "required_ids": ["M0017"]},
    {"probe_id": "P10", "session": "S4", "after_seq": 20,
     "question": "o PostgreSQL ainda era o banco primário antes da migração?",
     "required_ids": ["M0019"]},
    {"probe_id": "P11", "session": "S5", "after_seq": 29,
     "question": "qual lição aprendemos sobre trocar o pool de conexões?",
     "required_ids": ["M0021"]},
    {"probe_id": "P12", "session": "S5", "after_seq": 29,
     "question": "o que fazer antes de um deploy grande?",
     "required_ids": ["M0022"]},
    {"probe_id": "P13", "session": "S5", "after_seq": 29,
     "question": "qual é o estado atual do cluster de staging?",
     "required_ids": ["M0026"]},
    {"probe_id": "P14", "session": "S5", "after_seq": 29,
     "question": "qual foi o p95 confirmado do teste de carga?",
     "required_ids": ["M0027"]},
    {"probe_id": "P15", "session": "S6", "after_seq": 32,
     "question": "qual é a regra sobre trocar o banco primário?",
     "required_ids": ["M0006", "M0030"]},
    {"probe_id": "P16", "session": "S6", "after_seq": 32,
     "question": "com que frequência a chave de deploy é rotacionada agora?",
     "required_ids": ["M0031"]},
    {"probe_id": "P17", "session": "S6", "after_seq": 32,
     "question": "qual banco é usado para o cache local?",
     "required_ids": ["M0013"]},
    {"probe_id": "P18", "session": "S6", "after_seq": 32,
     "question": "quais decisões temos registradas sobre o banco primário?",
     "required_ids": ["M0003", "M0017"]},
    {"probe_id": "P19", "session": "S6", "after_seq": 32,
     "question": "qual foi a duração total do projeto?",
     "required_ids": ["M9999"], "unrecoverable": True},  # never ingested
    {"probe_id": "P20", "session": "S6", "after_seq": 32,
     "question": "o que ficou combinado para sexta-feira?",
     "required_ids": ["M0029"]},
]


def sha1_bytes(blob: bytes) -> str:
    return hashlib.sha1(blob).hexdigest()


def build() -> dict[str, bytes]:
    records = [
        {"memory_id": mid, "session": session, "seq": seq, "text": text,
         "tape_type": tape_type}
        for mid, session, seq, text, tape_type, _gold, _pattern in RECORDS
    ]
    gold = [
        {"memory_id": mid, "gold_class": gold_class, "pattern": pattern}
        for mid, _session, _seq, _text, _type, gold_class, pattern in RECORDS
    ]
    probes = PROBES
    files = {
        "records.jsonl": b"".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True).encode() + b"\n"
            for row in records),
        "gold.jsonl": b"".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True).encode() + b"\n"
            for row in gold),
        "probes.jsonl": b"".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True).encode() + b"\n"
            for row in probes),
    }
    manifest = {
        "builder": "eval/gen_lifecycle_fixture.py",
        "version": 1,
        "seed": SEED,
        "policy_version": POLICY_VERSION,
        "counts": {
            "records": len(records),
            "probes": len(probes),
            "by_class": {cls: sum(1 for r in gold if r["gold_class"] == cls)
                         for cls in CLASSES},
        },
        "contract": {
            "classifier_input": "records.jsonl only (memory_id, session, seq, text, tape_type)",
            "gold_file": "gold.jsonl (never read by rules/prompts)",
            "probe_order": "after_seq > max(seq of required ids) for ingested probes",
            "seed_usage": "composition/ordering only; gold is explicit below",
        },
        "files": {name: sha1_bytes(blob) for name, blob in sorted(files.items())},
        "sha1": sha1_bytes(b"".join(files[name] for name in sorted(files))),
    }
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True)
                              + "\n").encode()
    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="eval/fixtures/lifecycle_v1")
    args = parser.parse_args()
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    files = build()
    for name, blob in files.items():
        (out / name).write_bytes(blob)
    print(f"fixture: {out} | records {len(RECORDS)} | probes {len(PROBES)} "
          f"| sha1 {json.loads(files['manifest.json'])['sha1']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
