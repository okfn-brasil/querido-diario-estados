# Arquitetura do processamento: atual × proposta implementada

Este documento compara o processamento dos diários (extração do texto, indexação e excertos temáticos) na arquitetura atual, que é o baseline do experimento, e na arquitetura proposta, como foi implementada na Parte C. A coleta (raspadores, Scrapy Cloud e armazenamento dos PDFs) é a mesma nas duas e está em [arquitetura-legada-da-coleta-dos-diários.md](arquitetura-legada-da-coleta-dos-diários.md).

As duas arquiteturas convivem no `querido-diario-deployment` e se alternam pelo overlay:

| | Atual (baseline) | Proposta implementada |
|---|---|---|
| Overlay no kind | `k8s/overlays/dev` | `k8s/overlays/dev-queue` (`dev` + componente `queue-pipeline`) |
| Comando | `make k8s-local-queue-down` | `make k8s-local-queue` |
| Código | `querido-diario-data-processing`, pipeline `gazette_texts` | mesmo repositório, pacote `work_queue/` e pipelines `enqueue_extraction` e `themes_from_queue` |

## Arquitetura atual (baseline)

Um CronJob roda de hora em hora e processa, em sequência, todos os diários ainda não processados. O Tika é um Deployment compartilhado, sempre ligado. As métricas saem num push ao Pushgateway no fim de cada execução.

```mermaid
flowchart LR
    subgraph coleta["Coleta (igual nas duas arquiteturas)"]
        Spider["Raspadores<br/>(querido-diario)"]
    end

    subgraph qd["namespace querido-diario"]
        Cron["CronJob data-processing<br/>de hora em hora<br/>pipeline gazette_texts<br/>(mode=cron)"]
        Tika["Deployment apache-tika<br/>(compartilhado, 1 réplica,<br/>sempre ligado)"]
        PG[("Postgres<br/>gazettes")]
        S3[("Storage S3<br/>PDFs e .txt")]
        OS[("OpenSearch<br/>queridodiario<br/>educacao / ambiental")]
        API["API"]
    end

    subgraph mon["namespace monitoring"]
        PGW["Pushgateway"]
        Prom["Prometheus"]
        Graf["Grafana<br/>dashboard qd-pipeline"]
    end

    Spider -->|PDF| S3
    Spider -->|metadados<br/>processed=false| PG

    Cron -->|1 · diários não processados| PG
    Cron -->|2 · baixa o PDF| S3
    Cron -->|3 · extrai o texto<br/>um diário por vez| Tika
    Cron -->|4 · grava o .txt| S3
    Cron -->|5 · indexa| OS
    Cron -->|6 · processed=true| PG
    Cron -->|7 · excertos temáticos<br/>BERT, no mesmo Job| OS
    Cron -->|8 · push no fim da execução| PGW

    PGW --> Prom
    Prom --> Graf
    OS --> API
```

- **Latência:** um diário coletado espera até a próxima execução do CronJob, até 1 hora, antes de ser processado.
- **Paralelismo:** nenhum. Um Job processa um diário por vez, e o Tika compartilhado é o gargalo.
- **Custo em repouso:** o Tika compartilhado fica ligado mesmo sem trabalho.
- **Falhas:** um diário com erro é registrado no log e pulado. Ele continua `processed=false` e é tentado de novo na execução seguinte.

## Arquitetura proposta implementada

Um produtor enfileira o id de cada diário não processado num Redis dedicado. Workers, cada um com o próprio Tika, processam um diário por vez, e o KEDA escala os workers pelo tamanho da fila, de 0 até o teto. Os excertos temáticos rodam à parte, em lotes. As métricas dos workers e da fila são raspadas pelo Prometheus.

```mermaid
flowchart LR
    subgraph coleta["Coleta (igual nas duas arquiteturas)"]
        Spider["Raspadores<br/>(querido-diario)"]
    end

    subgraph qd["namespace querido-diario"]
        Enq["CronJob enqueue-extraction<br/>a cada 5 min"]

        subgraph rq["Deployment redis-queue (ADR-0009)"]
            Redis[("Redis dedicado<br/>noeviction + AOF + PVC<br/>────────<br/>extraction: fila do Celery<br/>qd:extraction:dead: DLQ<br/>qd:enqueued:{id}<br/>qd:themes:pending")]
            Exp["redis_exporter<br/>(sidecar, :9121)"]
        end

        SO["ScaledObject (KEDA)<br/>1 réplica a cada<br/>5 mensagens, 0 a N"]

        subgraph wk["Deployment extraction-worker (0 a N réplicas)"]
            direction TB
            subgraph pod["cada pod (ADR-0010)"]
                W["worker Celery<br/>--concurrency=1<br/>(mode=queue, :9100)"]
                TS["Tika sidecar<br/>localhost:9998"]
            end
        end

        Themes["CronJob themes-from-queue<br/>de hora em hora<br/>BERT em lotes"]

        PG[("Postgres<br/>gazettes")]
        S3[("Storage S3<br/>PDFs e .txt")]
        OS[("OpenSearch<br/>queridodiario<br/>educacao / ambiental")]
        API["API"]

        Off["Desligados no modo fila:<br/>CronJob data-processing (suspenso)<br/>apache-tika compartilhado (0 réplicas)"]
    end

    subgraph mon["namespace monitoring"]
        Prom["Prometheus<br/>(PodMonitors)"]
        KSM["kube-state-metrics<br/>(réplicas)"]
        Graf["Grafana<br/>dashboard qd-pipeline"]
    end

    Spider -->|PDF| S3
    Spider -->|metadados<br/>processed=false| PG

    Enq -->|1 · diários não processados| PG
    Enq -->|2 · SET qd:enqueued NX<br/>e enfileira o gazette_id| Redis

    SO -.->|lê o tamanho de extraction| Redis
    SO -.->|escala| wk

    Redis -->|3 · uma mensagem por vez<br/>acks_late| W
    W -->|4 · lê o diário pelo id| PG
    W -->|5 · baixa o PDF| S3
    W -->|6 · extrai o texto| TS
    W -->|7 · grava o .txt| S3
    W -->|8 · indexa| OS
    W -->|9 · processed=true| PG
    W -->|10 · SADD qd:themes:pending<br/>ou DLQ se falhar de vez| Redis

    Themes -->|11 · lê o lote sem remover| Redis
    Themes -->|12 · excertos temáticos| OS
    Themes -->|13 · SREM do lote processado| Redis

    W -.->|/metrics| Prom
    Exp -.->|redis_key_size| Prom
    KSM -.-> Prom
    Prom --> Graf
    OS --> API

    classDef off fill:#eeeeee,stroke:#999999,stroke-dasharray: 4 3,color:#555555;
    class Off off;
```

