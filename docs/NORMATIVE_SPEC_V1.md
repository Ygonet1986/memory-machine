# Memory Machine — Especificação Normativa v1

Versão: 1.0 · Data: 2026-09-21 · HEAD de referência: `9d9a235`
Autor do projeto: Igor Coutrim Lacerda

**Precedência.** Este documento é a referência normativa da arquitetura. O
manual/whitepaper v1.33 continua sendo a fonte histórica e de uso; onde houver
conflito, vale esta especificação. Cada item é marcado:

- `[IMPL]` — implementado e verificável no código (com o teste/arquivo);
- `[ALVO]` — norma decidida, ainda **não** implementada (lacuna declarada);
- `[CONFLITO]` — documentação e código divergem; a resolução está indicada.

---

## 1. Arquitetura normativa atual

A Memory Machine é uma arquitetura de **preservação, organização, seleção e
entrega** de memória para LLMs. O fluxo normativo é:

```
interação → FITA (fonte da verdade)
          → views/projeções (organização no write-time)
          → estado de atenção (continuidade)
          → roteamento (regiões da memória)
          → agentes de perspectiva (anotação)
          → QUADRO BRANCO (memória de trabalho)
          → EVIDENCE PAYLOAD (reidratação orçada)
          → LLM responde
          → checkpoint (novas memórias na fita)
```

Regra de ouro: **a fita guarda a história; o quadro guarda o presente; o
payload entrega a evidência.** Projeções (views, grafo, documentos, Trilepsia)
**selecionam**; a fita e os originais preservados **fornecem o texto**.

### Modos

| Modo | Composição | Estado | Defaults |
|---|---|---|---|
| **Principal (medido)** | view agents + atenção + payload + views | `[IMPL]` atrás de flags; **não** é o default de fábrica | ver §9 |
| **Legado** | agentes por grupo cronológico, quadro único | `[IMPL]` e default | `agent_mode="group"`, `whiteboard_mode="single"` |
| **Experimental** | grafo v3, documento D3–D5, Trilepsia | `[IMPL]` default off; Trilepsia congelada pelo gate | `graph_enabled=false`, `trilepsia_*` off |

`[CONFLITO]` O manual (nota de consolidação v1.0) declara a cadeia de views
como arquitetura principal, mas o código entrega `agent_mode="group"` como
default. **Resolução normativa**: a arquitetura *principal* é a cadeia medida
(H1: view agents 1.00 @5.0 calls vs grupo 0.83–0.97 @15.2); o *default de
fábrica* permanece o legado até que (a) o modo principal seja revalidado no
harness público e (b) a DX de migração exista. Até então, documentar
explicitamente "default conservador; modo principal opt-in".

## 2. Invariantes obrigatórios

