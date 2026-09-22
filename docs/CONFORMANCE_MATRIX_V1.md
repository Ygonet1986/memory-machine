# Memory Machine — Matriz de Conformidade v1.1 (corrigida)

Versão: 1.1 · Data: 2026-09-21 · HEAD: `39b49a1`+correções · Spec: `docs/NORMATIVE_SPEC_V1.md`

**Correções aplicadas nesta revisão** (auditoria documental externa):
N10 resolvido (document layer é camada de ingestão *shipped*, não experimental);
N1/N2/N4/N6/N9 com redação restrita e testes diretos novos; N8 com testes na
suíte; gate reescrito em G1–G8 com métrica/limiar/prova/comando; regra de
contagem de testes não frágil; referências declaram individual vs agregado.

**Método (não frágil).** A prova é: **toda a suíte coletada passa, nenhum
teste esperado desaparece e um piso mínimo evita queda silenciosa.** Nesta
revisão: `pytest -q` → **468 passed** (440 + 28 novos: correções v1.1, L1, guardas do mock e ordem de tópicos). O
manifesto completo de node IDs está em `docs/CONFORMANCE_PROOF.txt` (gerado
por `python3 -m pytest --collect-only -q` neste commit).

**Referências.** Node IDs individuais (`arquivo::teste`) são reais; quando a
referência é agregada (`arquivo.py (N testes)`), ela identifica o módulo, não
um node ID — sem alegação individual.

**Legenda**

| Status | Significado (mecânico) |
|---|---|
| **CONFORME** | código existe **e** teste direto na suíte `tests/` (pytest/CI) |
| **PARCIAL** | código existe; cobertura indireta, parcial ou de processo |
| **INTENÇÃO** | norma-alvo sem implementação |
| **BLOQUEADO** | congelado por gate (Trilepsia) |

---

## 1. Invariantes N1–N14 (redações restritas)

| # | Norma (redação corrigida) | Código | Testes | Status |
|---|---|---|---|---|
| N1 | Projeções **selecionam**; toda evidência persistente atribuída à MM é **reidratável até a fita ou o original preservado** | `tape.py`, `payload.py`, `graph*.py`, `documents.py` | `test_provenance_e2e.py::test_every_graph_row_points_back_to_tape_and_original`; `::test_rehydrated_payload_is_exact_and_traceable`; `test_graph_hooks.py::test_projection_never_touches_the_tape_bytes` | **CONFORME** (escopo restrito) |
| N2 | Toda projeção **implementada** (índice de views, grafo, documentos) é reconstruível; a projeção T2 da Trilepsia não existe (fora de escopo) | `views.py`, `graph.py`, `documents.py` | `test_migration_compat.py::test_views_index_is_a_reproducible_projection`; `test_document_rebuild.py::test_round_trip_rebuild_reproduces_projection`; `::test_plain_build_graph_keeps_graph_v3_projection` | **CONFORME** (escopo declarado) |
| N3 | Evidência com caminho até a memória (e ao original) | `graph_recall.py`, `graph.py` | `test_graph_recall.py::test_relation_provenance_maps_to_memory`; `test_provenance_e2e.py` | **CONFORME** |
| N4 | Anotações são **sinais de seleção**; quando `evidence_payload≠off`, fatos atribuídos à memória vêm do **payload reidratado** (nunca só da nota) | `payload.py`, `main_chatbot.py` | `test_payload.py::test_run_appends_payload_to_context`; `test_main_chatbot.py::test_extra_context_is_in_prompt_but_not_whiteboard` | **CONFORME** (payload ligado; modo legado por notas = limitação declarada) |
| N5 | Payload é efêmero (não acumula no quadro) | `payload.py` | `test_payload.py::test_recall_payload_is_not_persisted` | **CONFORME** |
| N6 | **No modo `budgeted`**, o payload (cabeçalhos incluídos) não excede o orçamento; o modo `full` não dá essa garantia (caveat do primeiro bloco > cap) | `payload.py` | `test_payload.py::test_payload_respects_budget_and_relevance`; `test_provenance_e2e.py` (soma de `used_chars` ≤ 4000) | **CONFORME** (budgeted) |
| N7 | Segredos bloqueiam toda escrita, inclusive envelopes | `secrets.py`, `trilepsia.py` | `test_secrets.py` (7); `test_trilepsia.py::test_envelope_is_secret_scanned`; `test_document_ingest.py::test_secret_chunk_skipped_without_false_provenance` | **CONFORME** |
| N8 | Spans exatos com offsets reversíveis | `eval/evidence_cards.py` | `test_evidence_cards.py` (5: substring exata, offsets reversíveis, paráfrase inválida, budget, determinismo) | **CONFORME** (agora na suíte) |
| N9 | **Imutabilidade de conteúdo**: campos factuais nunca mudam; `status` é metadado administrativo; correção = novo registro; `delete` remove | `tape.py` | `test_tape_immutability.py` (4); `test_tape.py::test_append_is_append_only` | **CONFORME** |
| N10 | **Recall/experimentais off por padrão**; document layer é camada de **ingestão shipped** (creation ON, recall OFF — intencional e testado) | `config.py` | `test_config.py::test_experimental_defaults_are_off`; `::test_graph_defaults_are_off_and_consistent`; `test_document_defaults.py` (4: projeção falha não bloqueia, `enable_graph=False` sem chamada, recall não toca o grafo, reingestão idempotente) | **CONFORME** (classificação corrigida) |
| N11 | Pré-registro congelado antes de executar | processo (`docs/`) | sem teste; artefatos `PLASTICITY_V1`, `COMPOSITION_V1`, `TRILEPSIA_*` | **PARCIAL** |
| N12 | Seleção no braço real não lê gold/verdicts | harnesses `eval/` | sem teste que audite os harnesses | **PARCIAL** |
| N13 | Payload builder determinístico, sem LLM | `payload.py` | `test_payload.py::test_payload_respects_budget_and_relevance` (sem cliente) | **CONFORME** |
| N14 | Piso de oscilação medido como limite mínimo de alegação | processo (`eval/`) | sem teste/CI; medições registradas (U4.2; E-lines) | **INTENÇÃO** |

