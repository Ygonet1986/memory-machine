# Configuration

`config.json` (see `config.json.example`):

| Key | Default | Meaning |
|-----|---------|---------|
| `capacity` | 500 | memories per group (per agent) |
| `graph_enabled` | `false` | write-time graph extraction (opt-in) |
| `graph_batch_size` / `graph_batch_max_chars` | 8 / 12000 | extraction batching limits |
| `graph_recall_mode` | `off` | graph recall: `off` / `augment` / `augment_guarded` / `only` |
| `graph_augment_min_score` / `graph_augment_max_items` | 0.80 / 3 | guarded augmentation: score floor and cap |
| `graph_augment_hub_degree` | 20 | guarded traversal: stop-expanding degree (generic `graph_hub_degree` overrides) |
| `graph_augment_question_gate` / `min_cov` | `false` / 0.30 | optional question veto over graph-only evidence (calibrated, pending the miss slice) |
| `graph_hub_degree` | 0 | guarded traversal: stop-expanding degree (0 = off) |
| `graph_resolver_candidates` | 10 | resolver shortlist size (doc-vector cache is always on) |
| `document_graph_enabled` | `true` | project `.txt` attachments into the document graph |
| `document_structure_level` | `chunk` | document scope: `chunk` / `document` / `both` |
| `document_window_chars` | 12000 | content-cost budget per document window |
| `plasticity_mode` | `off` | learned path priority: `off` / `observe` / `shadow` / `update` / `deliver` (P0 pre-registered; ledger in `<root>/plasticity/`) |
| `evidence_payload_window` | `false` | opt-in fact-window truncation (U2b; no reliable gain in the U3 30-case audit — stays off) |
| `graph_depth` / `graph_top_k` | 2 / 8 | traversal depth (semantic hops) and evidence cap |
| `whiteboard_budget` | 4000 | char budget for reminders on the whiteboard |
| `consolidate_threshold` | 6000 | whiteboard size that triggers consolidation |
| `context_consolidate_threshold` | 6000 | chatbot context size that triggers its own consolidation |
| `router_enabled` | `false` | enable partition routing (opt-in) |
| `router_mode` | `llm` | `lexical` / `embedding` / `llm` / `views` / `cascade` |
| `router_top_k` | 5 | partitions selected by the similarity router |
| `view_router_mode` | `lexical` | view selection: `lexical` (BM25) / `llm` (contextual) |
| `view_top_k` | 5 | views selected by the view router |
| `view_dimension_mode` | `off` | `auto` = dimension-aware plan (semantic/temporal/structural) with intersection |
| `view_prune` | `none` | `subject` = drop broad `subject/*` views when a topic matched |
| `agent_mode` | `group` | `view` = one perspective agent per selected view |
| `agent_history_messages` | `10` | 0-50 = append the last N turn slots ("Pessoa:"/"Assistente:") to every memory agent's user prompt so the agents follow the conversation. Active by default since v0.3.1 (declared with an archived-window restart under admission-shadow-v2 §8); set `0` to keep prompts byte-identical. |
| `whiteboard_mode` | `single` | `dimension` = one working board per dimension |
| `answerer_observer` | `true` | The conversation is served by **two agents**: the observer (one call) refreshes a compact conversation `understanding` (persisted) and gives short guidance; the answerer then writes with that guidance. Set `false` for the single-call path. Add ~1 LLM call per chatbot turn; recall/agents and the admission window are untouched. |
| `answerer_history_messages` | `10` | The conversation agent's context rule: the last N turns (summary + turns, each side capped at 320 chars) have priority inside `whiteboard_budget`; the whiteboard fills the remainder and is trimmed at that remainder, never below a 800-char floor. Set `0` to give the whole budget back to the whiteboard. Only affects the chatbot turn (CLI/app); recall/agents and the admission window are untouched. |
| `attention_mode` | `off` | persistent attention prior: `prior` / `context` / `state` |
| `attention_decay` / `boost` / `found_boost` | 0.6 / 0.8 / 0.3 | attention decay and saturation boosts |
| `attention_weight` | 0.5 | weight of the attention prior in view scoring |
| `attention_gate_min` / `margin` | 0.5 / 0.1 | concentration required for the `state` gate |
| `coverage_mode` | `off` | recall-local coverage signal: `agents` / `structural` / `views` / `judge` |
| `cascade_min_score` | 0.0 | selection score below which the cascade expands |
| `cascade_expand_top_k` | 5 | co-occurring views added on expansion |
| `model` | `deepseek-v4-flash` | LLM model for agents, chatbot and consolidators |
| `base_url` | `https://api.deepseek.com` | OpenAI-compatible endpoint |
| `api_key_env` | `DEEPSEEK_API_KEY` | env var that holds the API key |

The API key is read from the environment only; it is never written to disk.

### Agent conversation window (opt-in)

`agent_history_messages: 10` makes the memory agents read the last ten turn
slots recorded on the tape (paired `question`/`reply`, deduped by source).
Together with the per-agent `understanding` field (which the agent refines
every sweep and which is already persisted in the manifest), the agents'
metacognition then tracks the live conversation instead of only the
whiteboard. Requirements: turn slots present on the tape (the opencode
plugin flag or the Companion engine writes them), so the effective content
appears after the opencode restart that loads the slot flag. Set `0` to
disable in a root where prompts must stay frozen.

### Admission shadow instrumentation (opt-in)

`MEMORY_MACHINE_ADMISSION_SHADOW=1` makes every recall append one JSON line of
**derived admission signals** (candidate origin, score/rank, lexical overlap,
IDF rare-term coverage, entity/date matches, characters each candidate would
consume, counterfactual admission) to `admission_shadow.jsonl` in the session
root (`MEMORY_MACHINE_ADMISSION_SHADOW_PATH` overrides the path). It never
writes question text, summaries or notes — only IDs, hashes and metrics — and
never changes a recall result. See `docs/ADMISSION_SHADOW_V1.md`.


## See also

- `config.json.example` in the repository root.
- `docs/ADMISSION_SHADOW_V1.md` for the opt-in admission instrumentation.
