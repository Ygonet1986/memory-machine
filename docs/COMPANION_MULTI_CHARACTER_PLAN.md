# Companion: múltiplos personagens e vidas sintéticas

Status: plano de implementação, 2026-09-24. Não altera o produto nem promove
resultados de avaliação. Base: Companion v0.2.6, contrato
[`COMPANION_V0_CONTRACT.md`](COMPANION_V0_CONTRACT.md).

## 1. Objetivo

Permitir que uma pessoa crie e converse com vários personagens. Cada personagem
tem identidade, voz, valores, limites, biografia e uma **vida ficcional anterior
ao primeiro chat**, representada por acontecimentos sintéticos com datas,
lugares, relações e consequências coerentes. O criador oferece edição e
aprovação antes de ativar a personagem. A conversa acrescenta experiências da
relação sem alterar retroativamente a vida aprovada.

Exemplo: Lia pode lembrar que aprendeu violão com a avó numa cidade inventada.
Ela pode contar isso como parte de sua história ficcional; não pode dizer que
ela e a pessoa viveram esse episódio juntas. Uma segunda personagem pode ter
outra vida. A memória da pessoa e os episódios de cada relação continuam
isolados.

### Critério de produto

- Criar uma personagem sem editar JSON; pré-visualizar voz, ficha e linha do
  tempo; aprovar uma versão explícita.
- Trocar de personagem ou continuidade sem misturar fatos, IDs, histórias ou
  lembranças de conversas.
- Inspecionar, corrigir, excluir e regenerar eventos sintéticos e compreender
  quais resumos derivados serão afetados.
- Perguntar por um evento da vida da personagem e obter resposta ancorada em
  evento aprovado, com a natureza ficcional clara.
- Manter `save-off` com zero bytes no root canônico durante o turno.

## 2. Estado atual e dependência de qualidade

O v0 já fornece root por pessoa/personagem/continuidade, ficha `persona`
versionada, `story`, correção, exclusão em cascata, motor headless e UI. A demo
v1 registrada em [`COMPANION_DEMO_V1_PREREG.md`](COMPANION_DEMO_V1_PREREG.md)
teve `all_pass=false`: extração de `story` ausente, exclusão de um fato sem
alcançar um irmão semântico e menções negativas que reprovaram gates textuais
de correção/isolamento. Este plano **não** interpreta CI verde como aceitação
do comportamento conversacional. Antes de alegar prontidão para piloto,
registrar uma avaliação nova que cubra essas falhas e as novas vidas sintéticas.

## 3. Modelo conceitual e fronteiras

| Camada | Escopo | Exemplo | Autoridade |
| --- | --- | --- | --- |
| Modelo de personagem | Catálogo local de templates, sem dados da pessoa | Lia v1 | Rascunho reutilizável |
| Ficha aprovada | Uma cópia versionada no root da relação | Voz e valores da Lia | Especificação aprovada da personagem |
| Vida sintética | Eventos ficcionais aprovados, copiados para o root | Aprendeu violão com a avó | Cânone ficcional, nunca biografia real da pessoa |
| Relato da pessoa | Turnos desta relação | “Eu toco piano” | Relato, sem verificação independente |
| Episódio conjunto | Turnos reais desta relação | Conversa de terça | Evento de conversa, não evento da vida prévia |
| História improvisada | Continuidade narrativa escolhida | A ilha que imaginaram | Ficção da continuidade |
| Hipótese | Interpretação provisória | Talvez prefira jazz | Tentativa; não vira fato sem confirmação |

O root canônico permanece
`<base>/companion/<person_id>/<character_id>/<continuity_id>/`. O catálogo
contém apenas templates públicos ou locais; **nunca** agrega fatos privados de
roots. Uma definição pode ser reutilizada por várias pessoas, mas cada root
recebe snapshot aprovado de sua versão. Nenhum recall atravessa roots. IDs de
registro (`M0001` etc.) são locais; referências externas exigem importação
explícita com remapeamento de IDs.

Vida sintética **não é** `person_report` nem `episode`. Preferir usar registros
`story` com `origin.kind="synthetic_life_event"`, `event_id`, `life_version`,
`continuity_id` e proveniência da ficha aprovada. Como o contrato atual exige
turno de origem para `story`, esta admissão deve ser uma via separada e
explicitamente aprovada; **não** forjar turnos de pessoa para satisfazer o
extrator de conversas. Se for preciso alterar o contrato dos cinco tipos,
documentar isso num PR de contrato antes do código. O campo `type` continua
`story`, sem criar um sexto tipo silenciosamente.

## 4. Dados propostos

