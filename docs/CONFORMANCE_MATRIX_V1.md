# Memory Machine — Matriz de Conformidade v1

Versão: 1.0 · Data: 2026-09-21 · HEAD: `9d9a235` · Spec: `docs/NORMATIVE_SPEC_V1.md` (e2df0f8)

**Método.** Suíte coletada e executada neste HEAD: **440 testes, 440 passed**
(`PYTHONPATH=src python3 -m pytest -q`). As referências de teste abaixo são
node IDs reais do repositório (`arquivo::teste`). Onde não existe teste direto,
o status diz isso — nenhuma garantia foi inferida por narrativa.

**Legenda de status**

| Status | Significado |
|---|---|
| **CONFORME** | código existe **e** há teste automatizado direto no repo |
| **PARCIAL** | código existe; cobertura indireta, incompleta ou fora da suíte |
| **INTENÇÃO** | norma-alvo da spec, ainda sem implementação |
| **BLOQUEADO** | não avançar (ex.: congelado por gate) |

---

## 1. Invariantes N1–N14

| # | Norma | Código | Teste(s) de referência | Status |
|---|---|---|---|---|
| N1 | Fita é a única fonte da verdade | `tape.py`, `coordinator.py` | `test_tape.py::test_append_is_append_only`; `test_graph_hooks.py::test_projection_never_touches_the_tape_bytes` | **CONFORME** |
| N2 | Projeções reconstruíveis a partir da fita/originais | `graph.py`, `documents.py`, `ingest_document.py` | `test_document_rebuild.py::test_round_trip_rebuild_reproduces_projection`; `::test_plain_build_graph_keeps_graph_v3_projection` | **CONFORME** |
| N3 | Evidência com caminho até a memória (e ao original) | `graph_recall.py`, `graph.py` (explain) | `test_graph_recall.py::test_relation_provenance_maps_to_memory`; `test_document_rebuild.py::test_explain_shows_all_evidence_and_original_text` | **CONFORME** |
| N4 | Anotação ≠ evidência (payload fornece o fato) | `payload.py`, `main_chatbot.py` | `test_main_chatbot.py::test_extra_context_is_in_prompt_but_not_whiteboard`; medição H2 (manual §40.10) | **CONFORME** |
| N5 | Payload é efêmero (não acumula no quadro) | `payload.py` | `test_payload.py::test_recall_payload_is_not_persisted` | **CONFORME** |
| N6 | Orçamento de contexto é limite duro | `payload.py`, `whiteboard.py` | `test_payload.py::test_payload_respects_budget_and_relevance`; `test_whiteboard.py::test_merge_ranks_and_applies_budget` | **CONFORME** |
| N7 | Segredos bloqueiam toda escrita, inclusive envelopes | `secrets.py`, `trilepsia.py` | `test_secrets.py` (7 testes); `test_trilepsia.py::test_envelope_is_secret_scanned`; `test_document_ingest.py::test_secret_chunk_skipped_without_false_provenance` | **CONFORME** |
| N8 | Spans exatos com offsets reversíveis | `eval/evidence_cards.py` | **nenhum teste na suíte pytest**; validação existe só no `--self-check`/`--report` de `eval/` | **PARCIAL** |
| N9 | Atualizar = append (nunca editar conteúdo) | `tape.py` (status), `consolidate.py` | `test_tape.py::test_status_default_active`; `test_coordinator.py::test_rollup_derived_from_and_rehydrate` | **CONFORME** |
| N10 | Camadas experimentais off e byte-equivalentes quando off | `config.py` | `test_config.py::test_graph_defaults_are_off_and_consistent`; `test_payload.py::test_payload_window_off_is_unchanged`; `test_attachments.py::test_ingest_records_byte_equivalent_without_new_fields` | **CONFORME** |
| N11 | Pré-registro congelado antes de executar | processo (`docs/`) | sem teste; evidência nos artefatos (`PLASTICITY_V1`, `COMPOSITION_V1`, `TRILEPSIA_*`) | **PARCIAL** |
| N12 | Seleção no braço real não lê gold/verdicts | harnesses `eval/` | sem teste que audite os harnesses | **PARCIAL** |
| N13 | Payload builder determinístico, sem LLM | `payload.py` | `test_payload.py` (11 testes; sem cliente LLM no caminho) | **CONFORME** |
| N14 | Piso de oscilação medido como limite mínimo de alegação | processo (`eval/`) | sem teste/CI; medições registradas (U4.2; E-lines) | **INTENÇÃO** |

**Contagem: 10 CONFORME · 3 PARCIAL · 1 INTENÇÃO · 0 BLOQUEADO.**

## 2. Schemas e fluxos