| # | Invariante | Estado | Verificação |
|---|---|---|---|
| N1 | A fita é a única fonte da verdade; nenhum componente responde sozinho | `[IMPL]` | §44 manual; código |
| N2 | Toda projeção é reconstruível a partir da fita/originais | `[IMPL]` | `graph rebuild`, `views`; `tests/test_document_rebuild.py` |
| N3 | Nenhuma evidência factual sem caminho até uma memória (e ao original, quando houver) | `[IMPL]` | `graph explain`, `evidence_payload.derived_from` |
| N4 | Anotação ≠ evidência: o conteúdo factual vem do payload/reidratação, nunca da nota | `[IMPL]` | H2; `payload.py` |
| N5 | O payload é efêmero: nunca é acumulado no quadro persistente | `[IMP]` | `payload.py`; docstring |
| N6 | Orçamento de contexto é limite duro (padrão 4000 chars) e filtro protetor | `[IMPL]` | H3; oracle collapse §40.15 |
| N7 | Varredura de segredos bloqueia **toda** escrita na fita, inclusive envelopes/projeções | `[IMPL]` | `secrets.py`; T1 audit fix d311996 |
| N8 | Evidência em cartões/spans deve ser substring exata com offsets reversíveis | `[IMPL]` | `evidence_cards.validate_card`; E0 100% |
| N9 | Atualizar memória = gravar nova memória referenciando a antiga; nunca editar conteúdo | `[IMPL]` | `superseded`; `rehydrate` |
| N10 | Camadas experimentais ficam **off** por padrão e byte-equivalentes quando off | `[IMPL]` | config; 440 testes |
| N11 | Experimentos seguem pré-registro congelado; critérios não são re-ajustados após resultados | `[IMPL]` (processo) | docs/*.md (P, E, gate) |
| N12 | Seleção de evidência em braço real não pode ler gabarito (gold/verdicts) | `[IMPL]` (processo) | guardas E0–E5 |
| N13 | Payload builder é determinístico, sem chamada LLM | `[IMPL]` | `payload.py` |
| N14 | Toda alegação publicada cita medição com piso de oscilação ≥7% (ou maior medido) | `[ALVO]` | §11 |

## 3. Fluxos normativos

### 3.1 Escrita (`[IMPL]`)

```
1. tape.append(memória)                      # SEMPRE primeiro
2. tags de view atribuídas (default_views)   # organização
3. projeções opcionais (grafo/documento)     # nunca bloqueiam a fita
4. manifesto/grupos atualizados
```
Contrato: falha em projeção **nunca** faz rollback da fita; segredo detectado
recusa a gravação.

### 3.2 Recall (`[IMPL]`)

```
1. subject definido no quadro
2. atenção atualiza pesos (decay + reforço)          # se attention_mode≠off
3. seleção de regiões: full | router | views         # roteador é opt-in
4. agentes de perspectiva anotam (1 call/agente, fundido com checklist)
5. merge/dedupe das anotações (maior relevância; orçamento do quadro)
6. consolidação do quadro, se acima do limiar (estado persistido antes)
7. evidence payload reidratado sob orçamento         # se evidence_payload≠off
8. retorno: understanding, checklist, annotations, attached_content, past_hits
```

### 3.3 Checkpoint (`[IMPL]`)

```
1. memórias duráveis gravadas
2. turno gravado (type=memory, dedupe consecutivo)
3. metacognição + checklist atualizados
4. contexto do assistente atualizado (consolidação própria)
```

## 4. Estados e schemas

### 4.1 Memória da fita `[IMPL]`

| Campo | Obrig. | Notas |
|---|---|---|
| `id` M#### | sim | estável, nunca reutilizado |
| `type` | sim | `decision|lesson|preference|bugfix|build|memory|attachment|trilepsia_unit` |
| `summary`, `why` | sim / opcional | — |
| `files`, `created_at`, `status` | opcional | status: `active|archived|superseded` |
| `source` | opcional | `nome#hash12` (dedupe de anexos) |
| `derived_from` | opcional | proveniência (rollups, unidades) |
| `views` | opcional | projeções organizacionais |
| `source_span`, `source_document` | opcional | documento original |
| `trilepsia` | opcional | envelope `{schema_version, extractor, extractor_version, raw, V, dropped}` |

### 4.2 Quadro branco `[IMPL]`

`subject, objective, metacognition/Understanding, checklist, context, pending,
annotations[{memory_id,note,relevance}], consolidated_from, updated_at`; em
`whiteboard_mode="dimension"` também `boards` (semantic/temporal/structural).

### 4.3 Payload `[IMPL]`

Item: `{memory_id, relevance, note, evidence, source, derived_from,
allocated_chars, used_chars, truncated}`; formato
`[id | type | date] + summary + why`; summary preservado, `why` cortado
primeiro; rollups reidratam fontes.

### 4.4 Projeções

- **Grafo** `[IMPL]`: `entities/relations/aliases/mentions/extracted/pending/
  failed/hypotheses/reviews/meta`; `meta` declara schema/extractor/resolver.
- **Documentos** `[IMPL]`: linha D#### com `source, name, hash, path, original,
  spans, extractor, status`; originais em `<root>/documents/`.
- **Trilepsia** `[IMP]` (experimental): unidade tipada com envelope raw, V
  (scope/validity/permissions) e refs; **congelada** (gate net −1).

## 5. Validade temporal e contradição

### 5.1 O que existe `[IMPL]`
`created_at` ISO; status `superseded`; `derived_from` (rollup → fontes);
`time/*` views; H5' (datas reais de sessão + data da pergunta) — o conserto
temporal medido (0.29→0.64). Rollup é **por idade** (limitação conhecida).

### 5.2 Alvo normativo `[ALVO]` (não implementado)
Uma memória precisa poder declarar, no mínimo:

```
valid_from, valid_until      — intervalo de validade factual
asserted_by                  — fonte que afirma
confidence_extraction        — confiança de interpretação do texto
confidence_source            — confiabilidade da fonte
factual_certainty            — certeza factual (separada das anteriores)
verification_status          — unverified|corroborated|contested|refuted
relations: supports | contradicts | supersedes  (append-only, com provenance)
```

Regra: uma preferência conflitante **não** é sobrescrita; registra-se uma nova
memória `contradicts` + `supersedes` com validade. A Trilepsia T1 implementou
parte disso (`kind/state/assumptions`) — o gate mostrou que **estrutura sem
uso medido não paga o custo**; a promoção exige um teste que demonstre uso.

## 6. Retenção e níveis de memória

### 6.1 O que existe `[IMPL]`
"Quase tudo é memorizado": cada turno vira registro `memory` (dedupe), mais
memórias duráveis, anexos e rollups. Controle por status e rollup.

### 6.2 Alvo normativo `[ALVO]`
Separar três níveis (o manual atual trata tudo como um só):

| Nível | Conteúdo | Retenção | Consultável por agentes? |
|---|---|---|---|
| Event log | interação bruta | política (N dias) | não |
| Episódico | resumo do turno/sessão | médio | sim |
| Semântico | fatos e decisões validados | persistente | sim |

Nem todo turno deve virar memória **ativa** consultável. O ganho precisa ser
medido (ruído/custo vs recall) antes de virar default.

## 7. Organização no write-time como hipótese corrigível

`[IMPL]` tags de view são atribuídas na escrita; o índice é reconstruível.
`[ALVO]` toda view inferida deve carregar:

```
tag_confidence  — confiança da classificação
tag_source      — explicit | inferred_by_model | inferred_by_rule
tag_version     — versão do classificador
retaggable      — verdadeiro (a view é hipótese, não verdade)
```

Processo: retagging periódico; busca lexical/densa como rede de segurança;
nunca usar view como filtro único sem fallback (o auto-tag grosso perdeu 1/8
no LongMemEval).

## 8. Defaults e superfície de configuração (verificados no código)

| Chave | Default | Norma |
|---|---|---|
| `capacity` | 500 | manter; documentar custo (~47k tokens/agente no teto) |
| `whiteboard_budget` | 4000 | manter (orçamento do quadro) |
| `consolidate_threshold` | 6000 | manter |
| `context_consolidate_threshold` | 6000 | manter |
| `attach_chunk_size` | 600 | manter |
| `agent_mode` | `group` | `[CONFLITO]` §1 — principal é `view`; default conservador documentado |
| `whiteboard_mode` | `single` | idem (`dimension` medido sem regressão) |
| `attention_mode` | `off` | idem (`state` mede anáfora) |
| `router_enabled` / `router_mode` | `false` / `llm` | opt-in (perde recall nos dados reais) |
| `view_router_mode` | `lexical` | preferir lexical em repro (LLM instável 20/32) |
| `evidence_payload` | `off` | default conservador; `budgeted` é o modo medido |
| `evidence_payload_budget` | 4000 | manter (joelho) |
| `evidence_payload_window` | `false` | opt-in |
| `graph_enabled` / `graph_recall_mode` | `false` / `off` | experimental |
| `document_graph_enabled` | `true` | default atual (revisar com a DX) |
| `trilepsia_*` | off | congelado |

## 9. Segurança e privacidade

| Requisito | Estado |
|---|---|
| Varredura de segredos em toda escrita (regex: sk-, Bearer, PEM, JWT, AKIA, AIza, ghp_) | `[IMPL]` |
| Chave de API só no Keychain (app) / env (CLI); nunca no repo | `[IMPL]` |
| Isolamento de contexto externo (RAG/web nunca tocam fita/quadro/agentes) | `[IMPL]` |
| Anexos como exceção rotulada | `[IMPL]` |
| Níveis de sensibilidade / namespace privado | `[ALVO]` |
| Criptografia em repouso (fita é plaintext) | `[ALVO]` |
| Exclusão verificável (delete reescreve arquivo) | `[ALVO]` |
| Proteção contra prompt injection em documentos | `[ALVO]` |
| Modelo de ameaças + política de privacidade públicas | `[ALVO]` |

## 10. Métricas e protocolo de avaliação (norma)

1. Métricas primárias por natureza: **evidence recall** e **evidence
   completa** (retrieval); **GFR** (ingestão); **strict/lenient/AUR** (resposta);
   **calls/tokens/latência/custo** (custo).  
2. Todo ganho é **pareado por caso**, com N≥3 réplicas e modal; o piso de
   oscilação medido no próprio fixture é o limite mínimo (herdado 7–8% só se o
   fixture não medir o seu).
3. Juiz: prompt congelado, cego ao braço, ≥25% segunda passada com
   concordância reportada.
4. Pré-registro antes da execução; nenhum critério alterado após resultados;
   resultados negativos publicados.
5. Alegação pública só com: (a) paridade de orçamento, (b) piso vencido,
   (c) controles verdes, (d) dados brutos versionados.

## 11. Escalabilidade (requisitos de medição)

`[ALVO]` Antes de qualquer alegação de escala, medir e publicar:

- 1k / 10k / 100k memórias; views desequilibradas;
- latência p50/p95/p99; tokens e custo por consulta;
- taxa de falha do roteador; calls/query; tempo de rebuild;
- degradação após milhares de turnos;
- estratégia de hierarquia de views para views grandes
  (`topic/x → topic/x/sub → ...`) ou view→candidatos→agente.

## 12. Conformidade (como auditar)

| Invariante | Prova mínima |
|---|---|
| N1–N3 | round-trip de rebuild (`test_document_rebuild`), `graph explain` |
| N4/N5 | testes de payload; ausência de payload no whiteboard |
| N6 | teste de orçamento; tabela H3 |
| N7 | `test_secrets` + teste de envelope (T1) |
| N8 | validação de cartões (E0) |
| N10 | suíte completa com flags off (440 testes) |
| N11/N12 | artefatos de pré-registro + ledgers pareados |
| N13 | testes do `payload.py` |

## 13. Lacunas normativas (ordem de prioridade)

| # | Lacuna | Severidade |
|---|---|---|
| L1 | Empacotamento/instalação e integração opencode dentro do repo | Crítica |
| L2 | Defaults vs arquitetura principal (§1) — decidir após revalidação | Alta |
| L3 | Modelo de contradição/validade (§5.2) | Alta |
| L4 | Níveis de retenção (§6.2) | Alta |
| L5 | Segurança: sensibilidade/criptografia/injection (§9) | Alta |
| L6 | Escalabilidade medida (§11) | Alta |
| L7 | Ablações de checklist/metacognição (V1/V2) | Média |
| L8 | Tagging com confiança/retagging (§7) | Média |
| L9 | Rollup semântico (substituir idade) | Média |
| L10 | CI + suíte pública reproduzível com `--mock` | Crítica |

## 14. Compatibilidade e versionamento

`[ALVO]` A fita e as projeções precisam de `schema_version` explícito com
migrações declaradas; mudanças de schema exigem `--rebuild` explícito;
versão do pacote em semver único (corrigir `0.1.0` vs "projeto 1.0").
