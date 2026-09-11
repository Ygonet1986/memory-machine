import json
from pathlib import Path
OUT = Path.home() / "memory-machine" / "eval" / "out"
def load(name):
    p = OUT / name
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
def mean(xs): return sum(xs)/len(xs) if xs else 0.0
levels = {
 "INGEST-2K": "e2e_agents_view_payload_longmemeval.jsonl",
 "INGEST-4K": "e2e_agents_view_payload_longmemeval_ing4000.jsonl",
 "INGEST-8K": "e2e_agents_view_payload_longmemeval_ing8000.jsonl",
 "INGEST-FULL": "e2e_agents_view_payload_longmemeval_ing0.jsonl",
}
print(f"{'level':<12} {'n':>3} {'GFR':>5} {'evid':>6} {'strict':>7} {'AUR':>6} {'ctx_ch':>7}")
for name, f in levels.items():
    rows = load(f)
    if not rows: print(f"{name:<12} pending"); continue
    strict = sum(1 for r in rows if r["judge"]["verdict"]=="correct")
    complete = [r for r in rows if r["evidence_complete"]==1]
    aur = sum(1 for r in complete if r["judge"]["verdict"]=="correct")/len(complete) if complete else None
    gfr = [r.get("gfr") for r in rows if r.get("gfr") is not None]
    print(f"{name:<12} {len(rows):>3} {(mean(gfr) if gfr else float('nan')):>5.2f} "
          f"{len(complete)/len(rows):>6.2f} {strict/len(rows):>7.2f} "
          f"{(f'{aur:.2f}' if aur is not None else '  -'):>6} {mean([r['context_chars'] for r in rows]):>7.0f}")
