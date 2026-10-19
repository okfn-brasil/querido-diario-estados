# 0009. Fila de extração com Celery e Redis dedicado
Data: 18/10/2026
Status: Proposto

## Contexto e Declaração do Problema
Hoje o `querido-diario-data-processing` roda como um CronJob `data-processing` que, de hora em hora, busca no Postgres os diários com `processed = false` e os processa em série: baixa o arquivo, extrai o texto no Apache Tika, indexa no OpenSearch e marca a linha como processada. Um diário grande segura todos os outros, um erro no meio da execução só é retomado na hora seguinte e a capacidade de processamento é fixa, haja um diário pendente ou milhares, como numa coleta histórica do diário estadual do Espírito Santo (ADR-0008).

A arquitetura proposta no TCC troca esse laço por uma fila de extração: um produtor enfileira um item por diário pendente e workers consomem a fila, escalados pelo KEDA de 0 até um teto conforme o tamanho da fila. Para isso, é preciso escolher a biblioteca de fila que os workers vão usar no data-processing e o broker que guarda as mensagens no cluster.

Dois fatos do ecossistema pesam na escolha:

- O `querido-diario-backend` já usa Celery (`celery==5.2.7`, tasks em `alerts/tasks.py`), e o `querido-diario-deployment` já implanta os Deployments `celery-worker` e `celery-beat`, com `CELERY_BROKER_URL` e `CELERY_RESULT_BACKEND` apontando para `redis://redis:6378`.
- Esse Redis (`k8s/base/redis/deployment.yaml`) roda com `--maxmemory 200mb --maxmemory-policy allkeys-lru` e sem AOF. Com a memória cheia, ele descarta qualquer chave, inclusive as listas que guardam as mensagens da fila, sem erro para quem enfileirou. Uma coleta histórica enfileira dezenas de milhares de diários de uma vez.

## Fatores Determinantes da Decisão
- Nenhum diário pode ser perdido: se o worker morrer no meio do processamento, a mensagem precisa voltar para a fila (entrega *at-least-once*)
- Tamanho da fila legível pelo KEDA, para escalar os workers de 0 até o teto
- Ferramenta já conhecida pela comunidade e pelos mantenedores do Querido Diário
- Poucos componentes novos para operar no cluster
- Pouco consumo de recursos no cluster kind local, que roda num notebook
- Isolamento em relação ao que já roda (o Celery do backend), para não afetar o produto
- Esforço de implementação dentro do prazo do TCC

## Alternativas Consideradas

**Biblioteca de fila**
- A1: Celery
- A2: RQ (Redis Queue)
- A3: Fila própria sobre listas do Redis (`LPUSH`/`BRPOP`), sem biblioteca

**Broker**
- B1: Redis existente (`redis:6378`), o mesmo do backend
- B2: Redis dedicado à fila (`redis-queue`), com `noeviction` e AOF
- B3: RabbitMQ

## Alternativa Escolhida

**Biblioteca: A1.** Celery, no pacote `work_queue/` do data-processing (o nome `queue/` colidiria com o módulo `queue` da biblioteca padrão), com:

```python
app.conf.update(
    task_default_queue="extraction",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_ignore_result=True,
    broker_transport_options={"visibility_timeout": 2 * 3600},
)
```

Justificativa: o Celery é o que a comunidade já usa no backend e o que os manifests do deployment já sabem implantar, então quem mantém o Querido Diário não precisa aprender uma ferramenta nova para entender os workers. Ele também já resolve o que a fila exige. Com `task_acks_late`, a mensagem só é confirmada depois que a task termina, e com `task_reject_on_worker_lost` ela volta para a fila se o processo do worker morrer. Com `worker_prefetch_multiplier=1`, cada worker reserva só uma mensagem por vez, então o tamanho da lista `extraction` no Redis corresponde aos diários que ainda não começaram a ser processados, que é o número que o KEDA usa para escalar. Retentativas com espera e o sinal `task_failure`, usado para mandar à DLQ o diário que esgotou as tentativas, também vêm prontos. Sem `task_ignore_result`, cada task gravaria um resultado que ninguém lê.

O RQ (A2) é mais simples, mas não tem equivalente ao `acks_late`: um job cujo worker morre vai para o registro de jobs falhos e não volta sozinho para a fila. Além disso, ninguém no ecossistema o usa. A fila própria (A3) obrigaria a reescrever confirmação, retentativa e devolução de mensagens de workers mortos, que é justamente a parte difícil de acertar.

