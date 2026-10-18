# 0011. Observabilidade com Prometheus e Grafana
Data: 18/10/2026
Status: Proposto

## Contexto e Declaração do Problema
O TCC compara duas arquiteturas de processamento dos diários: a atual, um CronJob `data-processing` que roda de hora em hora e processa em série os diários pendentes, e a proposta, uma fila de extração com workers escalados pelo KEDA (Parte C, ADRs 0009 e 0010). Para comparar as duas nos experimentos de elasticidade, é preciso medir, nas duas arquiteturas e com a mesma definição:

- vazão (diários processados por minuto, por status);
- tempo de processamento por diário e latência entre a coleta (`scraped_at`) e a indexação;
- profundidade da fila e da DLQ;
- número de réplicas dos workers ao longo do tempo;
- CPU e memória por pod.

Hoje o `querido-diario-data-processing` só tem logs estruturados (`monitoring/`, com `setup_structured_logging` e um resumo de conexões com Tika e OpenSearch no fim da execução). O `querido-diario-deployment` não tinha nenhum manifest de monitoramento, e a branch `grafana-loki` da `querido-diario-api` trata apenas de logs. O Revoada, cluster onde rodam os experimentos, já tem um Grafana, instalado para o Diego.

Falta decidir com que ferramenta coletar e visualizar essas medidas e como as métricas saem de cada arquitetura, já que o CronJob é um processo batch que termina e os workers da fila são processos de longa duração.

## Fatores Determinantes da Decisão
- Medidas numéricas e comparáveis entre as duas arquiteturas, com séries temporais e percentis
- Acesso às métricas do cluster (réplicas, CPU, memória), que não saem do código da aplicação
- Ferramenta open source, sem custo e já usada pela comunidade e pelos mantenedores
- Reaproveitamento do que já existe no Revoada
- Esforço de implementação dentro do prazo do TCC
- A observabilidade não pode afetar o processamento dos diários
- Pouco consumo de recursos no cluster kind local, que roda num notebook

## Alternativas Consideradas

**Ferramenta**
- A1: Apenas logs estruturados, extraindo as medidas dos logs do data-processing (com `scripts/analyze_logs.py` ou com Loki)
- A2: Prometheus + Grafana, com métricas da aplicação instrumentadas via `prometheus-client` e métricas do cluster via `kube-prometheus-stack`
- A3: OpenTelemetry (métricas e traces) com um coletor e um backend de observabilidade

**Como as métricas do CronJob chegam ao Prometheus**
- B1: Pushgateway: o CronJob envia as métricas no fim de cada execução
- B2: Expor `/metrics` no próprio Job e deixar o Prometheus raspar enquanto ele roda
- B3: Gravar as medidas no Postgres e lê-las depois

**Registry das métricas da aplicação**
- C1: Registry padrão do `prometheus-client`
- C2: Registry próprio (`CollectorRegistry`) só com as métricas `qd_*`

## Alternativa Escolhida