**Contagem: 11 CONFORME · 2 PARCIAL · 1 INTENÇÃO.**

## 2. Schemas e fluxos

| Norma | Testes | Status |
|---|---|---|
| Schema da fita (campos/status/id) | `test_tape.py` (12); `test_tape_immutability.py` (4) | **CONFORME** |
| Schema do quadro + boards por dimensão | `test_whiteboard.py` (7); `test_dimension_boards.py` (4) | **CONFORME** |
| Schema do payload | `test_payload.py` (11) | **CONFORME** |
| Registro de documentos + originais (hash) | `test_document_ingest.py` (10); `test_document_rebuild.py` (11) | **CONFORME** |
| Grafo (meta/entidades/relações/proveniência) | `test_graph*.py` (agregado: ≈70) | **CONFORME** |
| Trilepsia (envelope/V/queues) | `test_trilepsia.py` (14) | **CONFORME** (camada congelada) |
| Versão de schema + migrações | — | **INTENÇÃO** |
| Fluxo de escrita | `test_coordinator.py`, `test_attachments.py` (9), `test_graph_hooks.py` (13) | **CONFORME** |
| Fluxo de recall | `test_coordinator.py::test_recall_returns_whiteboard`; `test_view_router.py` (13); `test_routing.py` (30) | **CONFORME** |
| Fluxo de checkpoint | `test_coordinator.py::test_checkpoint_writes_back` | **CONFORME** |

## 3. Defaults (teste de configuração limpa)

`test_config.py::test_defaults_are_valid`, `::test_clamps_capacity_and_budgets`,
`::test_non_int_values_fall_back`, `::test_experimental_defaults_are_off`,
`::test_graph_defaults_are_off_and_consistent` → **CONFORME**.
Default-vs-arquitetura-principal permanece **INTENÇÃO** (gate G1–G8).

## 4. Migração e compatibilidade

| Cenário | Teste | Status |
|---|---|---|
| Fita antiga sem campos novos | `test_migration_compat.py::test_old_tape_line_without_new_fields_loads` | **CONFORME** |
| Campos desconhecidos / linha corrompida | `::test_unknown_fields_and_broken_lines_are_tolerated` | **CONFORME** |
| Quadro antigo sem boards | `test_dimension_boards.py::test_legacy_whiteboard_without_boards_loads` | **CONFORME** |
| Troca de modo não escreve na fita | `::test_mode_switch_is_read_only_on_the_tape` | **CONFORME** (estrutural: recall não grava) |
| Anexos pré-campos-novos byte-equivalentes | `test_attachments.py::test_ingest_records_byte_equivalent_without_new_fields` | **CONFORME** |
| Grafo v3 preservado com doc layer off | `test_document_rebuild.py::test_plain_build_graph_keeps_graph_v3_projection` | **CONFORME** |
| Migração de schema versionado | — | **INTENÇÃO** |

## 5. Matriz de modos

| Modo | Testes | Status |
|---|---|---|
| Legado (group/single/off/off) | `test_coordinator.py` (14), `test_groups.py` (9), `test_agents.py` (15) | **CONFORME** |
| Views sem atenção | `test_view_router.py` (13), `test_routing.py` (30) | **CONFORME** |
| Views + atenção | `test_attention.py` (12) | **CONFORME** |
| Views + boards | `test_dimension_boards.py` (4) | **CONFORME** |
| Payload off/budgeted/janela | `test_payload.py` (11) | **CONFORME** |
| Grafo off/on (+documento) | `test_graph_hooks.py` (13), `test_app_graph.py` (9), `test_document_*` (21) | **CONFORME** |
| Trilepsia | `test_trilepsia.py` (14) | **CONFORME** (congelada, off) |

## 6. Gate para mudança de defaults — G1–G8

