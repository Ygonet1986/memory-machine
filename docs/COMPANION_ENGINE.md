# Companion engine (headless)

Status: F3a + F3b implemented (recall, layers, reply, writes, save-off).
Contract: `docs/COMPANION_V0_CONTRACT.md`. Nothing here touches the measured
opencode path, the admission-shadow-v2 window or product defaults.

## One turn

`CompanionEngine(session, client).reply(message, save=False)`

1. The whole turn runs inside `CompanionSession.run_turn`: with saving off, on
   a disposable clone, so the canonical root receives zero bytes (including
   the core recall machinery it triggers).
2. **Recall with the memory agents**: `Machine.recall(message)` inside the
   root (agents per partition, whiteboard, checklists, per-agent
   understanding). `cross_session` is never used. The engine enables the
   `budgeted` evidence payload in memory when the root config has it off; the
   root configuration itself is not modified.
3. **Labeled layers**: payload cards are filtered to the five Companion kinds
   minus `persona` (whose biography lives in the system prompt) and rendered
   as named sections with provenance:
   - Relatos da pessoa (declarações; não são verificação independente)
   - Episódios de conversas reais
   - Histórias imaginadas (ficção; nunca fatos da vida real)
   - Hipóteses tentativas (podem estar erradas; não são fatos)
   A `budget` (default 2000 chars, at least one card) bounds the context;
   dropped ids are reported.
4. **Persona prompt**: `render_persona_prompt(sheet)` from the approved root
   sheet, plus the epistemic policy (only cite provided ids; fiction stays
   fiction; hypotheses stay tentative; ask instead of filling gaps; no guilt
   or exclusivity).
5. **One reply call** (temperature 0 by default) through a counting proxy; the
   per-turn cost is the agent calls (one per consulted group) plus this one.
6. **Trailer protocol**: the reply must end with one JSON object
   `{"used": ["M0001", ...], "memories": [{"type": ..., "summary": ...,
   "quote": ..., "source": "person"|"lia", ...}]}`. The engine removes it from
   the reply, validates `used` against the provided ids and reports
   violations (`missing_trailer`, `unknown_used`); v0 does **not** rewrite the
   reply. Candidate memories pass through untouched in F3a; F3b validates and
   commits them.

Return value: `{reply, used, provided, dropped, proposed, violations, calls,
saved}`. A recall hit is not automatically a used memory: only `used` counts.

## Saving (F3b)

With `save=True` the same turn also writes, after the reply is produced:

- **Turn slots**: `question` (the person's message) and `reply` (the clean
  reply) with sources `companion#<turn_id>` and `companion#<turn_id>-r`,
  paired via `derived_from`. They are the interaction/provenance layer and do
  not enter the typed recall surface.
- **Eligible extraction**: each proposed memory must carry a literal `quote`
  from its declared source. Source policy: `person_report` only quotes the
  person's message; `episode`, `story` and `hypothesis` may quote the person
  or the character (`"source": "person" | "lia"`); `persona` never comes from
  a conversation. Every candidate goes through `CompanionMemory.add_candidate`
  (kind whitelist, author, bounds, hypothesis confidence/review, secret scan);
  rejected proposals are skipped and recorded in `violations`, never written.
- **Cache hygiene**: `recall_cache.json` is removed after writes so the next
  turn recalls fresh state.

With `save=False` the whole turn (recall agents, whiteboard, extraction)
runs on the disposable clone: the canonical root receives zero bytes.

## Non-goals

- No cross-root or cross-session search; no web/personal-data ingestion.
- No shadow admission, no change to `opencode` defaults; the frozen window is
  checked only under its own stopping rule.
- The engine does not rewrite a reply when the trailer is violated (v0);
  violations are measured in the F5 evaluation.