**Ferramenta: A2.** Prometheus para coletar e guardar as séries e Grafana para os dashboards. No kind local, a stack sobe com `make k8s-local-monitoring` (`kube-prometheus-stack` e `prometheus-pushgateway`, no namespace `monitoring`, com os values de `k8s/local/monitoring-values.yaml`). No Revoada, usamos o Grafana que já existe e um Prometheus que colete o namespace de testes (#42).

Justificativa: as perguntas dos experimentos são numéricas (vazão, percentis, profundidade da fila, réplicas) e precisam ser vistas ao longo do tempo, lado a lado com o uso de CPU e memória. Os logs registram eventos, e não séries: tirar percentis e taxas deles exige um parser próprio (o `analyze_logs.py` só gera um relatório por execução) ou um Loki com consultas LogQL de agregação, e nenhum dos dois traz réplicas, CPU ou memória, que vêm do kubelet e do kube-state-metrics. Os percentis do Prometheus vêm de histogramas com buckets fixos, o que dá a mesma medida no CronJob e na fila. Prometheus e Grafana são open source, foram o que o Diego e o Nelson sugeriram, o Revoada já tem um Grafana e o KEDA, usado na Parte C, também expõe métricas no formato do Prometheus. OpenTelemetry (A3) resolveria o mesmo problema, mas acrescenta um coletor e um backend que nenhum dos clusters tem hoje, e os traces não são necessários para os experimentos.

Os logs estruturados continuam. Eles servem para diagnosticar um diário específico (qual arquivo falhou e por quê), e as métricas servem para medir o comportamento do pipeline. Um Loki, como o da branch `grafana-loki`, pode ser adicionado ao mesmo Grafana no futuro sem mudar esta decisão.

As métricas da aplicação ficam em `monitoring/metrics.py`, no `querido-diario-data-processing` (#16):

| Métrica | Tipo | Rótulos |
|---|---|---|
| `qd_gazettes_processed_total` | Counter | `mode`, `status` (`ok`, `unsupported`, `error`) |
| `qd_gazette_processing_seconds` | Histogram | `mode` |
| `qd_scrape_to_index_seconds` | Histogram | `mode` |

**Push × pull: B1 para o CronJob, scrape para os workers.** O CronJob é batch e costuma terminar antes de qualquer scrape, por isso, no fim de `execute_pipeline`, envia as métricas ao Pushgateway com `job="data-processing"` quando `PUSHGATEWAY_URL` está definida. O Prometheus raspa o Pushgateway com `honorLabels: true`, o que mantém o `job="data-processing"` em vez do job do próprio Pushgateway. Os workers da fila são processos longos, então expõem `/metrics` com `start_metrics_server()` (porta `METRICS_PORT`, padrão 9100) e são raspados via `PodMonitor` (#21, #24). As mesmas séries servem às duas arquiteturas, distinguidas pelo rótulo `mode` (`cron` ou `queue`), que vem de `PIPELINE_MODE`.

Justificativa: expor `/metrics` no Job (B2) perderia as métricas de execuções mais curtas que o intervalo de scrape (10 s no kind), e a execução sem diários pendentes termina em segundos. Gravar no Postgres (B3) misturaria medidas de experimento com os dados do produto e exigiria escrever no Grafana as consultas que o Prometheus já faz.

**Registry: C2.** Só as métricas `qd_*` vão ao Pushgateway. Com o registry padrão (C1), o push levaria também as métricas de processo (CPU, memória, descritores de arquivo do processo Python), que ficariam "congeladas" no Pushgateway com o valor do momento do push e continuariam sendo raspadas como se o processo ainda existisse.

**Falha no push não derruba o pipeline.** `push_metrics_if_configured()` captura qualquer exceção do envio e só registra um aviso no log. Com `PUSHGATEWAY_URL` vazia, que é o valor da base do `app-config`, nada é enviado. Uma execução que indexou os diários não pode falhar porque o monitoramento estava fora do ar.

**Limitação conhecida.** Cada push substitui o grupo `job="data-processing"`, então o Pushgateway guarda só a última execução, e os contadores voltam a zero a cada uma. O histórico fica no Prometheus, que guardou cada valor raspado. Por isso, no dashboard *Querido Diário / Pipeline* (#17), a primeira linha mostra os valores diretos da última execução e `push_time_seconds{job="data-processing"}` (horário do último push), e nos gráficos com `rate()` cada execução do CronJob aparece como um pico. Para o CronJob, os percentis de uma janela só são válidos se ela cobrir pelo menos uma execução.

## Prós e Contras das Alternativas

| Alternativa | Prós | Contras |
| -------- | -------- | -------- |
| A1 — Apenas logs estruturados | Já existe no data-processing; nenhum componente novo no cluster | Medidas numéricas exigem parser ou LogQL de agregação; sem réplicas, CPU e memória; percentis calculados por execução, e não comparáveis entre arquiteturas |
| A2 — Prometheus + Grafana (escolhida) | Séries temporais e percentis prontos; métricas do cluster e do KEDA no mesmo lugar; open source; Grafana já existe no Revoada; sugerido pelos mantenedores | Mais componentes no cluster (cerca de 1 GB de RAM no kind); o CronJob precisa do Pushgateway |
| A3 — OpenTelemetry | Padrão aberto para métricas, traces e logs | Coletor e backend novos em dois clusters; traces fora do escopo dos experimentos; mais esforço para o mesmo resultado |
| B1 — Pushgateway para o CronJob (escolhida) | Não perde execuções curtas; padrão recomendado pelo Prometheus para jobs batch | Guarda só a última execução; contadores zeram a cada execução |
| B2 — `/metrics` no Job | Mesmo mecanismo dos workers | Perde as execuções mais curtas que o intervalo de scrape; o Job some antes do scrape final |
| B3 — Medidas no Postgres | Histórico completo por execução | Mistura dados de experimento com os do produto; consultas próprias no Grafana |
| C1 — Registry padrão | Nenhum código extra | Métricas de processo congeladas no Pushgateway após o fim do Job |
| C2 — Registry próprio (escolhido) | Pushgateway recebe só o que tem sentido depois do fim do processo | Workers não expõem as métricas de processo do Python, o que não faz falta porque CPU e memória vêm do cAdvisor |