```text
personas/<slug>/vN.json                    # template versionado no repositório
<root>/persona/current.json                # ficha aprovada neste root
<root>/persona/history/vN.json             # revisões aprovadas
<root>/synthetic_life/current.json         # versão ativa, seed e índice de eventos
<root>/synthetic_life/history/vN.json      # snapshots aprovados, inclusive retirados
<root>/tape.jsonl                          # registros story e memórias da relação
```

`character_id` é ID opaco e imutável, separado de `display_name`. Não usar
nome visível ou caminho fornecido pelo modelo como componente de root.
`continuity_id` decide em qual universo o evento é válido; uma versão da vida
é aprovada **por continuidade**. O modelo pode ser compartilhado, mas a vida
aprovada e sua evolução pertencem ao root da relação. Compartilhar a mesma
vida entre roots, se desejado futuramente, exige uma ação explícita de
importação e snapshots independentes.

Esquema mínimo de um evento sintético (exemplo de forma, não fixture aprovada):

```json
{
  "event_id": "life-0007",
  "life_version": 1,
  "title": "Primeira apresentação",
  "summary": "Lia apresentou uma composição num festival fictício.",
  "event_time": "2018-06-10",
  "time_precision": "day",
  "place": "cidade ficcional aprovada",
  "participants": ["lia", "avo_lia"],
  "causes": ["life-0003"],
  "effects": ["life-0008"],
  "status": "draft",
  "provenance": {"kind": "synthetic_life", "generator": "manual", "sheet_version": 1}
}
```

Regras: `event_id` é estável dentro da continuidade; `event_time` pode ser
desconhecido ou ter precisão de ano/mês/dia, sem inventar dia exato. Referências
de causa e efeito apontam para eventos locais existentes e formam um grafo
acíclico temporal. Participantes têm IDs locais e papéis definidos. A ficha
inclui data de referência/idade ou deixa ambas indefinidas; idade, parentesco,
residência e cronologia não podem entrar em contradição. Todo evento conserva
origem (`manual`, `generated`, `imported`), versão de ficha, prompt/modelo/seed
quando houver geração e o ato de aprovação. Texto gerado é rascunho, não
memória ativa.

Limites iniciais propostos: 3–12 fatos de biografia já existentes; 5–30 eventos
de vida por versão, até 500 caracteres por resumo, no máximo 5 participantes
e 5 vínculos por evento. Esses limites são escolhas de implementação sujeitas
a um PR de contrato e testes de orçamento, não números medidos.

## 5. Criador de personagens

Fluxo em etapas com rascunho recuperável:

1. **Identidade**: nome visível, idioma (pt-BR no primeiro recorte), voz,
   valores, limites, tema, idade fictícia opcional e declaração visível de IA.
2. **Mundo e relações**: continuidade, lugares, pessoas fictícias próximas,
   marcos fixos e assuntos que a personagem não deve afirmar.
3. **Vida**: inserir eventos manualmente ou pedir uma proposta gerada. Mostrar
   linha do tempo, vínculos, inconsistências e origem de cada evento.
4. **Prévia**: conversar em sandbox sem gravar no root canônico; mostrar quais
   eventos entraram no contexto e quais foram citados na resposta.
5. **Aprovação**: confirmar ficha e eventos selecionados; gravar snapshot
   versionado no root, com IDs e contagem. Eventos rejeitados não entram no
   recall. Uma edição posterior cria vN+1, sem reescrever vN.

Primeira entrega pode ser um formulário Qt simples e um backend headless.
Lia v1 permanece como template de partida; **não** migrar automaticamente
relações existentes nem considerar o template aprovado sem ação da pessoa.
Permitir duplicar um template para criar personagem nova, gerando novo
`character_id`; a cópia não herda conversas privadas.

O criador mostra que a vida foi inventada. Evitar uma ficha que se apresente
como pessoa humana real, gere pressão por permanência, exclusividade ou culpa,
ou alegue experiência compartilhada sem turno de origem. Regras de segredo e
limites de tamanho valem para todos os campos, eventos e metadados antes de
qualquer gravação.

## 6. Admissão, recall e revisão

- **Admissão**: validar esquema e coerência; comparar IDs, vínculos e versões;
  verificar segredos; exibir diff; só então publicar eventos aprovados como
  `story` com proveniência `synthetic_life_event`. Operação idempotente para
  `(root, life_version, event_id)` e sem escrita parcial após validação falha.
- **Recall**: buscar no root corrente; limitar cartões de vida sintética com
  orçamento próprio. Rotular “passado ficcional da personagem”, separado de
  “história imaginada em conversa” e “relato da pessoa”. Incluir `event_id`,
  versão e fonte no cartão; devolver somente IDs realmente usados. Não
  atribuir eventos gerados não aprovados à personagem.
