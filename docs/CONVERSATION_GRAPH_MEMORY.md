# Duas memórias, um quadro branco

A fita (`tape.jsonl`) guarda os turnos e os registros duráveis. Os agentes de
memória existentes consultam a fita e propõem anotações para o quadro branco.
O grafo persistente (`graph/`) guarda entidades e conexões extraídas desses
mesmos registros. Ele não substitui a fita: cada conexão aponta para o ID do
registro de origem, e o texto recuperado continua vindo da fita.

## Escrita

Com `graph_enabled=true` e `graph_conversation_enabled=true` (ambos são os
defaults), um turno salvo (`question` ou `reply`) é enviado ao extrator do
grafo depois de entrar na fita. O turno do chat principal (`memory`) também é
processado. O agente extrai entidades e associações `related_to` mesmo quando
a conversa não declara uma relação factual. Descrições explícitas podem ser
gravadas como registros `entity_definition`: `summary` contém o nome e `why`
contém a descrição. A projeção vincula o ID da memória à entidade e às
conexões. Falhas de extração não desfazem a gravação da fita; seguem a fila de
tentativas da projeção. Turnos deduplicados não são reprocessados.

## Leitura

Na recuperação, os agentes usuais examinam a fita. O agente do grafo parte
das entidades encontradas na pergunta, percorre até `graph_depth` conexões
(default: 2) e propõe anotações `agent_id="graph"` com os IDs de origem. Em
`graph_recall_mode="augment"` (default), as duas listas são combinadas por
ID e passam juntas pelo orçamento do quadro branco. Apenas registros ativos
da fita podem entrar nas anotações e no payload; a resposta é fundamentada
nos registros recuperados, não nas arestas tomadas isoladamente.
Se o quadro branco ultrapassar `consolidate_threshold`, o fluxo de recall
consolida seu conteúdo após a combinação das anotações. A consolidação
resume o quadro branco; não apaga os registros da fita nem o grafo persistente.

Assim, uma fala sobre Lia e jardim e outra sobre Nina e jardim podem ligar
Lia → jardim → Nina. Uma pergunta sobre Lia pode recuperar a segunda fala
mesmo sem repetir as palavras dela. Essas ligações são pistas de navegação,
não declarações de veracidade. A revisão e a remoção dos vínculos antigos
exigem sincronizar a projeção do grafo com a fita; isso deve ser validado
antes de usar correções de entidades no produto.

Para desligar, configure `graph_enabled=false`. Para manter o grafo dos
registros tradicionais sem extrair conversas, use
`graph_conversation_enabled=false`. O plugin OpenCode ainda requer que a
gravação dos turn slots esteja habilitada para disponibilizar o texto bruto
dos turnos ao extrator; o chat interno já grava seus turnos na fita.
