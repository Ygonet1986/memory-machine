"""Generate a synthetic project-memory fixture + tasks with ground truth.

Writes a full project (config, tape, manifest, whiteboard) with ``--records``
memories and a ``tasks.json`` mapping each task to the memory id that SHOULD be
remembered.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from memory_machine.config import Config
from memory_machine.coordinator import Machine
from memory_machine.tape import MemoryRecord

DOMAINS = [
    "payments",
    "auth",
    "search",
    "inventory",
    "shipping",
    "notifications",
    "billing",
    "analytics",
]
TECHS = [
    "Postgres",
    "Redis",
    "Kafka",
    "gRPC",
    "Elasticsearch",
    "S3",
    "RabbitMQ",
    "Prometheus",
    "Flink",
    "MongoDB",
]
TYPES = ["decision", "lesson", "preference", "bugfix", "build"]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--records", type=int, default=300)
    p.add_argument("--tasks", type=int, default=20)
    p.add_argument("--capacity", type=int, default=50)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    root = Path(args.out).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    cfg = Config(capacity=args.capacity)
    cfg.save(root / "config.json")
    m = Machine(root, config=cfg)

    rng = random.Random(args.seed)
    for i in range(args.records):
        domain = DOMAINS[i % len(DOMAINS)]
        tech = TECHS[(i // len(DOMAINS)) % len(TECHS)]
        rec = MemoryRecord(
            type=TYPES[i % len(TYPES)],
            summary=f"{tech} for the {domain} module",
            why=f"recorded during {domain} work; token={i:04d}",
        )
        m.add_memory(rec, save=(i % 25 == 0))
    m.save()

    sample = sorted(rng.sample(range(args.records), min(args.tasks, args.records)))
    tasks = []
    for idx in sample:
        domain = DOMAINS[idx % len(DOMAINS)]
        tech = TECHS[(idx // len(DOMAINS)) % len(TECHS)]
        tasks.append(
            {
                "task": f"We are revisiting the {domain} module. What did we decide about {tech}?",
                "expected": f"M{idx + 1:04d}",
            }
        )

    (root / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.records} records + {len(tasks)} tasks to {root}")


if __name__ == "__main__":
    main()