- **Revisão**: mudança de evento aprovado cria nova versão; usar supersession
  para substitutos, retirar eventos excluídos e invalidar caches/derivações.
  Preservar história administrativa, mas só versões ativas entram no recall.
- **Exclusão**: mostrar impacto antes de confirmar: evento, derivações e
  possíveis referências em episódios. Não assumir que a exclusão por cadeia
  resolve irmãos semânticos; identificar referências por `event_id` e pedir
  decisão explícita sobre conteúdo relacionado. Testar reload e não
  ressurreição. Apagar o root inteiro continua operação separada.
- **Save-off**: gerar resposta sobre clone temporário; nenhuma proposta,
  cache ou rascunho desse turno pode escrever bytes no root canônico.

Para manter atualizações consistentes entre JSON, tape e índices, preparar
uma transação root-local (staging + validação + commit/recuperação) ou journal
idempotente antes da primeira publicação de vários eventos. `os.replace` de
um JSON isolado não torna a operação de múltiplos arquivos atômica. Testar
falhas simuladas entre eventos, revisão e atualização de `current.json`.

## 7. PRs pequenos e dependências

| PR | Entrega | Prova mínima |
| --- | --- | --- |
| C0 | Contrato dos eventos sintéticos, autoridade ficcional e decisões de exclusão; atualizar F0 | Revisão do contrato, sem código |
| C1 | Schema e validador de ficha estendida, mundo e eventos; templates de exemplo | Rejeição de versões, ciclos, contradições, IDs e segredos |
| C2 | Backend do criador: rascunho, prévia, aprovação e snapshot por root | Idempotência, falha no meio, isolamento e migração Lia sem escrita |
| C3 | Admissão `story` de vida sintética e versionamento/supersession | Sem turno forjado; proveniência e não ressurreição após reload |
| C4 | Recall rotulado, orçamento e resposta ancorada em eventos | `used` real, zero atribuição à pessoa, colisões de IDs entre roots |
| C5 | UI: galeria, formulário, linha do tempo, diff de revisão, exclusão com impacto | Testes de backend e fluxos UI críticos; cópia sem herdar conversas |
| C6 | Avaliação pré-registrada nova e relatório A/B de orçamento igual | Gates abaixo, custos, falhas e execução única registrada |
| C7 | Versão, build e artefato instalável após gates | Smoke do pacote, recurso de templates e abertura do criador |

Cada PR regenera `docs/CONFORMANCE_PROOF.txt` quando adicionar testes e passa
os seis checks exigidos. Nada muda nos caminhos medidos de OpenCode, na janela
admission-shadow-v2, nos defaults do produto ou nas políticas experimentais
por efeito colateral. Não fazer bump de versão antes de C7.

## 8. Avaliação antes de piloto

Pré-registrar fixture, hashes, modelos, prompts, seed, orçamento, rubrica,
divisão dev/holdout, regra de parada e custo. Registrar a demo v1 como linha
histórica reprovada, sem reexecutá-la como confirmação. Casos obrigatórios:

1. Duas personagens com vidas incompatíveis; duas pessoas e duas
   continuidades; IDs de memória deliberadamente iguais em roots distintos.
2. Pergunta sobre passado aprovado, pergunta sem evidência e evento ainda em
   rascunho; nenhum fato inventado ou rascunho tratado como lembrança.
3. Pergunta que mistura vida sintética, história improvisada e relato da
   pessoa; zero atribuição de ficção à vida real da pessoa.
4. Correção, exclusão com irmãos semânticos, recarga do disco e novo recall;
   nenhum conteúdo retirado reaparece.
5. Revisão de voz e linha do tempo, mudança de personagem, save-off e falha
   durante aprovação; isolamento e zero bytes canônicos no save-off.
6. Extração de `story` a partir de conversa, inclusive o caso ausente em v1.
   Separar falha de extração de falha do gate de ficção.

Medir respostas com rubrica de **atribuição**, não só busca de palavras: citar
“irmã” para explicar uma correção ou “astronomia” para negar conhecimento é
diferente de afirmá-los como fatos atuais. Manter também checks literais para
vazamento de texto apagado, com categorias explícitas. A/B compara referência
simples e Memory Machine sob o mesmo orçamento/contexto, sem alegação de
superioridade antes dos resultados. Gates de liberação: zero cruzamento de
roots, zero ficção atribuída à pessoa, zero ressuscitação de evento excluído,
zero rascunho em recall, correção estável e custo dentro do teto registrado.

## 9. Fora do primeiro recorte

Personagens autônomos que escrevem sua vida sem revisão, memórias globais
compartilhadas entre pessoas, transferência automática de experiências entre
personagens, voz/avatares, rede social de personagens e piloto público.
Essas extensões exigem novo contrato de consentimento, proveniência e
retenção.
