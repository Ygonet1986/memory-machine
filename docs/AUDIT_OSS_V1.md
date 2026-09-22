# Memory Machine — OSS readiness audit (v1)

Data da auditoria: 2026-09-21 · HEAD auditado: `9d9a235` · Fontes: manual/whitepaper
v1.33 (documento do autor, lido integralmente), repositório local
(`/Users/igorcoutrimlacerda/memory-machine`, código e testes inspecionados), e
pesquisa web de concorrentes (sources listadas na §7). Este documento separa
explicitamente fatos verificados, alegações do documento, inferências e
estimativas. Onde o texto diz "verificado no repo", o código foi inspecionado
diretamente — o que é uma vantagem desta auditoria, não uma limitação.

## 1. Veredito executivo

A Memory Machine é um sistema de pesquisa **sério, original e incomumente
honesto**, com uma base de engenharia melhor do que o normal para um projeto de
um autor: núcleo stdlib, 440 testes verdes, fita append-only auditável, 15
documentos de projeto, pré-registros congelados, e uma coleção rara de
resultados negativos medidos e mantidos (H4, H6a, dg-v1 F5, P2/P2b, E1/E2/E5,
gate B2 vs B2+ net −1). Ao mesmo tempo, **não é publicável hoje como produto ou
biblioteca para terceiros**:

- não é instalável (sem `pyproject.toml`/`setup.py`; roda via `PYTHONPATH`);
- a integração com opencode (plugin, AGENTS.md, skills, agent) **mora fora do
  repositório**;
- não há CI, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY, CHANGELOG, templates;
- a evidência é interna, com amostras pequenas e um único modelo/provedor;
- as próprias medições mais recentes **refutam** a alegação de superioridade
  agentica em regimes de similaridade direta (LongMemEval) e não demonstram
  valor analítico para a camada Trilepsia (gate: net −1).

**Decisão recomendada: publicar após correções mínimas** (≈3–4 semanas de
trabalho focado, §11 M0), com objetivo inicial de **validação com usuários
early-adopters**, posicionado como *memória local-first, auditável e orçada
para projetos longos* — nunca como "melhor que RAG".

## 2. O que a Memory Machine realmente é hoje

| Camada | Estado verificado | Evidência |
|---|---|---|
| Fita append-only + grupos/agentes | Implementado; 440 testes | código + `pytest` (440 collected) |
| Whiteboard + metacognição + checklists | Implementado; sobrevive à consolidação | código, manual §12–13 |
| Views/projeções | Implementado; `views.py`, CLI `views`, filtro `--views` | código, manual §11.9 |
| Router de partições | Implementado, **opt-in**, 3 modos; perde recall nos dados reais | manual §11.7/§8.7 |
| Attention state | Implementado (prior/context/state; decaimento) | manual §40.9 |
| Evidence payload | Implementado (`off|budgeted|full`), joelho ~4000 chars | manual §40.11–40.13; `payload.py` |
| Consolidação/rollup/rehidrate | Implementado; rollup por idade + `derived_from` | código, manual §15 |
| Cross-session | Implementado (BM25 nas fitas antigas) | manual §17 |
| Anexos .txt + documento (D3–D5) | Implementado; originais com hash-gate, rebuild atômico | código, `tests/test_document_rebuild.py` |
| Grafo v3 (projeção) | Implementado, **default off**; extração instável medida | código; dg-v1 F5 FAIL |
| App macOS | Implementado (PySide6); DMG assinado ad-hoc, sem notarização | `dist/`, manual §21 |
| CLI | Implementado (~20 comandos, JSON) | `cli.py` |
| Plugin opencode | Implementado, **224 linhas, fora do repo** | `~/.config/opencode/plugins/memory.ts` |
| Trilepsia (T2TC, T1) | Implementado, **default off**, gate falhou (proveniência) | `trilepsia.py`, `docs/TRILEPSIA_GATE_V1.md` |
| Ablações V0–V7 | **Planejadas, não executadas** | manual §41 |
| Paper | Esqueleto | manual §43 |
| Usuários externos | **Nenhum** | declarado pelo autor |

