import json
from pathlib import Path
OUT = Path.home() / "memory-machine" / "eval" / "out"
def load(arm, suffix):
    p = OUT / f"e2e_{arm}{suffix}.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
def mean(xs): return sum(xs)/len(xs) if xs else 0.0
print(f"{'arm':<22} {'n':>3} {'evid':>6} {'strict':>7} {'AUR':>6} {'ctx_ch':>7} {'pl_ch':>6} {'trunc':>6}")
for arm in ["agents_view_ctx", "agents_view_payload"]:
    rows = load(arm, "_longmemeval")
    if not rows: continue
    complete = [r for r in rows if r["evidence_complete"] == 1]
    strict = sum(1 for r in rows if r["judge"]["verdict"] == "correct")
    aur = sum(1 for r in complete if r["judge"]["verdict"] == "correct")/len(complete) if complete else None
    trunc = sum(1 for r in rows for i in r.get("payload_items", []) if i.get("truncated"))
    print(f"{arm:<22} {len(rows):>3} {len(complete)/len(rows):>6.2f} {strict/len(rows):>7.2f} "
          f"{(f'{aur:.2f}' if aur is not None else '  -'):>6} {mean([r['context_chars'] for r in rows]):>7.0f} "
          f"{mean([r.get('payload_chars',0) for r in rows]):>6.0f} {trunc:>6}")
