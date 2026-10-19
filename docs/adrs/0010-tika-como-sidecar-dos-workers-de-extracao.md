# 0010. Apache Tika como sidecar dos workers de extração
Data: 18/10/2026
Status: Proposto

## Contexto e Declaração do Problema
Hoje o Apache Tika, que extrai o texto dos PDFs dos diários, roda no `querido-diario-deployment` como um Deployment `apache-tika` com uma réplica (`k8s/base/apache-tika/deployment.yaml`), atrás do Service `apache-tika:9998`. Ele pede 1200 Mi de memória, com limite de 2500 Mi e `-Xmx1400m` no `JAVA_TOOL_OPTIONS`; no overlay `dev`, os valores caem para 512 Mi e 1500 Mi. O CronJob `data-processing` chama esse Tika pelo `APACHE_TIKA_SERVER` (`http://apache-tika:9998`), um diário por vez, então uma réplica basta.

A ADR-0009 troca esse CronJob por uma fila de extração com workers Celery escalados pelo KEDA de 0 até um teto. Com `--concurrency=1` e `worker_prefetch_multiplier=1`, cada worker processa um diário por vez, e o número de réplicas passa a ser o paralelismo do pipeline. Falta decidir como esses workers acessam o Tika: se todos chamam um Tika compartilhado ou se cada worker tem o seu.

O que pesa na escolha é onde fica o custo do processamento. O worker baixa o arquivo, espera a resposta do Tika e envia o texto ao OpenSearch: quase todo o tempo e quase toda a memória de um diário estão na extração, feita pela JVM do Tika. A vazão de um pipeline é a do seu estágio mais lento. Se os workers escalam e o Tika não, a fila só muda de lugar: sai da lista `extraction` do Redis, que o KEDA enxerga, e vira requisições esperando dentro do Tika, que ele não enxerga.

## Fatores Determinantes da Decisão
- Vazão de extração crescendo com o número de workers, que é a hipótese dos experimentos de elasticidade
- Nenhum ponto único de falha na extração
- Escala até zero sem recursos parados: sem diários na fila, nada de processamento reservado no cluster (cenário E2)
- Um único mecanismo de escala para operar e calibrar
- Consumo de memória no cluster kind local, que roda num notebook
- Tempo até o primeiro diário processado depois de um scale-up a partir de zero
- Esforço de implementação dentro do prazo do TCC

## Alternativas Consideradas
- Opção 1: Tika como sidecar, um container Tika em cada pod de worker, acessado por `localhost:9998`
- Opção 2: Deployment compartilhado com réplicas fixas, o `apache-tika` atual com `replicas` maior
- Opção 3: Deployment compartilhado com escala própria, o `apache-tika` com um segundo ScaledObject do KEDA (ou HPA por CPU)

## Alternativa Escolhida
Opção escolhida: **Opção 1**, Tika como sidecar do `extraction-worker`.

O pod do `extraction-worker` (componente Kustomize da fila, overlay `dev-queue`) passa a ter dois containers: o worker Celery e o Tika, com a mesma imagem `ghcr.io/okfn-brasil/querido-diario-data-processing/apache-tika` e os mesmos recursos e `JAVA_TOOL_OPTIONS` do Deployment atual. O Tika escuta em `127.0.0.1`, e o worker recebe `APACHE_TIKA_SERVER=http://localhost:9998`. O Tika é declarado como *native sidecar*: um `initContainer` com `restartPolicy: Always` e `startupProbe` em `/version`. O cluster kind usa `kindest/node:v1.31.2`, em que esse recurso já vem habilitado. O Deployment `apache-tika` compartilhado continua no overlay `dev`, que é o baseline do experimento.

Justificativa: com o sidecar, cada worker que o KEDA sobe traz a sua própria capacidade de extração, então a vazão cresce na proporção das réplicas e o paralelismo medido nos experimentos é o paralelismo real da extração. Como cada worker processa um diário por vez, cada Tika atende uma requisição por vez: não há disputa pelo heap nem pausas de GC causadas pelo diário de outro worker, e a latência de extração de um pod depende só do que ele está processando. É isso que permite atribuir as métricas de duração da ADR-0011 a cada diário.

