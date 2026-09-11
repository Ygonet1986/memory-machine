import json
from pathlib import Path
OUT = Path.home() / "memory-machine" / "eval" / "out"
def load(name):
    p = OUT / name
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []
def mean(xs): return sum(xs)/len(xs) if xs else 0.0
runs = {
 "FULL": "e2e_agents_view_ctx_longmemeval_ing0.jsonl",
 "P6000": "e2e_agents_view_payload_longmemeval_ing0_pb6000.jsonl",
 "P4000": "e2e_agents_view_payload_longmemeval_ing0_pb4000.jsonl",
 "P2500": "e2e_agents_view_payload_longmemeval_ing0_pb2500.jsonl",
}
base = None
print(f"{'arm':<7} {'n':>3} {'GFR':>5} {'evid':>6} {'strict':>7} {'AUR':>6} {'chars':>7} {'d_strict':>9} {'red%':>6}")
for name, f in runs.items():
    rows = load(f)
    if not rows:
        print(f"{name:<7} pending"); continue
    strict = sum(1 for r in rows if r["judge"]["verdict"]=="correct")/len(rows)
    complete = [r for r in rows if r["evidence_complete"]==1]
    aur = sum(1 for r in complete if r["judge"]["verdict"]=="correct")/len(complete) if complete else None
    gfr = [r.get("gfr") for r in rows if r.get("gfr") is not None]
    chars = mean([max(r.get("context_chars",0), r.get("payload_chars",0)) for r in rows])
    if name == "FULL": base = (strict, chars)
    ds = f"{strict-base[0]:+.3f}" if base else "-"
    red = f"{(1-chars/base[1])*100:.0f}" if base and base[1] else "-"
    print(f"{name:<7} {len(rows):>3} {(mean(gfr) if gfr else float('nan')):>5.2f} "
          f"{len(complete)/len(rows):>6.2f} {strict:>7.2f} "
          f"{(f'{aur:.2f}' if aur is not None else '  -'):>6} {chars:>7.0f} {ds:>9} {red:>6}")