- **Latência:** o produtor roda a cada 5 minutos, e os workers começam assim que a fila tem mensagens.
- **Paralelismo:** réplicas = diários em paralelo (`--concurrency=1`). O teto é 6 no componente e 2 no overlay `dev-queue`, para caber no Docker de um notebook. A calibração fica para a D5.
- **Custo em repouso:** com a fila vazia, o KEDA leva os workers a 0, e com eles os Tikas. Só o `redis-queue` fica ligado.
- **Falhas:**
  - **Erro transitório** (rede, Tika reiniciando, Postgres fora do ar): até 5 novas tentativas com backoff. A conexão com o Postgres é refeita a cada tentativa.
  - **Erro definitivo** (arquivo sem suporte, PDF ausente no storage): o diário vai direto para a DLQ (`qd:extraction:dead`).
  - **Worker morto no meio de um diário:** a mensagem volta para a fila (`acks_late` + `task_reject_on_worker_lost`).
  - **Diário reprocessado:** não duplica, porque o índice sobrescreve o documento pelo checksum.
- **Temas:** o lote só sai de `qd:themes:pending` depois de passar por todos os temas. Se o Job morrer no meio, por exemplo por falta de memória no BERT, o lote é processado de novo na execução seguinte.

## Métricas (ADR-0011)

As duas arquiteturas emitem as mesmas séries (`qd_gazettes_processed_total`, `qd_gazette_processing_seconds` e `qd_scrape_to_index_seconds`), diferenciadas pelo rótulo `mode`. Só o caminho até o Prometheus muda:

| | Baseline (`mode=cron`) | Fila (`mode=queue`) |
|---|---|---|
| Processamento | push ao Pushgateway no fim do Job | `/metrics` do worker (porta 9100), raspado pelo PodMonitor `extraction-worker` |
| Fila e DLQ | — | `redis_exporter` (porta 9121), raspado pelo PodMonitor `redis-queue` |
| Réplicas | — | `kube_deployment_status_replicas` (kube-state-metrics) |
| CronJobs da fila | — | rodam com `PUSHGATEWAY_URL=""`, para não substituir o grupo `job="data-processing"` do baseline no Pushgateway |

## Onde está cada peça

| Peça | Repositório | Arquivo |
|---|---|---|
| App Celery e broker | `querido-diario-data-processing` | `work_queue/celery_app.py` |
| Task `extract_gazette`, retries e DLQ | `querido-diario-data-processing` | `work_queue/tasks.py` |
| Chaves do Redis | `querido-diario-data-processing` | `work_queue/redis_keys.py` |
| Pipelines `enqueue_extraction` e `themes_from_queue` | `querido-diario-data-processing` | `main/__main__.py` |
| Redis dedicado e exporter | `querido-diario-deployment` | `k8s/components/queue-pipeline/redis-queue.yaml` |
| Worker com Tika sidecar | `querido-diario-deployment` | `k8s/components/queue-pipeline/extraction-worker.yaml` |
| CronJobs da fila | `querido-diario-deployment` | `k8s/components/queue-pipeline/enqueue-cronjob.yaml` e `themes-cronjob.yaml` |
| KEDA | `querido-diario-deployment` | `k8s/components/queue-pipeline/scaledobject.yaml` |
| PodMonitors | `querido-diario-deployment` | `k8s/components/queue-pipeline/monitoring/` |
| Overlay e limites locais | `querido-diario-deployment` | `k8s/overlays/dev-queue/kustomization.yaml` |

Decisões: [ADR-0009](../adrs/0009-fila-de-extracao-com-celery-e-redis-dedicado.md) (broker e fila), [ADR-0010](../adrs/0010-tika-como-sidecar-dos-workers-de-extracao.md) (Tika sidecar) e [ADR-0011](../adrs/0011-observabilidade-com-prometheus-e-grafana.md) (observabilidade). Validação funcional dos dois modos em [validacao-funcional.md](../validacao-funcional.md).