Como o Celery entrega cada mensagem pelo menos uma vez, a mesma task pode rodar duas vezes para o mesmo diário. A task é idempotente: retorna sem chamar o Tika se o diário já está com `processed = true`, e o documento no OpenSearch usa o `file_checksum` do diário (ou do segmento) como chave, então uma segunda indexação sobrescreve a primeira em vez de duplicar. O produtor, por sua vez, só enfileira um diário se conseguir `SET qd:enqueued:{id} 1 NX EX 21600`, o que impede enfileirar de novo, a cada execução do CronJob de enfileiramento, um diário que ainda está na fila.

**Broker: B2.** Um Redis só para a fila, o `redis-queue` (`redis:7`, porta 6379), com `--appendonly yes --maxmemory 512mb --maxmemory-policy noeviction` e um PVC de 1 Gi, no componente Kustomize da fila (overlay `dev-queue`). Um sidecar `redis_exporter` expõe o tamanho das listas `extraction` e `qd:extraction:dead` ao Prometheus (ADR-0011).

Justificativa: o Redis existente (B1) não serve para guardar a fila. Com `allkeys-lru`, quando a memória chega a 200 MB, ele descarta chaves para abrir espaço, e as mensagens da fila sumiriam sem que o produtor ou os workers percebessem: exatamente a perda que a fila existe para evitar. Mudar a política desse Redis para `noeviction` e ligar o AOF também não é uma boa saída: ele é o broker e o result backend do Celery do backend, e com `noeviction` uma coleta histórica que enchesse a memória faria o Redis recusar também as escritas do backend, derrubando os alertas junto com a fila. Seria mexer na infraestrutura do produto para atender um experimento do TCC. Com `noeviction`, o `redis-queue` recusa novas mensagens quando a memória acaba, e o produtor recebe o erro em vez de perder dados em silêncio. Com AOF, as mensagens sobrevivem a um reinício do pod. Separar o Redis também evita que uma coleta histórica dispute memória com o backend, e permite subir e derrubar a fila inteira no experimento sem tocar no que já roda.

O RabbitMQ (B3) seria o broker mais robusto para o Celery: confirmação de mensagens nativa, sem depender de `visibility_timeout`. Mas é mais um componente para operar, que ninguém no ecossistema usa, consome mais memória em repouso que um Redis, e o KEDA teria de usar outro scaler (`rabbitmq`, pela API de gerenciamento) em vez do `redis`, que lê diretamente o tamanho da lista. Para o volume do TCC, um Redis bem configurado basta.

**Limitação conhecida.** No transporte Redis do Celery, uma mensagem reservada e não confirmada fica guardada à parte e só volta para a fila depois do `visibility_timeout`, se o worker morrer sem conseguir devolvê-la (por exemplo, com `SIGKILL` ou um nó que cai). O timeout precisa ser maior que o tempo do diário mais demorado, senão a mensagem é entregue a outro worker enquanto o primeiro ainda processa. Com 2 h, um diário de um worker morto dessa forma pode levar até 2 h para ser reprocessado. Num `kubectl delete pod`, o worker recebe `SIGTERM` e tem o `terminationGracePeriodSeconds` para terminar a task ou devolver a mensagem. Isso precisa ser considerado no cenário de robustez R1 do experimento, em que o valor do timeout pode ser reduzido para a duração do teste.

## Prós e Contras das Alternativas

| Alternativa | Prós | Contras |
| -------- | -------- | -------- |
| A1 — Celery (escolhida) | Já usado no backend e implantado pelo deployment; `acks_late`, devolução de mensagens de workers mortos, retentativas e sinais de falha prontos; lista no Redis legível pelo KEDA | Mais configuração que o RQ; no Redis depende de `visibility_timeout` para recuperar mensagens de workers mortos |
| A2 — RQ | API simples; só depende do Redis | Sem `acks_late`: job de worker morto vai para os falhos e não volta à fila; ninguém no ecossistema usa |
| A3 — Fila própria sobre o Redis | Nenhuma dependência nova; controle total | Reescrever confirmação, retentativa, DLQ e recuperação de workers mortos; mais código para testar e manter |
| B1 — Redis existente | Nenhum componente novo | `allkeys-lru` descarta mensagens quando a memória enche; sem AOF; disputa memória com o Celery do backend; mudar a política afetaria o produto |
| B2 — Redis dedicado (escolhida) | `noeviction` e AOF sem afetar o backend; isolado do produto; sobe e desce com o overlay da fila; scaler `redis` do KEDA | Mais um Deployment e um PVC no cluster |
| B3 — RabbitMQ | Confirmação de mensagens nativa, sem `visibility_timeout` | Componente novo que ninguém no ecossistema opera; mais memória em repouso; scaler do KEDA pela API de gerenciamento |