O sidecar também tira o ponto único de falha. Um PDF que estoure a memória da JVM derruba o Tika de um pod, e não as extrações em andamento de todos os workers. O diário afetado volta para a fila pelo `task_acks_late` e pelo `task_reject_on_worker_lost` da ADR-0009 e é processado por outro worker.

A escala fica a cargo de um único ScaledObject. Com a fila vazia, o KEDA leva o `extraction-worker` a zero e nenhuma JVM fica ocupando memória à toa, que é o comportamento medido no cenário E2. Um Tika compartilhado não acompanha os workers sozinho: ou fica sempre ligado (Opção 2), ou precisa de um segundo laço de escala (Opção 3).

A Opção 2 é a que mais economiza memória. Uma JVM atende vários workers e as requisições se intercalam, e o Tika já está aquecido quando o primeiro worker chega. Mas o número de réplicas do Tika passa a ser um teto fixo da vazão, abaixo do qual escalar os workers não muda nada, e as réplicas ficam reservadas mesmo sem diários na fila. Com uma réplica, que é a configuração do baseline, a proposta herdaria o gargalo do baseline e o experimento não separaria o efeito da fila do efeito do Tika. Por isso ela fica como plano B no plano de implementação, com `replicas: 3`, e não como arquitetura proposta.

A Opção 3 corrige o teto, mas com dois laços de escala que reagem a sinais diferentes e em tempos diferentes: o KEDA dos workers lê o tamanho da fila, enquanto o do Tika leria CPU ou requisições em andamento. Cada laço teria que ser calibrado, assim como a proporção entre workers e Tikas, e o Service ainda distribuiria as requisições sem saber quanto cada réplica está processando. É uma complexidade que o sidecar evita por construção.

**Consequências negativas.** Cada pod de worker reserva a memória de um Tika (1200 Mi de *request* na base, 512 Mi no `dev`), além da memória do worker. Com N réplicas, são N JVMs, e isso limita o `maxReplicaCount` no kind; o teto será calibrado no D5. Cada scale-up paga de 20 a 30 s de inicialização da JVM antes do primeiro diário. O native sidecar faz o worker só começar depois de a `startupProbe` do Tika passar, e só desliga o Tika depois de o worker sair. Assim, no `SIGTERM`, o Tika continua disponível durante o `terminationGracePeriodSeconds` para o worker terminar o diário atual. Mesmo assim, as retentativas com espera exponencial de `ApacheTikaTextExtractor` continuam cobrindo uma reinicialização do Tika no meio de uma task. O tempo de inicialização entra na medição de elasticidade e precisa ser reportado nos resultados.

## Prós e Contras das Alternativas

| Alternativa | Prós | Contras |
| -------- | -------- | -------- |
| Opção 1 — Sidecar (escolhida) | Vazão de extração escala com os workers; sem ponto único de falha; um único ScaledObject; escala a zero libera o Tika junto; latência por diário sem interferência de outros workers | Uma JVM por pod (≈ 1,2 GiB na base); 20 a 30 s de *cold start* a cada scale-up; Tika ocioso durante o download e a indexação do próprio worker |
| Opção 2 — Compartilhado com réplicas fixas | Menos memória, uma JVM atende vários workers; Tika já aquecido; nenhum manifest novo para o Tika | Réplicas do Tika são um teto fixo de vazão; com 1 réplica repete o gargalo do baseline; réplicas reservadas mesmo com a fila vazia; falha de uma réplica afeta vários workers |
| Opção 3 — Compartilhado com escala própria | Menos memória que o sidecar; vazão do Tika pode acompanhar a demanda | Dois laços de escala com sinais diferentes para calibrar; proporção workers/Tikas a ajustar; Service distribui sem saber a carga de cada réplica; também paga *cold start* ao escalar |
