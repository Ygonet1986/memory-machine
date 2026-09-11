"""Offline answerer-error classification over existing e2e snapshots."""
import json, re, sys
from pathlib import Path
from collections import Counter
sys.path.insert(0, "src"); sys.path.insert(0, "eval")
from memory_machine.llm import LLMClient, extract_json_object

KEY = sys.argv[1]
OUT = Path("eval/out")
FILES = {
 "p4000 base": "e2e_agents_view_payload_longmemeval_ing0_pb4000.jsonl",
 "p4000 memory": "e2e_agents_view_payload_memory_longmemeval_ing0_pb4000.jsonl",
 "oracle memory": "e2e_oracle_memory_longmemeval_ing0.jsonl",
 "oracle base": "e2e_oracle_longmemeval_ing0.jsonl",
}
ERROR_SYSTEM = open("eval/e2e_bench.py").read().split('ERROR_SYSTEM = """')[1].split('"""')[0]
client = LLMClient("https://api.deepseek.com", KEY, "deepseek-v4-flash", timeout=120, retries=1, backoff=0.5)

def evidence_from_prompt(prompt: str) -> str:
    m = re.search(r"## (?:External context|Recalled memory evidence)\n\n(.*?)\n\n## Task", prompt, re.S)
    return m.group(1) if m else ""

for name, fname in FILES.items():
    p = OUT / fname
    if not p.exists(): print(f"{name}: missing"); continue
    rows = [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    kinds = Counter(); wrong = 0
    for r in rows:
        if r["judge"]["verdict"] == "correct": continue
        wrong += 1
        ev = evidence_from_prompt(r.get("answer_prompt_final",""))
        msgs = [{"role":"system","content":ERROR_SYSTEM},
                {"role":"user","content": f"Question: {r['question']}\nReference answer: {r['gold']}\nEvidence available:\n{ev or '(none)'}\nCandidate answer: {r['answer']}"}]
        try:
            obj = extract_json_object(client.complete(msgs, temperature=0.0))
            kind = str(obj.get("kind") or "other").strip().lower()
        except Exception as e:
            kind = f"err:{type(e).__name__}"
        kinds[kind] += 1
    print(f"{name:<14} wrong={wrong:<3} {dict(kinds)}")