| Norma | Código | Testes | Status |
|---|---|---|---|
| Schema da fita (campos/status/id) | `tape.py` | `test_tape.py` (12) | **CONFORME** |
| Schema do quadro (incl. merge/orçamento) | `whiteboard.py` | `test_whiteboard.py` (7) | **CONFORME** |
| Schema do payload | `payload.py` | `test_payload.py` (11) | **CONFORME** |
| Registry de documentos + originais (hash) | `documents.py`, `ingest_document.py` | `test_document_ingest.py` (10); `test_document_rebuild.py` (11) | **CONFORME** |
| Grafo (meta/entities/relations/proveniência) | `graph.py`, `graph_extract.py`, `graph_resolve.py` | `test_graph.py`, `test_graph_v2.py`, `test_graph_extract.py`, `test_graph_resolve.py`, `test_graph_f4.py`, `test_graph_hooks.py` (≈70) | **CONFORME** |
| Trilepsia (envelope/V/queues/validador) | `trilepsia.py` | `test_trilepsia.py` (14) | **CONFORME** (camada congelada por gate) |
| Versão de schema + migrações | — | — | **INTENÇÃO** (spec §14) |
| Fluxo de escrita (tape→views→projeções) | `coordinator.py`, `attachments.py` | `test_coordinator.py`, `test_attachments.py` (9), `test_graph_hooks.py` | **CONFORME** |
| Fluxo de recall (plan→agents→quadro→payload) | `coordinator.py`, `view_router`/`routing` | `test_coordinator.py::test_recall_returns_whiteboard`; `test_view_router.py` (13); `test_routing.py` (30) | **CONFORME** |
| Fluxo de checkpoint (grava volta) | `coordinator.py` | `test_coordinator.py::test_checkpoint_writes_back` | **CONFORME** |

## 3. Defaults e configuração limpa

| Norma | Teste | Status |
|---|---|---|
| Defaults válidos e normalizados | `test_config.py::test_defaults_are_valid`; `::test_clamps_capacity_and_budgets`; `::test_non_int_values_fall_back` | **CONFORME** |
| Experimentais off (grafo; janela; payload window; trilepsia) | `test_config.py::test_graph_defaults_are_off_and_consistent`; `test_app_graph.py::test_graph_settings_default_to_off`; `test_payload.py::test_config_payload_window_defaults_off` | **CONFORME** |
| Chaves desconhecidas ignoradas (compat) | `test_config.py::test_from_dict_ignores_unknown_keys` | **CONFORME** |
| Defaults = arquitetura principal? | — (spec §1 marca `[CONFLITO]`) | **INTENÇÃO** (gate de default §8) |

## 4. Retenção, contradição/tempo, segurança, escala

| Norma | As-is | Alvo | Status |
|---|---|---|---|
| Níveis event log / episódico / semântico | turno vira `memory` (dedupe) + status + rollup | separar níveis e retenção | **INTENÇÃO** |
| Rollup por idade | `test_coordinator.py::test_rollup_archives_old_records` | rollup semântico (schema+scope+validade) | **PARCIAL** |
| Validade temporal | `created_at`, `superseded`, H5' medido | `valid_from/until`, `asserted_by`, confianças separadas | **PARCIAL** |
| Contradição (`contradicts`/`supports`/`verification_status`) | Trilepsia T1 (congelada) tem `state/assumptions` | relações append-only na fita | **INTENÇÃO** |
| Segurança: scanner + isolamento de contexto externo | `test_secrets.py`; `test_main_chatbot.py::test_extra_context_is_in_prompt_but_not_whiteboard` | sensibilidade/criptografia/injection | **PARCIAL** |
| Chave só no Keychain (app) | `app/keychain.py` + fluxo do app | — | **CONFORME** (código; app fora do pytest) |
| Escala 10k/100k/1M medida | — | benchmark reproduzível | **INTENÇÃO** |

## 5. Matriz de modos (combinações mínimas)

| Modo | Config | Testes que cobrem | Status |
|---|---|---|---|
| **Legado** | `agent_mode=group`, `whiteboard_mode=single`, `attention_mode=off`, `evidence_payload=off`, `graph=off` | `test_coordinator.py` (14), `test_groups.py` (9), `test_agents.py` (15), `test_tape.py` (12) | **CONFORME** |
| **Views sem atenção** | `agent_mode=view` + roteador lexical/LLM | `test_view_router.py` (13), `test_routing.py` (30) | **CONFORME** |
| **Views + atenção** | `attention_mode=prior|context|state` | `test_attention.py` (12: decay/gate/anáfora/troca de tópico) | **CONFORME** |
| **Views + boards** | `whiteboard_mode=dimension` | roteamento por dimensão coberto (`test_routing.py`); persistência/merge de `Whiteboard.boards` **sem teste direto** | **PARCIAL** |
| **Payload off/budgeted/janela** | `evidence_payload=off|budgeted|full`; `evidence_payload_window` | `test_payload.py` (11) | **CONFORME** |
| **Grafo off/on (+documento)** | `graph_enabled`; `document_graph_enabled` | `test_graph_hooks.py` (13), `test_app_graph.py` (9), `test_document_*` (21) | **CONFORME** |
| **Trilepsia** | `trilepsia_*` | `test_trilepsia.py` (14) | **CONFORME** (congelada; off) |