| Classificação | Itens |
|---|---|
| Implementado e testado diretamente | fita, grupos/agentes, whiteboard, metacognição, checklists, consolidação, retrieval BM25, sessões, anexos, views, payload, app, CLI, plugin, grafo/doc layer, trilepsia T1 |
| Medido experimentalmente (interno) | H1–H6 (H5' confirmada; H4/H6a refutadas), GFR/ingestão, H3 (parcial relativa), roteamento/topologia, e2e, E1/E2/E5, gate B2 vs B2+ |
| Apenas planejado | ablações V0–V7, embeddings completos, router de sessões, rollup semântico, múltiplos assistentes, export/import, visualizações |
| Hipótese/alegação do autor | "vantagem agentica onde a relevância é contextual"; "budget é filtro protetor"; T2TC como direção |
| Não confirmável sem execução externa | custo/latência reais em uso contínuo; qualidade do recall em fitas >10k; utilidade percebida por usuários |

## 3. Pontos fortes comprovados ou promissores

1. **Auditabilidade radical**: fita imutável, `derived_from`, `rehydrate`,
   hash-gate de originais, spans exatos, pré-registros congelados. Isso é o
   diferencial mais defensável e raro no mercado.
2. **Disciplina experimental com resultados negativos mantidos** (H4, H6a,
   dg-v1, P2/P2b, E1/E2/E5, gate). Raro e reputacionalmente valioso.
3. **"Budget como filtro protetor"** com dados que mostram colapso do contexto
   ilimitado (oracle 0.08→0.00 em multi-session) — achado contraintuitivo e
   publicável com ressalvas.
4. **GFR/ingestão**: o fato sumia **antes** do retrieval (0.42→0.83; evidence
   recall constante) — diagnóstico de alto valor didático.
5. **H5' (proveniência temporal)**: 0.29→0.64 no temporal; 4/9→9/9 com
   evidência completa. Conserto arquitetural, não de prompt.
6. **Núcleo sem dependências** (stdlib; `certifi` opcional): instalação
   trivial em qualquer SO; superfície de segurança pequena.
7. **Checklists como memória prospectiva**: enquadramento conceitual forte
   (manual §13.4), sem ablação ainda.
8. **Licença MIT**, 440 testes, documentação interna extensa (SPEC 1.315 linhas,
   15 docs), app + CLI + plugin reais, dogfooding de 104 commits.
9. **E5/recente**: mesmo com veredito de consolidação, os dois braços do E5
   tiveram **zero regressões** (+3 e +4 reparos) — sinal direcional útil para o
   futuro.

## 4. Principais falhas, riscos e lacunas

| # | Severidade | Problema | Evidência | Impacto |
|---|---|---|---|---|
| F1 | Crítico | Não instalável como pacote (`pip install`) | sem `pyproject.toml`/`setup.py` (verificado) | bloqueia adoção |
| F2 | Crítico | Integração opencode fora do repo | plugin/skills/AGENTS.md em `~/.config` | terceiros não reproduzem o caso de uso principal |
| F3 | Crítico | Sem CI e sem suíte em 3 SOs | sem `.github/` (verificado) | regressões silenciosas; credibilidade |
| F4 | Alto | Evidência interna, amostras pequenas (12–50q), 1 modelo (deepseek-v4-flash) | manual §40–42 | alegações frágeis vs concorrência (mem0 publica 92.5 LoCoMo) |
| F5 | Alto | Custo/latência por turno: N chamadas de agente por mensagem | manual §8.1; view agents 3–5 calls | inviável em uso intenso sem router (que perde recall) |
| F6 | Alto | Teto externo baixo (~0.56–0.64 strict) e composição não resolvida | manual §40.15; E1/E5 | utilidade percebida em perguntas difíceis |
| F7 | Alto | Recuperação temporal com evidência incompleta (5 erros restantes) | manual §40.17 | gap aberto no eixo mais vendável |
| F8 | Alto | Sem validação de usuários, sem métricas de uso real | declarado | risco de construir para si mesmo |
| F9 | Alto | Sem SECURITY.md/modelo de ameaças/privacidade; fita em texto plano | manual §25 (só segredos) | adoção corporativa inviável |
| F10 | Médio | Versão inconsistente (`0.1.0` no código vs "projeto 1.0") | verificado | confusão de releases |
| F11 | Médio | Complexidade ativa não evidenciada: grafo/doc/Trilepsia em código | dg-v1 F5 FAIL; gate net −1 | superfície que não paga aluguel |
| F12 | Médio | Instabilidade de extração/seleção LLM (20/32; plano de views muda) | manual §40.6b | reprodutibilidade de resultados |
| F13 | Médio | App macOS-only, ad-hoc, sem notarização; dependências PySide6 | manual §21 | fricção de instalação |
| F14 | Médio | Consolidação por idade pode destruir validade factual | manual §15.3; corrigido só na Trilepsia | perda epistemológica |
| F15 | Baixo | Fixtures/avaliações dependem de caminhos voláteis (`/tmp`) em harnesses históricos | verificado (E-lines) | reprodutibilidade de terceiros |
| F16 | Baixo | Sem demo visual/GIF/badges; README PT/EN misto | verificado | conversão de visitantes |

## 5. Auditoria componente por componente

| Componente | Problema que resolve | Benefício real medido | Custo/complexidade | Riscos/modos de falha | Evidência | Alternativa | Recomendação |
|---|---|---|---|---|---|---|---|
| **Fita append-only** | histórico imutável e auditável | base de tudo; 440 testes | baixo (JSONL) | crescimento; texto plano | código+testes | SQLite | **Manter** |
| **Grupos + agentes por partição** | triagem O(N) com contexto local | achou o que BM25 perdia (0.33→1.00 sintético; LoCoMo 0.90) | alto: 15–16 calls/query | ruído/variação; custo | §8.7, §40.10 | BM25/dense por query | **Simplificar**: view agents como padrão; grupo = modo compat |
| **Whiteboard + boards** | memória de trabalho limitada | 1.00 evid sem regressão com boards | médio | consolidação perde contexto | §40.7 | resumo rolante | **Manter** |
| **Metacognição/checklists** | memória prospectiva | conceito forte; sem ablação | médio (1 call/turno) | checklist virar ruído | §13, §41 (V1/V2 pendentes) | instruções estáticas | **Testar melhor** (ablação) |
| **Views/projeções** | organização no write-time | C1 0.97 vs similarity 0.72 | baixo | views ruidosas/auto-tag grosso (7/8) | §40.4–40.8 | tags manuais | **Manter** (e melhorar tagger) |
| **Router (partições/views)** | reduzir fan-out | -Custo com perda; lexical 0.39; view-LLM 1.00 @15 calls | médio | instabilidade LLM 20/32 | §8.7, §40.6b | varredura completa | **Manter opt-in**; preferir lexical determinístico em repro |
| **Attention state** | continuidade/anáfora | anáfora 5.7 calls vs 10.7–16; under/over-persistence medidas | baixo | stickiness (bug já corrigido) | §40.9 | sempre full sweep | **Manter** |
| **Evidence payload** | entregar o fato sob orçamento | H2 0.72→0.88; H3 relativa; joelho 4000 | baixo (determinístico) | truncamento mata fato (U-phase) | §40.11–40.13 | full text | **Manter — é o componente mais bem evidenciado** |
| **BM25/embeddings** | recuperação base | BM25 forte no lexical; dense forte no LongMemEval; LoCoMo fraco | baixo/opcional | dependência de provedor de embeddings | §40.2 | dense-only | **Manter ambos, opt-in** |
| **Consolidação/rollup/rehidrate** | controlar crescimento | reidratação evita perda cognitiva | médio | rollup por idade destrói validade | §15.3, §11.8 | consolidação semântica | **Manter + rollup semântico** |
| **Cross-session** | continuidade entre sessões | real no dogfooding | médio (BM25 em N fitas) | custo cresce com sessões | §17 | índice global | **Manter**; router de sessões depois |
| **Grafo v3 + documento** | relações/estrutura | proveniência documental robusta | alto | extração instável (dg-v1 F5) | dg-v1 | não ter | **Testar/adiar**: manter off, não vender |
| **Anexos .txt** | memorizar documentos do usuário | GFR 0.42→0.83 (ingestão) | baixo | volume/agentes | §18, §40.12 | RAG puro | **Manter** |
| **Proveniência temporal** | perguntas temporais | H5' 0.29→0.64; 9/9 | baixo | depende de datas na ingestão | §40.15 | prompts temporais (refutado) | **Manter — prioridade de marketing** |
| **Trilepsia (T1)** | investigação tipada | 0 ganho analítico medido (net −1) | alto (LLM/ingest) | complexidade sem retorno | gate §8 | nada | **Congelar** (off, experimental) |
| **Escalabilidade** | fita cresce | escala em nº de agentes | alto: capacity 500 ≈ 47k tokens/agente | custo/latência; contexto por agente | manual §11.1 | hierarquia/sumarização | **Testar a 1k/10k/100k** antes de prometer |
| **Segurança** | evitar segredos na fita | bloqueio verificado (440 testes) | baixo | sem modelo de ameaças; plaintext; sem criptografia | código/`secrets.py` | criptografia em repouso | **Manter + documentar** |

## 6. Avaliação dos experimentos e benchmarks

**Metodologia boa**: pré-registro congelado, juiz cego com prompt congelado,
replicação, ledger pareado, taxonomia de falhas, controles mantidos (evid/GFR),
resultados negativos preservados, artefatos brutos versionados.

**Riscos e lacunas**:
- amostras pequenas (12–50q; 24–32 tarefas sintéticas); sem intervalos de
  confiança nem power analysis fora da linha E;
- um único modelo/provedor (deepseek-v4-flash) e um único juiz; concordância
  auditada em subamostra (0.75–1.0), mas sem juiz humano;
- fixtures sintéticos com views perfeitas por construção; auto-tag externo com
  taxonomia grossa (perdeu 1/8);
- comparações com baselines rodam no mesmo harness, mas os números não são
  comparáveis aos publicados pelos concorrentes (pipelines diferentes);
- a acurácia absoluta no LongMemEval é baixa (0.56–0.64) — publicar exige
  deixar isso explícito;
- risco de overfitting de harness: correções feitas para o fixture (ex.: datas)
  precisam ser re-validadas em outro corpus;
- a lacuna "sem answer accuracy com juiz" **foi fechada depois** (e2e_bench),
  mas com 32 golds autorais.

**Suíte mínima reproduzível proposta** (1 comando por braço):
1. congelar datasets: hash de `longmemeval_s_cleaned`, LoCoMo, fixtures
   sintéticos (com seeds) e golds autorais;
2. braços: `no_memory | bm25 | dense(2 modelos) | agents_full | agents_view |
   view+payload`, com N=3 réplicas e modal;
3. métricas: evidence recall, evidence completa, GFR, strict/lenient/AUR,
   calls/tokens/latência, custo estimado;
4. juiz: prompt congelado + 25% segunda passada + relatório de concordância;
5. saída: JSONL bruto + `run_manifest.json` com commits/hashes/shas;
6. modo `--mock` (cliente LLM determinístico) para CI sem chave;
7. tabela final com **ressalvas explícitas** e modo de falha dominante.

## 7. Comparação com concorrentes

Pesquisa em 2026-09-21 (fontes: repositórios/páginas oficiais; ver abaixo).
Onde a página não foi verificada nesta passada, está marcado.

| Dimensão | **Memory Machine** | **mem0** (65.8k★) | **Graphiti/Zep** (31.1k★) | **Letta** (24.8k★) | **LangMem** (1.7k★) | **Windsurf/Devin memories** |
|---|---|---|---|---|---|---|
| Arquitetura | fita + agentes por view/grupo + whiteboard + payload | extração ADD-only + multi-sinal (semântico+BM25+entidades) | grafo temporal bi-temporal (fatos com validade) | agentes stateful (sucessor do MemGPT) | ferramentas de memória + manager em background | memórias auto-geradas por workspace + rules/AGENTS.md |
| Persistência | JSONL local (arquivos) | vetor/DB via SDK; servidor self-hosted; nuvem | Neo4j/FalkorDB/Neptune | DB do runtime; nuvem | store do LangGraph (memória/Postgres) | local `~/.codeium/windsurf/memories/` |
| Temporal | sim (H5': datas reais) + rollup por idade | temporal reasoning (alegado) | **bi-temporal com invalidação** | sim (histórico de mensagens) | básico | não explícito |
| Grafo | projeção opt-in (instável medida) | entity linking (não grafo completo) | **grafo completo** | não | não | não |
| Integração coding agents | plugin opencode (fora do repo) | **skills/CLI para Claude Code, Codex, Cursor, Windsurf, OpenCode, OpenClaw** | MCP server + REST | TUI, desktop, canais (Slack etc.) | LangGraph | nativo no editor |
| Local/privacidade | **100% local, sem telemetria** | local possível; nuvem padrão | self-hosted; telemetria opt-out | local/nuvem | local | local |
| Escala | não medida > ~centenas | produção (alegada) | milhões de grafos (Zep) | produção | produção LangGraph | desktop |
| Licença | **MIT** | Apache-2.0 | Apache-2.0 | Apache-2.0 | MIT | proprietário |
| Benchmarks publicados | internos, amostras pequenas | **LoCoMo 92.5 / LongMemEval 94.4 (abr/2026, plataforma gerenciada; OSS "directionally similar")** | paper arXiv 2501.13956 (Zep) | — | — | — |
| Maturidade/comunidade | 104 commits, 1 autor, 0 usuários externos | 2.640 commits, 65.8k★, YC S24 | 986 commits, 31.1k★, empresa | 7.474 commits (repo antigo), empresa | 153 commits, LangChain | produto comercial |
| Custo | chave do usuário; N calls/turno | nuvem paga ou self-host | DB próprio + LLM | nuvem/self-host | LLM | incluso no editor |

**Leitura honesta**: a MM não compete hoje em biblioteca, escala, integrações
nem benchmarks. Seus diferenciais reais são: (a) auditabilidade/proveniência
local, (b) whiteboard + checklists (memória prospectiva), (c) entrega orçada
com evidência de que o orçamento protege, (d) núcleo sem dependências, (e)
honestidade experimental. O sinal mais forte de mercado é que o mem0 **já
publica integração com opencode** — ou seja, a "memória para agentes de
programação" está sendo disputada ativamente.

Fontes (verificadas 2026-09-21): github.com/mem0ai/mem0; github.com/getzep/graphiti;
github.com/letta-ai/letta; github.com/langchain-ai/langmem;
docs.devin.ai/windsurf/cascade/memories (conteúdo de Memórias/Rules do Windsurf).
Não verificados nesta passada: Cursor memories (a página buscada retornou o
índice), Cline memory bank, Copilot memory, MemOS/A-MEM, Khoj.

## 8. Prontidão para publicação open source (checklist verificado no repo)

| Item | Estado | Ação |
|---|---|---|
| Licença | **MIT** presente | ok |
| README | bom conteúdo (356 linhas) mas instalação via PYTHONPATH | reescrever Quickstart para `pip install`/instalador |
| Guia de instalação | só `PYTHONPATH` + app macOS | criar instalador + `pipx`/`pip` |
| Quickstart | funciona; sem verificação em máquina limpa | script CI `quickstart smoke` |
| Exemplos | eval/ e docs; nenhum "hello memory" mínimo | exemplo de 20 linhas |
| Arquitetura documentada | SPEC + 15 docs | ok (traduzir/ordenar público) |
| API/contratos | CLI JSON estável de fato; sem versão de API | documentar schema da fita/CLI |
| Versionamento | `__version__="0.1.0"` vs "projeto 1.0"; tags existem | unificar semver (0.2.0) |
| Testes | **440 verdes** | adicionar CI 3 SOs + cobertura |
| CI/CD | **ausente** | GitHub Actions: pytest + lint + smoke |
| Compatibilidade | núcleo 3.11+; app macOS | declarar matrix; app só macOS |
| Segurança | varredura de segredos; chave no Keychain (app) e env (CLI) | SECURITY.md + modelo de ameaças + criptografia opcional |
| Gestão de segredos | boa no app; CLI em env/keychain | documentar |
| Telemetria | **nenhuma** | declarar explicitamente (vantagem) |
| Política de privacidade | ausente | criar (dados ficam locais) |
| Modelo de ameaças | ausente | criar (fita plaintext, multi-sessão, anexos) |
| Relato de vulnerabilidades | ausente | SECURITY.md |
| Guia de contribuição | ausente | CONTRIBUTING.md |
| Código de conduta | ausente | COC (Contributor Covenant) |
| Templates de issues | ausentes | bug/feature templates |
| Roadmap | manual sugere; sem ROADMAP público | publicar roadmap enxuto |
| Changelog | ausente | CHANGELOG.md + releases com notas |
| Processo de releases | tags apenas | GitHub Releases + semver |
| Suporte/manutenção | implícito | declarar expectativas ("best effort") |
| Demonstração reproduzível | harnesses internos | 1 comando + `--mock` |

## 9. Objetivo recomendado para o primeiro lançamento

**Validação com usuários early-adopters** (não contribuições, não reputação).

Justificativa: solo + orçamento limitado + zero usuários + sistema complexo +
evidência interna. Contribuições técnicas exigem DX maduro (que não existe);
reputação é consequência; produto é prematuro sem retenção. Um lançamento
pequeno com 5–10 desenvolvedores usando em projetos reais gera o ativo que
falta: **dados de uso e feedback**. Métricas de sucesso do lançamento:
4/5 completam o quickstart em <15 min; 3/5 continuam usando após 1 semana;
≥10 issues qualificadas (bugs/DX), com o autor resolvendo ≥50% em 2 semanas.

## 10. Proposta de posicionamento

> **Memory Machine — memória local-first, auditável e orçada para projetos
> longos com agentes de programação.**
> Sua fita é a fonte da verdade; o quadro é o presente; a evidência é entregue
> sob orçamento com proveniência. Nada sai da sua máquina.

Claims permitidos: "local, sem telemetria, MIT"; "proveniência e reidratação";
"orçamento como filtro protetor (com evidência)"; "agentes por perspectiva
reduzem custo em regimes contextuais (com evidência)". Claims proibidos:
"melhor que RAG"; "superior ao dense"; "resolvemos memória temporal";
"composição resolvida". Público: devs que rodam agentes em monorepos/projetos
longos e se importam com auditoria e privacidade.

## 11. Plano de melhorias para seis meses

| Fase | Prioridade | Objetivo | Trabalho | Dependências | Esforço | Custo | Risco | Critério de conclusão |
|---|---|---|---|---|---|---|---|---|
| **M0 (3–4 sem, antes de publicar)** | Obrigatório | Tornar instalável e verificável | `pyproject.toml` + `pip install -e .`; mover plugin/skills/AGENTS para `integrations/opencode/` com instalador; CI GitHub Actions (3 SOs, pytest, smoke quickstart, lint); CONTRIBUTING/COC/SECURITY/templates/CHANGELOG; modelo de ameaças+privacidade; semver 0.2.0; quickstart em máquina limpa; `--mock` nos eval | repo público | 3–4 sem | ~0 | escopo | `pip install memory-machine` + smoke verde em CI nos 3 SOs; quickstart <15 min |
| **M1 (2 sem)** | Obrigatório | Publicar v0.2 | README EN-first; demo (GIF + cenário 30 min); release com notas; Discussions; tabela de evidências com ressalvas | M0 | 2 sem | ~0 | baixo | release publicada; 10+ stars orgânicos; 5 issues |
| **M2 (4–6 sem)** | Importante | Validar com usuários | Recrutar 5–10 devs; onboarding guiado; logs locais opt-in (latência/calls/hits); entrevistas; corrigir top-10 DX | M1 | 4–6 sem | ~0 (LLM do usuário) | abandono | ≥4/5 com primeiro recall <15 min; ≥3/5 usando em 1 semana |
| **M3 (4 sem)** | Importante | Endurecer avaliação | Suíte mínima reproduzível (§6) no CI semanal; escalabilidade 1k/10k/100k memórias; tabela custo/latência/qualidade; 2 modelos respondentes | M0 | 4 sem | baixo (calls) | overfitting de harness | números reproduzíveis por terceiros; CI semanal verde |
| **M4 (3 sem)** | Importante | Simplificar arquitetura | View agents como padrão; grupo como compat; rollup semântico; grafo/doc/Trilepsia marcados experimentais (default off, fora do marketing) | M2 | 3 sem | ~0 | regressões | suíte verde; defaults documentados; menos código no caminho principal |
| **M5 (4 sem)** | Desejável | Comunidade/reputação | Preprint/workshop (H5', GFR, budget, regimes); 1 contributor onboarded; governança mínima | M2/M3 | 4 sem | ~0 | tempo | submissão feita; 1 PR externo mergeado |
| **M6 (2 sem)** | Desejável | Decidir produto | Avaliar retenção/willingness-to-pay; decidir nuvem vs local-only; manter API separável | M2–M5 | 2 sem | ~0 | direção | decisão registrada |

**Adiar/remover**: expansão Trilepsia/T2TC (**bloqueada pelo gate**);
roteador de sessões; embeddings completos por padrão; export/import de times;
múltiplos assistentes; app Windows/Linux; notarização (só quando houver
usuários); qualquer feature de monetização.

## 12. Checklist mínimo antes da publicação

- [ ] `pyproject.toml` + instalação limpa testada (`pipx install`)
- [ ] Plugin/skills/AGENTS.md **dentro do repo** + instalador documentado
- [ ] CI verde (Linux/macOS/Windows do núcleo; app macOS)
- [ ] Quickstart smoke em máquina limpa (script CI)
- [ ] CONTRIBUTING, COC, SECURITY, issue templates, CHANGELOG, ROADMAP
- [ ] Modelo de ameaças + privacidade (dados locais; fita plaintext; anexos)
- [ ] Versão semver única; Release com notas; tag anotada
- [ ] Demo de 30 min com custo/latência medidos
- [ ] Suíte de avaliação reproduzível (`--mock`) com hashes de dataset
- [ ] Linguagem de claims revisada (tabela proibida da §10)
- [ ] Declaração de suporte ("best effort, solo maintainer")

## 13. Experimentos com os primeiros usuários

1. **Onboarding**: 5 devs, máquinas limpas, sessão gravada; medir tempo até
   primeiro recall cross-session; pontos de fricção.
2. **Diário de 1 semana**: uso real em 1 projeto; métricas locais opt-in
   (calls/dia, latência, taxa de recall não-vazio, memórias/dia).
3. **A/B de README**: "memória para agentes" vs "proveniência/auditoria";
   medir instalação e retenção de 7 dias.
4. **Tarefa de confiança**: pedir para auditar uma decisão antiga até a fonte
   (testa o diferencial real); medir sucesso e tempo.
5. **Entrevista de falha**: apresentar um erro de recall/answer e medir se o
   usuário entende o modo de falha e mantém confiança.

## 14. O que deve ser adiado ou removido

| Item | Ação | Motivo |
|---|---|---|
| Expansão Trilepsia/T2TC | **Adiar (congelado)** | gate B2 vs B2+ não demonstrou ganho analítico |
| Grafo/document graph no marketing | Adiar | extração instável medida (dg-v1 F5) |
| Roteador por padrão | Manter opt-in | perde recall nos dados reais |
| Embeddings completos por padrão | Adiar | denso é regime-dependente |
| Router de sessões; multi-assistente; export/import | Adiar | sem demanda validada |
| App Windows/Linux | Adiar | custo alto, usuários zero |
| Monetização/telemetria | Adiar | não é prioridade; telemetria ausente é vantagem |
| Consolidação por idade como padrão | **Substituir** | destrói validade factual |

## 15. Informações adicionais necessárias para uma auditoria definitiva

1. URL pública do repo e issues (licença/CI já verificados localmente).
2. Dados de uso real (mesmo de 1 usuário) com calls/latência/custo por sessão.
3. Escalabilidade medida em 1k/10k/100k memórias (calls/query, tokens,
   latência, tamanho de prompt por agente).
4. Concordância inter-juiz e validação humana de uma amostra do e2e.
5. Confirmação de que a app pode ser reproduzida em máquina limpa
   (build.sh + notarização decida).
6. Plano de compatibilidade de schema da fita (migrações/versões).

## Conclusão principal

A Memory Machine tem o que a maioria dos projetos de memória não tem:
**proveniência auditável, resultados negativos honestos e um mecanismo de
entrega (payload orçado) com evidência real de proteção contra contexto
excessivo**. O que falta não é pesquisa: é **produto e distribuição** —
empacotamento, integração dentro do repo, CI, governança e validação externa.
Ela deve ser publicada como um **motor de memória local, auditável e
experimental**, com claims estritamente limitados ao que foi medido.

### Maiores ressalvas e incertezas
- Evidência interna, amostras pequenas, um único modelo; nada replicado por
  terceiros.
- O teto externo (~0.56–0.64) e a composição não resolvida limitam o valor
  percebido em perguntas difíceis.
- Custo por turno (N agentes) sem telemetria real de uso.
- A camada de investigação (Trilepsia) foi implementada mas **não** demonstrou
  valor — risco de confundir sofisticação com utilidade.
- Esforço estimado do plano é incerto (solo, tempo parcial).

### Melhor próxima ação concreta
**M0 sprint**: `pyproject.toml` + mover a integração opencode para o repo +
instalador + CI verde + quickstart limpo + CHANGELOG/SECURITY. Uma semana de
trabalho entrega "um estranho consegue instalar e rodar".

### Cinco ações de maior prioridade
1. Empacotar (`pip install`) e publicar instalador (F1).
2. Mover plugin/skills/AGENTS para o repo com instalador (F2).
3. CI + smoke + templates/community files (F3).
4. Suíte de avaliação reproduzível com `--mock` e hashes (F4/F15).
5. Validar com 5 devs com métricas de onboarding e retenção (F8).

### Decisão
**Publicar após correções mínimas.** Não publicar agora (quebraria a confiança
de terceiros no primeiro contato), nem adiar (a janela competitiva está aberta
e o M0 é curto).
