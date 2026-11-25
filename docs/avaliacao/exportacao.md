# Exportação dos resultados (D4)

O `simulador/export_metrics.py` (issue #30) guarda, ao fim de **cada** execução, tudo o que a análise (E-3) vai ler: as séries do Prometheus entre t0 e o fim, um resumo da execução inteira, as contagens finais do Postgres e o conteúdo da DLQ. A análise lê só esses arquivos, nunca o Prometheus ([protocolo](protocolo.md#análise)). Rodar ao fim de cada execução é obrigatório no Revoada, cujo Prometheus guarda só 1 dia.

## Uso

No kind, com os port-forwards abertos pelo próprio script:

```bash
# durante a execução (necessário no modo A): contagem do Postgres a cada 15 s
python simulador/export_metrics.py --acompanhar --cenario E1 --modo A --run E1-A-1 --port-forward &

# no fim (t_vazio; no modo C, t_zero)
kill %1
python simulador/export_metrics.py --start <t0> --end <t_fim> \
    --cenario E1 --modo A --run E1-A-1 --port-forward
```

`--start` e `--end` aceitam timestamp Unix (`date +%s`) ou ISO 8601; sem fuso, vale o horário local. Com `--invalida`, os arquivos vão para `resultados/<campanha>/<cenario>/<modo>/invalidas/`. Com `uv run simulador/export_metrics.py ...`, as dependências (`psycopg2-binary`, `redis` e `requests`) se instalam sozinhas.

| Opção | Padrão | Observação |
|---|---|---|
| `--step` | 15 | passo do `query_range` em segundos; **30 na campanha R** (o kube-prometheus do Revoada raspa o cAdvisor e o kube-state-metrics a cada 30 s) |
| `--namespace` | `querido-diario` | `querido-diario-tcc` no Revoada |
| `--prometheus-svc` | `monitoring/monitoring-kube-prometheus-prometheus` | serviço do Prometheus usado pelo `--port-forward` |
| `--sem-postgres` | — | não consulta o Postgres no fim |

A janela do `rate()` é 4 × o passo, com mínimo de 1 min (1 min na campanha K, 2 min na R).

### No Revoada

Não temos port-forward nem proxy da API para o namespace `monitoring`, então o script roda num pod do nosso namespace, que alcança `http://prometheus-k8s.monitoring.svc:9090`. O pod está em [`simulador/k8s/export-metrics-pod.yaml`](../../simulador/k8s/export-metrics-pod.yaml), com os comandos no cabeçalho: aplicar o pod, copiar os dois scripts com `kubectl cp`, rodar com `kubectl exec` e copiar `resultados/` de volta. As conexões vêm das variáveis de ambiente do pod (Prometheus, `redis-queue` e Postgres, com as credenciais do `app-secret`).

Testado em 24/11/2026, com o namespace ainda vazio: de dentro do pod, o Prometheus responde e as séries de CPU, memória, reservas, fase dos pods e `up` vêm com os mesmos filtros do kind (`container!="", image!=""`). O pod precisa de 1 Gi de limite de memória, porque o `uv` chega a ~700 Mi ao instalar as dependências (com 512 Mi ele foi `OOMKilled`). O Grafana (`grafana.monitoring.svc:3000`) também serve: `QD_EXPORT_PROMETHEUS_URL=http://grafana.monitoring.svc:3000/api/datasources/proxy/uid/P1809F7CD0C75ACF3`, com `QD_EXPORT_PROMETHEUS_USER` e `QD_EXPORT_PROMETHEUS_PASSWORD`.

## `<run>.csv`

Formato longo, uma linha por ponto:

| Coluna | Conteúdo |
|---|---|
| `timestamp` | Unix, em segundos |
| `instante` | o mesmo, em ISO 8601 UTC |
| `serie` | nome da série (tabela abaixo) |
| `rotulos` | rótulos que separam as linhas da série, como `k=v;k=v` (vazio quando a série é um único valor) |
| `valor` | número; pontos `NaN` (por exemplo, percentil sem diários na janela) não são gravados |

```python
df = pd.read_csv("resultados/K/E1/C/E1-C-1.csv")
fila = df[df.serie == "fila"].set_index("timestamp").valor
```

Séries (`$NS` = `--namespace`; `$QD` = `job="data-processing"` no modo A, `mode="queue", namespace="$NS"` no B e no C; `W` = janela do `rate()`):

| Série | Rótulos | PromQL | Uso |
|---|---|---|---|
| `processados` | `status` | `sum by (status) (qd_gazettes_processed_total{$QD})` | contagem por resultado. No B e no C, contador acumulado dos workers; no A, o valor do último push |
| `vazao_por_min` | `status` | `60 * sum by (status) (rate(qd_gazettes_processed_total{$QD}[W]))` | vazão ao longo do tempo (só faz sentido no B e no C) |
| `tempo_diario_p50_s`, `_p95_s` | — | `histogram_quantile` de `qd_gazette_processing_seconds` | tempo por diário. No B e no C, sobre `rate(...[W])`; no A, o histograma do último push |
| `coleta_indexado_p50_s`, `_p95_s` | — | idem, com `qd_scrape_to_index_seconds` | latência coleta → indexado |
| `push_time_s` | — | `max(push_time_seconds{job="data-processing"})` | quando o CronJob enviou as métricas (A) |
| `fila`, `dlq` | — | `sum(redis_key_size{namespace="$NS", key=...})` | profundidade da fila e da DLQ; t_vazio |
| `replicas_desejadas`, `replicas`, `replicas_disponiveis` | — | `kube_deployment_spec_replicas`, `_status_replicas`, `_status_replicas_available` do `extraction-worker` | t_rep1, t_zero, réplicas×tempo |
| `cpu_cores` | `pod` | `sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="$NS", container!="", image!=""}[W]))` | CPU·s |
| `memoria_bytes` | `pod` | `sum by (pod) (container_memory_working_set_bytes{...})` | memória·s |
| `request_cpu_cores`, `request_memoria_bytes` | `pod` | `sum by (pod) (kube_pod_container_resource_requests{namespace="$NS", resource=...})` | recursos reservados (E2) |
| `pod_fase` | `pod`, `phase` | `kube_pod_status_phase{namespace="$NS"} > 0` | t_rep1 no A (pod do Job `Running`) |
| `reinicios` | `pod`, `container` | `kube_pod_container_status_restarts_total` | validade: reinício de infraestrutura |
| `oomkilled` | `pod`, `container` | `kube_pod_container_status_last_terminated_reason{reason="OOMKilled"} > 0` | validade e resultado (worker `OOMKilled`) |
| `alvo_up` | `job` | `up` dos alvos do namespace e do Pushgateway | validade: buraco nas séries |
| `pg_processados`, `pg_pendentes`, `pg_pendentes_sem_dlq` | — | Postgres, gravado pelo `--acompanhar` | t_doc1 e vazão no A; t_vazio |

As séries cobrem o namespace inteiro, inclusive Postgres, OpenSearch, Garage e outros serviços. A escolha dos pods de processamento de cada modo ([cenarios.md](cenarios.md#instantes-e-medidas)) é feita na análise, pelo rótulo `pod`.

As séries `pg_*` só existem se o `--acompanhar` rodou durante a execução. Ele grava `<run>-postgres.csv` na mesma pasta, e o export copia para o CSV principal os pontos entre `--start` e `--end`.

## `<run>.json`

O export escreve só a chave `export`. Se o `.json` já existir (gravado pelo `run_experiment.sh`, #33, com os instantes, os parâmetros, os commits e o *digest*), as outras chaves são mantidas.

| Campo | Conteúdo |
|---|---|
| `inicio`, `fim`, `passo_s`, `janela_rate`, `namespace`, `prometheus` | parâmetros da exportação |
| `linhas_por_serie`, `series_vazias` | para conferir que "o CSV sai com todas as séries" (piloto). Vazias esperadas: no A, as da fila e das réplicas; no B e no C, `push_time_s`; sem falhas, `oomkilled`. Os percentis ao longo do tempo (`tempo_diario_*`, `coleta_indexado_*`) ficam vazios no B e no C quando todos os diários terminam entre dois *scrapes*, porque o `rate()` não vê aumento; isso só acontece com N muito pequeno, e o resumo abaixo continua valendo |
| `prometheus_resumo` | a execução inteira, numa consulta instantânea em `--end`: `processados_por_status` e, para `tempo_diario_s` e `coleta_indexado_s`, os `buckets`, `soma`, `contagem`, `media`, `p50`, `p95` e `p99` |
| `postgres_fim` | diários sintéticos no fim: `sinteticos`, `processados`, `pendentes` e `pendentes_sem_dlq` |
| `dlq` | `tamanho`, `ids` e as `entradas` de `qd:extraction:dead` (`id`, `error`, `ts`); `null` no modo A |

Como o resumo é calculado:

- **B e C:** para cada série (cada pod é uma série), o máximo no intervalo menos o valor no início; uma série que nasce durante a execução (pod novo) conta inteira. Isso dá a contagem certa também no B, em que o mesmo worker fica de pé entre execuções e o contador vem acumulado. Não se usa `increase()`, que perderia os primeiros diários de cada pod novo: o contador só aparece no `/metrics` depois do 1º diário. A conta quebra se um contêiner reiniciar **dentro do mesmo pod** (OOMKill), porque o contador zera; nesse caso, vale o Postgres.
- **A:** o Pushgateway guarda o histograma da última execução inteira, então o resumo é o valor direto. Se o último push for anterior a `--start` (o Job morreu, como no R1, ou ainda não terminou), o resumo fica vazio, com uma `observacao`, e vale o Postgres.

O máximo de `qd_gazette_processing_seconds` (necessário para o `QUEUE_VISIBILITY_TIMEOUT` do R1) não existe num histograma. O limite superior do bucket mais alto com diários, em `buckets`, é a cota superior, e o `p99` é uma estimativa.

## Execução de teste

Em 24/11/2026, no kind, modo C: `load_simulator.py --profile burst --total 10 --duration 30s --seed 1 --corrupt 2`, disparo manual do `enqueue-extraction`, `--acompanhar` durante a execução e export ao fim, depois de as réplicas voltarem a 0 (176 s, passo de 15 s). Resultado: 1180 linhas no CSV, com fila 10 → 0, DLQ 0 → 2, réplicas 0 → 1 → 0, CPU e memória por pod e as séries `pg_*`. No `.json`: `processados_por_status` = 8 `ok` + 2 `error`; `postgres_fim` = 10 sintéticos, 8 processados, 2 pendentes e 0 pendentes fora da DLQ; e a DLQ com os ids dos 2 corrompidos (Tika respondeu HTTP 422). Os percentis ao longo do tempo ficaram vazios pelo motivo descrito acima: cada diário levou ~0,5 s.

No Revoada, o teste foi só de conectividade, com o namespace ainda vazio (ver [No Revoada](#no-revoada)).