| # | Critério | Métrica/limiar | Prova exigida | Comando de reprodução | Status |
|---|---|---|---|---|---|
| G1 | Sem regressão significativa de resposta | ledger pareado; net acima do piso medido no fixture congelado; regra: net > piso×N (sem teste estatístico além de binomial reportado) | ledger + piso medido | `python3 eval/... --mock|--live` (harness público) | INTENÇÃO |
| G2 | Evidence recall geral | ≥ 0,90 (média) | tabela por braço | idem | INTENÇÃO |
| G3 | Evidence recall de composição | ≥ 0,85 e sem categoria acima do piso de regressão | tabela por categoria | idem | INTENÇÃO |
| G4 | Categorias críticas | temporal ≥ baseline − piso; nenhuma categoria com regressão > piso | tabela por categoria | idem | INTENÇÃO |
| G5 | Custo online | `calls_online` ≤ 6 por turno (roteador+agentes+metacognição+answerer); `calls_system` reportado separado (judge/embeddings) | telemetria do harness | idem | INTENÇÃO |
| G6 | Latência | p50 ≤ 15 s **e p95 declarado** (limite a definir com dados) | p50/p95 | idem | INTENÇÃO |
| G7 | Zero perda de dados na migração | fita byte-idêntica ao trocar de modo; testes de migração verdes | testes de migração | `pytest tests/test_migration_compat.py` | PARCIAL (estrutural ok; falta harness) |
| G8 | Rollback reproduzível + documentação | uma chave de config volta ao legado; guia + changelog | doc + teste | manual | INTENÇÃO |

## 7. L1–L10 como tarefas verificáveis

| # | Lacuna | Critério de conclusão | Evidência |
|---|---|---|---|
| L1 | Empacotamento | `pip install` em venv limpo; `memory-cli --help`; `python -m memory_machine init`; versão única | **CONCLUÍDO**: wheel `memory_machine-0.2.0` + `scripts/smoke_installed.sh` PASS (venv limpo → wheel → init → remember → recall(mock) → restart → persistência); falta apenas o CI (L10) |
| L2 | Defaults vs principal | G1–G8 cumpridos; decisão registrada | ledger + decisão |
| L3 | Contradição/validade | schema + testes adversariais | testes novos |
| L4 | Níveis de retenção | testes de ciclo de vida | testes + doc |
| L5 | Segurança alvo | sensibilidade/criptografia/injection | testes + threat model |
| L6 | Escala | benchmark 1k/10k/100k (p50/p95, calls, custo, rebuild) | script + números |
| L7 | Ablações checklist/metacognição | braços V1/V2 com ledger pareado | resultado |
| L8 | Tagging corrigível | `tag_confidence/version` + retagging | schema + testes |
| L9 | Rollup semântico | por `schema+scope+validity` | testes |
| L10 | CI + suíte pública | Actions 3 SOs; **toda a suíte coletada passa; nenhum teste esperado desaparece; piso mínimo anti-queda silenciosa**; wheel artifact; modo `--mock` | **CONCLUÍDO (com pendência de plano)**: CI verde na matriz real 3 SOs × py3.11/3.14 (run 35712803264, commit 26f273f; registro em `docs/CI_RECORD.md`; 1 falha Windows corrigida com teste de regressão); tag anotada `v0.2.0`. **Branch protection pendente**: GitHub Pro ou repo público (403 no plano Free para repo privado). `.github/workflows/ci.yml` (3 SOs × py3.11/3.14, wheel, suíte, `verify_proof_manifest.py`, `smoke_installed.py`, dry-runs, artifacts) + `.github/workflows/scientific.yml` (schedule/dispatch, concurrency, timeout, `gate_report.py` tri-estado, artifacts); provas locais: suíte 467, smoke PASS, proof check PASS |

## 7b. Guardas do mock (L10)

`MEMORY_MACHINE_MOCK=1` é a única via para o mock, é detectável (`is_mock`) e
**avisa em stderr na primeira construção** (nunca silencioso); clientes *live*
construídos diretamente não são afetados. Provas: `tests/test_mock_guard.py` (3).

## 8. Harness público congelado (faltante)

Datasets com hash; braços `no_memory|bm25|dense|agents_full|agents_view`;
prompts/juiz/orçamento/N congelados; juiz cego + segunda passada; `--mock` para
CI; JSONL + manifest. **Status: PARCIAL** (harnesses existem; falta `--mock`,
empacotamento e o fixture público único).

## 9. Leitura

- Após as correções, **11 de 14 invariantes têm prova direta** (o que faltava
  era exatamente span/board/imutabilidade/migração — agora cobertos).
- O que resta **não é código**: N11/N12/N14 são garantias de **processo** que
  precisam de CI/auditoria de harness para virarem prova executável (entram em
  L10).
- O gate G1–G8 está operacional (métricas, limiares, provas e comandos), com
  `calls_online` vs `calls_system` e p95 incluídos.
- N10 está resolvido: document layer é camada **shipped** de ingestão
  (creation ON, recall OFF), não experimental — e isso agora está fixado por
  teste.
