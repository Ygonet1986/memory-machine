# Implementação da memória de grafo para conversas

**Branch:** `graph/conversation-agent`  
**PR:** [#92](https://github.com/Ygonet1986/memory-machine/pull/92)  
**Escopo:** o commit inicial dessa funcionalidade, publicado em 25/09/2026.

Este documento descreve o que foi efetivamente alterado. Ele distingue as
partes que já existiam no projeto das ligações novas, e aponta os casos que
ainda precisam de implementação ou verificação.

## 1. Ideia operacional

Há dois caminhos de memória para a mesma conversa:

| Caminho | Onde persiste | Quem escreve | Como recupera |
| --- | --- | --- | --- |
| Fita | `tape.jsonl` | Fluxo normal, turn slots e Companion | Agentes de memória usuais consultam registros e anotam IDs |
| Grafo | `graph/` no root | Extrator de grafo projeta registros salvos | `GraphRecall` percorre entidades/conexões e anota IDs da fita |

O grafo é uma projeção persistente dos registros, não uma segunda cópia
autônoma do texto. Uma aresta traz a origem na fita. Na recuperação, o
coordenador aceita apenas IDs cujo registro na fita ainda esteja ativo. As
anotações dos dois caminhos são reunidas antes de passar pelo orçamento
global do quadro branco.

Uma ligação `related_to` representa associação útil para encontrar uma
lembrança. Ela não certifica que a relação descrita é verdadeira. Isso atende
à decisão de permitir que o grafo se forme enquanto a conversa evolui.

## 2. O que já existia

Antes deste commit, o projeto já possuía `GraphStore` em `graph.py`, a
extração por LLM em `graph_extract.py`, resolução de entidades em
`graph_resolve.py`, travessia em `graph_recall.py` e a junção de evidências
no `Machine.recall()` em `coordinator.py`. Também já existiam turn slots
`question`/`reply`, agentes comuns, quadro branco, limite de orçamento e
consolidação do quadro.

O trabalho novo liga os turnos a essa infraestrutura e altera os valores
padrão de configuração. Não introduz um novo banco, nem um processo em
segundo plano independente. O "agente do grafo" na escrita é a chamada ao
extrator LLM; na leitura, é a travessia `GraphRecall`, determinística, que
entrega anotações com `agent_id="graph"`.

## 3. Defaults e opções (`src/memory_machine/config.py`)

| Campo | Novo default | Efeito |
| --- | --- | --- |
| `graph_enabled` | `true` | Habilita projeção e permite recall por grafo |
| `graph_conversation_enabled` | `true` | Inclui turnos e `entity_definition` na projeção |
| `graph_recall_mode` | `augment_guarded` | Admite evidências do grafo por score e quantidade antes de uni-las às dos agentes comuns |
| `graph_depth` | `2` (já existente) | Permite percorrer uma conexão intermediária, como Lia → jardim → Nina |

`graph_enabled=false` desliga o caminho de grafo. É possível manter o
grafo de registros tradicionais e desativar somente os turnos com
`graph_conversation_enabled=false`. `graph_recall_mode="off"` impede sua
participação na recuperação. Há ainda os modos preexistentes `only` e
`augment`, este último sem o filtro de admissão do modo padrão.

**Atenção às instalações existentes:** `Config.load()` pode carregar campos
já gravados em `config.json`; mudar o default da classe não sobrescreve um
valor explícito antigo. As opções do plugin OpenCode para enviar turn slots
também não foram alteradas neste commit.

## 4. Escrita no chat e nos turn slots (`coordinator.py`)

`Machine._graph_eligible()` passa a considerar os tipos `question`, `reply`,
`memory` e `entity_definition` quando as duas opções do grafo estão ativas.
O tipo `reply` costuma ter `derived_from` apontando para a pergunta; ele é
elegível apesar dessa derivação. Os demais tipos continuam seguindo a
política antiga de `graph_extract_types` e derivação.

Em `Machine.add_turn_slot()`, a fita recebe o turno primeiro. Se o resultado
for válido e não for uma repetição deduplicada, o registro é convertido de
volta em `MemoryRecord` e projetado no grafo. O ID e o texto vêm do registro
que efetivamente foi gravado, não de uma fala presumida. O plugin OpenCode
ainda precisa enviar turn slots (`MEMORY_MACHINE_TURN_SLOTS=1`); o novo
default do grafo sozinho não liga essa captura no plugin.

Ao final de `Machine.run()`, o chat principal já gravava um registro `memory`
com a pergunta no `summary` e a resposta no `why`. Agora esse registro é
projetado após sua gravação, se não for duplicado. Registros tradicionais
aprovados continuam passando pelo fluxo de extração que já existia.

`Machine._graph_after_appends()` aplica a extração depois do append na fita.
Uma falha da projeção não desfaz o registro original; a infraestrutura do
grafo gerencia tentativas pendentes e falhas. A projeção usa o root da
instância de `Machine`, mantendo os roots separados.

### Definição explícita de entidade

O tipo `entity_definition` é aceito pela elegibilidade do grafo. Seu contrato
com o extrator é `summary` = nome da entidade e `why` = descrição. Por
exemplo, um registro `entity_definition` chamado "Lia" cuja descrição
mencione "jardim" pode formar Lia → jardim. **Este commit não criou um
comando de CLI nem uma tela para cadastrar ou revisar esse tipo.** Essa
integração ainda terá de ser feita pela interface que for escolhida.

## 5. Extração de associações (`graph_extract.py`)

`GRAPH_CONVERSATION_PROMPT` foi adicionado para os quatro tipos de conversa
acima. Ele pede ao LLM um JSON de entidades, eventos, relações e menções
compatível com o parser e o `GraphStore` preexistentes. O extrator pode
registrar `related_to` quando entidades são discutidas juntas, mesmo sem
uma afirmação factual explícita. Cada item pode incluir confiança entre 0 e
1. O prompt proíbe entidades e associações ausentes daquele turno.

Exemplo conceitual:

1. Turno A: "Lia cuida do jardim" → Lia → jardim, com origem A.
2. Turno B: "Nina desenhou o jardim" → Nina → jardim, com origem B.
3. Pergunta "Lia" → o recall pode atravessar o jardim e sugerir B.

No `extract()` individual, a seleção do prompt depende do tipo do registro.
**Limite importante:** `extract_batch()` ainda usa `GRAPH_BATCH_PROMPT`, o
prompt genérico anterior, mesmo quando o lote contém turnos de conversa.
Assim, os dois slots do Companion projetados em lote ainda não recebem a
mesma instrução associativa do fluxo individual. É uma correção necessária
antes de declarar equivalência entre todas as portas de entrada.

## 6. Companion (`companion_engine.py`)

`CompanionEngine._commit()` já persistia slots de pergunta e resposta no
root do Companion. Agora, depois de salvar esses slots, lê a configuração
daquele root e, se as duas opções do grafo estiverem ativas, entrega os
slots novos a `Machine._graph_after_appends()` com o mesmo cliente LLM.
Slots falhos ou deduplicados ficam fora do lote.

Esse código roda apenas no `_commit()` de uma interação salva. O caminho
`save=False` do Companion usa o fluxo temporário preexistente e não grava
turnos nem grafo no root real. A implementação desta PR não adicionou um
teste específico de byte equality para o grafo do Companion.

## 7. Recuperação e quadro branco (`coordinator.py`)

No modo padrão `augment_guarded`, `Machine.recall()` executa os agentes tradicionais
e também `GraphRecall`. Este último identifica entidades na pergunta,
percorre caminhos até a profundidade configurada e devolve IDs de registros
ligados às entidades. `Machine._graph_annotations()` descarta IDs sem
registro ativo na fita e cria `Annotation(agent_id="graph", memory_id=...)`.
No modo padrão, o guard preexistente limita as evidências por score
(`graph_augment_min_score`, default 0,80) e quantidade
(`graph_augment_max_items`, default 3), antes da junção.
`_union_with_graph()` combina as duas listas por ID; quando ambas sugerem
o mesmo registro, preserva uma anotação com a maior relevância.

`merge_annotations()` aplica o orçamento `whiteboard_budget` ao conjunto
combinado e atualiza o quadro branco. O payload e a reidratação usam os
registros da fita. O resultado do recall expõe `graph_evidence`,
`graph_metrics` e `graph_mode`, permitindo examinar o caminho usado.

Se o tamanho serializado do quadro exceder `consolidate_threshold`, o fluxo
preexistente chama `consolidate_whiteboard()` após unir as anotações. A
consolidação reduz o quadro; não significa apagar o `tape.jsonl` ou o grafo.

**Limite importante:** no modo `whiteboard_mode="dimension"`, o código atual
usa `_merge_by_dimension(run)` em vez de `raw_annotations`, portanto essa
ramificação não inclui as anotações do grafo no quadro da mesma maneira que
o modo padrão `single`. O comportamento para quadros por dimensão precisa
ser corrigido e testado separadamente.

## 8. Testes e revisão

Foi criado `tests/test_graph_conversation.py` com três verificações:

1. Dois turnos compartilham "jardim"; o grafo persiste três entidades e
   duas relações; a pergunta por Lia encontra o registro de Nina em dois
   saltos; repetir o mesmo ID de turno não duplica relações; recarregar o
   `GraphStore` conserva as relações.
2. Desabilitar explicitamente `graph_conversation_enabled` impede chamadas
   ao extrator e não cria a projeção para um turn slot.
3. Com `Config()` padrão, o ID encontrado pelo grafo aparece em
   `graph_evidence`, nas anotações de resposta e no quadro branco com
   `agent_id="graph"`.

Testes antigos que verificam exclusivamente roteamento/agentes sem grafo
passaram a definir `graph_enabled=False` explicitamente. O teste de
configuração foi atualizado para os novos defaults. Na verificação local do
commit inicial: `python -m pytest -q` → **743 passed, 4 skipped**;
`python -m ruff check src/memory_machine tests/test_graph_conversation.py`
→ **sem erros**. Não há aqui uma avaliação de qualidade semântica das
relações produzidas por um modelo real: os testes usam `FakeClient`.

## 9. Trabalho pendente, sem afirmar que já foi feito

- Garantir que correções, supersede e exclusões na fita retirem ou refaçam
  conexões antigas no grafo; testar que nada removido volta no recall.
- Dar ao lote de conversas o mesmo contrato associativo do prompt individual.
- Integrar as anotações do grafo ao quadro em modo `dimension`.
- Oferecer criação e revisão de `entity_definition` na CLI/UI e testes de
  correção de descrições ao longo da conversa.
- Integrar a captura de turn slots do OpenCode quando o produto desejar
  registrar automaticamente suas conversas; sua chave própria continua
  desligada por padrão.
- Medir custo de chamadas, qualidade de conexões e efeito da mudança de
  defaults sobre a janela de avaliação existente antes de fazer alegações
  comparativas.

O branch contém a implementação descrita acima; o PR está aberto para
revisão. O merge em `main` é uma etapa separada.