## 6. Migração e compatibilidade (instalações antigas)

| Cenário | Cobertura | Status |
|---|---|---|
| Config antigo com chaves desconhecidas | `test_config.py::test_from_dict_ignores_unknown_keys` | **CONFORME** |
| Registro da fita sem campos novos (ex.: `trilepsia`) | `MemoryRecord.from_dict` tolerante; `test_tape.py` | **CONFORME** (por leitura tolerante; sem teste explícito de fita antiga com campo ausente) |
| Anexos ingeridos antes dos campos novos | `test_attachments.py::test_ingest_records_byte_equivalent_without_new_fields` | **CONFORME** |
| Grafo/doc layer desligado preserva projeção v3 | `test_document_rebuild.py::test_plain_build_graph_keeps_graph_v3_projection` | **CONFORME** |
| Troca de `agent_mode`/`whiteboard_mode` sem perda/reescrita de dados | — | **INTENÇÃO** (teste de migração exigido pelo gate §8) |
| Migração de schema da fita (versões) | — | **INTENÇÃO** |

## 7. Harness público congelado (requisitos antes de revalidar defaults)

1. Datasets com hash fixado (LongMemEval limpo; LoCoMo; fixtures sintéticos com
   seeds) + dados autorais.
2. Braços: `no_memory | bm25 | dense(≥1) | agents_full | agents_view(+payload)`.
3. Prompts, modelos, juiz (prompt congelado), orçamento e N=3 congelados antes
   de rodar; juiz cego; ≥25% segunda passada com concordância publicada.
4. Modo `--mock` (cliente determinístico) para CI sem chave.
5. Saída: JSONL bruto + `run_manifest.json` (commits/hashes) + tabela com
   ressalvas.
   → **Status atual: PARCIAL** (harnesses existem; falta `--mock` e empacotamento).

## 8. Gate para mudança de defaults (congelado)

Não alterar defaults (`agent_mode`, `whiteboard_mode`, `attention_mode`,
`evidence_payload`) antes de **todos**:

1. nenhuma regressão significativa de resposta (ledger pareado; net acima do
   piso medido no fixture público);
2. evidence recall ≥ 0.90 no harness público (média) e ≥ 0.85 em composição;
3. custo: calls/query ≤ 6 e latência p50 ≤ 15 s por turno (medidos);
4. zero perda/reescrita de dados na migração (teste de migração verde);
5. rollback documentado (uma chave de config volta ao legado);
6. guia de migração compreensível + changelog.
   → **Status: INTENÇÃO** (critérios definidos aqui; execução pendente).

## 9. Lacunas L1–L10 como tarefas verificáveis

| # | Lacuna | Critério de conclusão (verificável) | Evidência exigida |
|---|---|---|---|
| L1 | Empacotamento | `pip install memory-machine` em venv limpo; `memory-cli --help` e `python -m memory_machine init` funcionam; plugin opencode instalado por script do repo | CI matrix + smoke log |
| L2 | Defaults vs arquitetura principal | §8 cumprido; defaults alterados ou conflito documentado em README | ledger + decisão |
| L3 | Contradição/validade | schema + testes adversariais (preferências conflitantes, validade por intervalo, correção parcial) | testes novos verdes |
| L4 | Níveis de retenção | testes de ciclo de vida (event log expira; semântico persiste) | testes + doc |
| L5 | Segurança alvo | níveis de sensibilidade + criptografia em repouso + exclusão verificável + injection guard em anexos | testes adversariais + threat model |
| L6 | Escala | benchmark 1k/10k/100k com p50/p95/p99, calls, tokens, custo, rebuild | script + números publicados |
| L7 | Ablações checklist/metacognição | braços V1/V2 com ledger pareado (piso medido) | resultado + doc |
| L8 | Tagging corrigível | `tag_confidence/tag_source/tag_version` + retagging testado | schema + testes |
| L9 | Rollup semântico | rollup por `schema+scope+validity` preservando estados | testes + resultado |
| L10 | CI + suíte pública | GitHub Actions (3 SOs) verde com 440 testes + smoke `--mock` | workflow + badge |

## 10. Leitura

- A base **testável é forte**: 10 de 14 invariantes têm teste direto; a suíte
  cobre todos os schemas, os três fluxos e a matriz de modos (exceto boards).
- As **garantias científicas de processo** (N11/N12/N14) e a **validação de
  span fora da suíte** (N8) são os pontos mais fracos — são exatamente os que
  transformam "intenção" em auditabilidade de terceiros.
- As **lacunas de produto** (L1/L10) continuam sendo as críticas para
  publicação; L2–L9 dependem delas (sem CI não há prova executável da spec).
- Nada de novo precisa ser medido agora para L1/L10: são engenharia e processo.
