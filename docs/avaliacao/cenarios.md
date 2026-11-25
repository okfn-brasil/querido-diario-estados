# Cenários de avaliação (ATAM)

Este documento define os cenários de qualidade usados nos experimentos da Parte E (item D3 do plano, issue #29). Cada cenário segue o formato do ATAM: um **estímulo** aplicado ao sistema num **ambiente** conhecido, a **resposta** esperada da arquitetura e a **medida** que diz se a resposta aconteceu. Os mesmos estímulos são aplicados à arquitetura atual (baseline) e à arquitetura proposta (fila de extração, ADR-0009, ADR-0010 e ADR-0011), para que os resultados sejam comparáveis.

Aqui ficam só a definição dos cenários e como aplicá-los. O protocolo de execução (repetições, ordem, diário de bordo) está em [protocolo.md](protocolo.md) (E-1); a carga vem do simulador (D2, #28); a coleta das séries, do `export_metrics.py` (D4, #30); e o teto de réplicas, da calibração (D5, #31).

## Resumo

| ID | Atributo | Estímulo | Ambiente | Resposta | Medida |
|---|---|---|---|---|---|
| E1 | Elasticidade | `burst` de N diários | fila vazia, 0 workers | escalar até o teto e voltar a 0 sem intervenção | tempo até a 1ª réplica, tempo até o 1º diário processado (inclui o *cold start* do Tika sidecar, ADR-0010), tempo até esvaziar, réplicas×tempo, CPU·s total |
| E2 | Elasticidade/custo | nenhum diário por 30 min | ocioso | não consumir recursos de processamento | memória/CPU reservadas em repouso (baseline: CronJob + Tika fixo) |
| R1 | Robustez | SIGKILL no processo de um worker (`kill -9` pelo nó do kind) durante o processamento, com `QUEUE_VISIBILITY_TIMEOUT` reduzido | carga E1 | nenhum diário perdido; reprocessado depois do `visibility_timeout` | diários `processed=false` no fim (alvo 0), retentativas, tempo até o diário do pod morto ser reprocessado |
| R1a | Robustez | `kubectl delete pod` (`SIGTERM`, desligamento gracioso) em um worker durante o processamento | carga E1 | o worker termina o diário atual antes de sair; nada é reprocessado | diários `processed=false` no fim (alvo 0), diários reprocessados (alvo 0), duração do desligamento |
| R2 | Robustez | 10 PDFs corrompidos no meio da carga | carga E1 | corrompidos vão para a DLQ, o resto segue | itens na DLQ = 10, vazão dos demais |
| R3 | Robustez | OpenSearch indisponível por 60 s (`kubectl scale sts opensearch --replicas=0`, depois 1) | carga E1 | retentativa com backoff, recupera sozinho | perdas (alvo 0), tempo extra até esvaziar |
| M1 | Manutenibilidade | falha injetada (R2) | — | pessoa identifica a causa só pelo Grafana e pelos logs | tempo até o diagnóstico; questionário aos mantenedores |

R1a é a variante graciosa de R1, explicada na [seção do R1](#r1--worker-morto-no-meio-do-processamento).

## Modos de execução

Todo cenário roda nos três modos do [protocolo](protocolo.md) (E-1), no mesmo cluster, com os mesmos limites de recursos, a mesma imagem (`querido-diario-data-processing:tcc-fila`) e a mesma amostra de PDFs (D1). A única diferença entre eles é a arquitetura.

| Modo | O que é | Como aplicar (no `querido-diario-deployment`) | Disparo do processamento |
|---|---|---|---|
| **A — baseline** | CronJob `data-processing` sequencial e Tika compartilhado (1 réplica, sempre ligado) | `make k8s-local-queue-down` (overlay `dev`), com o CronJob apontado para a imagem `tcc-fila`, como na validação funcional | `kubectl create job --from=cronjob/data-processing <nome> -n $NS` (o `app-config` já define `EXECUTION_MODE=UNPROCESSED`) |
| **B — fila sem elasticidade** | fila com 1 worker fixo (worker + Tika sidecar) | `make k8s-local-queue` e depois `kubectl patch scaledobject extraction-worker -n $NS --type merge -p '{"spec":{"minReplicaCount":1,"maxReplicaCount":1}}'` | `kubectl create job --from=cronjob/enqueue-extraction <nome> -n $NS` |
| **C — proposta** | fila com KEDA, de 0 até o teto | `make k8s-local-queue` (teto 2 no kind; no Revoada, o teto do D5) | igual ao B |

O modo B separa o efeito da *fila* (retentativa, DLQ, devolução de mensagens) do efeito do *paralelismo elástico*. Assim, o ganho de C sobre A não pode ser atribuído só a "usar mais máquinas".

`$NS` é o namespace da aplicação: `querido-diario` no kind e `querido-diario-tcc` no Revoada (sempre com `--context revoada-testes`).

## Condições comuns

### Antes de cada execução

1. `python simulador/load_simulator.py --cleanup`: apaga as linhas `file_url LIKE 'sim://%'`, os PDFs no Garage e os documentos no OpenSearch.
2. Nos modos B e C, com a fila vazia e os workers parados, limpar o Redis da fila: `kubectl exec -n $NS deploy/redis-queue -c redis -- redis-cli FLUSHDB`. O Redis é dedicado (ADR-0009) e só guarda dados da fila. Sem isso, a DLQ (`qd:extraction:dead`) e as chaves `qd:enqueued:*` dos diários que foram para a DLQ, que não expiram, se acumulam de uma execução para a outra e a contagem "itens na DLQ" do R2 deixa de valer.
3. No modo A, conferir que o agendamento do CronJob está suspenso (`kubectl get cronjob data-processing -n $NS -o jsonpath='{.spec.suspend}'` deve dar `true`), para que uma execução de hora cheia não se misture com o Job do experimento. O overlay `dev` já o deixa suspenso; em outro ambiente, suspender com `kubectl patch cronjob data-processing -n $NS -p '{"spec":{"suspend":true}}'`. **Exceção:** no E2 o agendamento é reativado (`"suspend":false`), porque em produção ele roda de hora em hora e isso faz parte do comportamento em repouso.
4. Esperar 2 min com o sistema ocioso (no modo C, com 0 workers).

### Carga

Salvo indicação, todos os cenários usam a carga do E1: `python simulador/load_simulator.py --profile burst --total N --territory 3299999`, ou seja, N diários sintéticos inseridos em 5 min a partir da amostra do D1. O N de cada cenário e de cada campanha está em [Parâmetros fixados](protocolo.md#parâmetros-fixados) (300 no E1, 1500 no R1 e 100 no R1a, no R2 e no R3, na campanha K). O perfil `peak-day` do D2 não entra nos cenários: sozinho, ele ocuparia 8 h, e cada campanha cabe em 1 dia.

O processamento é **disparado manualmente logo depois que o simulador termina a inserção**, nos três modos (coluna "Disparo" da tabela acima). Esse instante é o **t0** de todas as medidas.

- No modo A, o Job lê a lista de pendentes uma vez, no início. Se fosse disparado antes do fim da inserção, ele não veria todos os diários.
- Nos modos B e C, o agendamento de 5 em 5 min do `enqueue-extraction` fica **suspenso da preparação até o disparo manual** e é reativado logo depois do t0. Sem isso, um agendamento que caísse durante a inserção enfileiraria parte dos diários e o processamento começaria antes do t0, o que não acontece no A (visto num teste do `run_experiment.sh` em 24/11/2026: 2 de 8 diários já processados 3 s depois do t0). Depois do t0, o agendamento não atrapalha (o produtor não enfileira de novo um diário que já está na fila, por causa de `qd:enqueued:{id}`). No E2 ele fica ativo o tempo todo, porque faz parte do repouso do B e do C.
- Disparar o baseline na hora é favorável a ele: em produção, o diário espera até a próxima hora cheia. Essa espera estrutural (de 0 a 60 min, 30 min em média) não entra nas medidas do experimento. Ela é reportada à parte, ao discutir a latência coleta → indexado.

### Fim da execução

A execução termina quando não há mais diários sintéticos pendentes (consulta abaixo) **e**, nos modos B e C, a lista `extraction` está vazia, ou quando estoura o timeout definido no `run_experiment.sh`. No modo C, a coleta de séries continua até as réplicas voltarem a 0, para medir a volta ao repouso.

Diários que foram para a DLQ continuam `processed=false`. Nos cenários em que a DLQ é a resposta esperada (R2), eles saem da contagem de pendentes, ou a execução nunca terminaria:

```sql
-- pendentes que ainda podem ser processados
SELECT count(*) FROM gazettes
WHERE file_url LIKE 'sim://%' AND NOT processed
  AND id NOT IN (/* ids da DLQ: LRANGE qd:extraction:dead 0 -1 */);
```

### Repetições e registro

Três repetições por cenário × modo (uma no E2), na ordem e com os critérios de validade do [protocolo](protocolo.md). Cada execução é anotada em `resultados/diario-de-bordo.md`, com data, commit de cada repositório, modo, cenário, N, teto, os instantes de cada injeção de falha (t_kill, t_down etc.) e anomalias. As séries são exportadas com `export_metrics.py --start <t0> --end <t_fim>` para `resultados/<cenario>/<modo>/<run>.csv`.

## Instantes e medidas

Instantes usados em mais de um cenário:

| Instante | Definição | Fonte |
|---|---|---|
| t0 | criação do Job de disparo (`enqueue-extraction` ou `data-processing`) | `run_experiment.sh` |
| t_rep1 | 1º instante com uma réplica do `extraction-worker` disponível. No modo A: pod do Job `Running` | `kube_deployment_status_replicas_available{deployment="extraction-worker"} > 0`; no A, `kube_pod_status_phase` |
| t_doc1 | 1º diário processado com `status="ok"` | 1º incremento de `qd_gazettes_processed_total{mode="queue",status="ok"}`; no A, ver a observação abaixo |
| t_vazio | fim da execução (seção anterior) | Postgres + `redis_key_size{key="extraction"}` |
| t_zero | réplicas de volta a 0 (só no modo C) | `kube_deployment_spec_replicas{deployment="extraction-worker"} == 0` |

Medidas:

| Medida | Como calcular |
|---|---|
| Tempo até a 1ª réplica | t_rep1 − t0 |
| Tempo até o 1º diário | t_doc1 − t0. Inclui a subida do pod e, nos modos B/C, a inicialização da JVM do Tika sidecar (20 a 30 s, ADR-0010), que precisa ser reportada |
| Tempo até esvaziar | t_vazio − t0 |
| Vazão | diários `ok` ÷ (t_vazio − t0), em diários/h |
| Réplicas×tempo | integral de `kube_deployment_status_replicas_available` entre t0 e t_zero, em réplica·s. No A, a duração do pod do Job somada ao Tika compartilhado, que fica ligado o tempo todo |
| CPU·s total | integral de `sum(rate(container_cpu_usage_seconds_total{container!="",image!=""}[1m]))` sobre os pods de processamento do modo (lista abaixo), entre t0 e t_zero (ou t_vazio no A) |
| Memória·s | mesma integral, com `container_memory_working_set_bytes` |
| Latência coleta → indexado | p50/p95 de `qd_scrape_to_index_seconds` (ADR-0011) |

**Pods de processamento** considerados em CPU·s, memória·s e no E2: no A, o pod do Job `data-processing` e o `apache-tika`; no B e no C, os pods `extraction-worker` (worker + Tika sidecar), o `redis-queue` (com o `redis-exporter`) e os pods dos Jobs `enqueue-extraction`. O operador do KEDA (namespace `keda`) é reportado à parte: ele é um componente do cluster e pode servir a outras aplicações.

**Métricas do baseline.** O CronJob só envia as métricas `qd_*` ao Pushgateway no fim da execução (ver `observabilidade.md`). Por isso, no modo A, t_doc1 e a vazão ao longo do tempo vêm do Postgres (o `run_experiment.sh` consulta a contagem de `processed=true` periodicamente) ou dos logs do Job, e não do Prometheus. Se o pod do Job morrer (R1), as métricas daquela execução se perdem e só o Postgres conta. O envio é um POST (`pushadd_to_gateway`, okfn-brasil/querido-diario-data-processing#133), que só substitui as métricas enviadas: antes era um PUT, e no piloto da campanha K (25/11/2026) a segunda tentativa do Job, sem diários pendentes, apagava as métricas da primeira. Isso acontece porque, no kind, a fase de temas falha com HTTP 429 do OpenSearch (circuit breaker, heap de 512 MiB) depois da extração, e o `restartPolicy: OnFailure` repete o Job. Os temas ficam fora da medição; o `run_experiment.sh` anota o reinício como anomalia e guarda os logs das tentativas em `<run>-job.log`.

## E1 · Burst de diários

**Objetivo:** medir como cada arquitetura responde a um volume grande de diários que chega de uma vez, como quando vários estados publicam à meia-noite.

**Aplicação:** a carga comum, sem falha injetada.

| Modo | Comportamento esperado |
|---|---|
| A | O Job sobe, processa os N diários em sequência com o Tika compartilhado e termina. Não há réplicas a escalar: t_rep1 é a subida do pod do Job |
| B | O único worker já está de pé (sem *cold start*) e consome a fila sozinho |
| C | O KEDA lê o tamanho de `extraction` a cada 10 s e sobe 1 réplica a cada 5 mensagens, até o teto. Cada réplica nova paga a inicialização do Tika. Depois que a fila esvazia, as réplicas voltam a 0 após o `cooldownPeriod` e a janela de estabilização (120 s cada), em cerca de 2 a 4 min |

**Medidas:** todas as da tabela de medidas. O gráfico central é a profundidade da fila × réplicas × tempo (E-3).

**Critério da resposta:** no modo C, as réplicas chegam ao teto e voltam a 0 sem nenhuma intervenção, e todos os N diários terminam `processed=true`.

## E2 · Repouso

**Objetivo:** medir quanto cada arquitetura reserva quando não há nada para processar. É o custo que a escala a zero deve eliminar.

**Aplicação:** depois do cleanup, com 0 diários pendentes e, no modo C, com as réplicas já em 0, deixar o sistema 30 min sem carga. No modo A, o agendamento de hora em hora do CronJob é **reativado** durante a janela (o overlay `dev` o deixa suspenso): se uma hora cheia cair na janela, o Job sobe, não encontra nada e termina, e isso faz parte do custo em repouso.

**Medidas**, integradas sobre os 30 min e também como média:

- recursos reservados: `sum(kube_pod_container_resource_requests{namespace="$NS", resource="memory"})` e o mesmo com `resource="cpu"`, só para os pods de processamento do modo;
- uso real: `container_memory_working_set_bytes` e `rate(container_cpu_usage_seconds_total[1m])` dos mesmos pods.

| Modo | O que fica reservado em repouso |
|---|---|
| A | Tika compartilhado (1 réplica, 512 Mi de *request* no `dev`), mais o pod do Job durante uma execução de hora cheia, se houver |
| B | 1 worker + 1 Tika sidecar, o `redis-queue` e os Jobs `enqueue-extraction` de 5 em 5 min |
| C | o `redis-queue` e os Jobs `enqueue-extraction`; nenhum worker e nenhum Tika |

**Critério da resposta:** no modo C, nenhum pod de extração existe durante a janela. O `redis-queue` é um custo fixo da proposta e entra na comparação, não é descontado.

## R1 · Worker morto no meio do processamento

**Objetivo:** mostrar que um worker que morre de verdade (`SIGKILL`, nó que cai, OOM) não faz um diário se perder.

### Por que SIGKILL e `QUEUE_VISIBILITY_TIMEOUT` reduzido (ADR-0009)

Um `kubectl delete pod` simples manda `SIGTERM`. Com `terminationGracePeriodSeconds: 300`, o worker do Celery faz um desligamento gracioso: termina o diário atual, confirma a mensagem e só então sai. Nesse caso nada se perde, mas o teste também não exercita a recuperação. Para simular um worker que morre de fato, R1 manda SIGKILL direto no processo principal do contêiner, pelo nó do kind, como num OOMKill:

```bash
NO=$(kubectl get pod <pod> -n $NS -o jsonpath='{.spec.nodeName}')
CID=$(kubectl get pod <pod> -n $NS -o jsonpath='{.status.containerStatuses[?(@.name=="worker")].containerID}' | sed 's|^containerd://||')
docker exec $NO kill -KILL $(docker exec $NO crictl inspect $CID | jq -r .info.pid)
```

O plano era `kubectl delete pod --grace-period=0 --force`, mas ele não mata na hora: o pod some da API, e o kubelet ainda manda `SIGTERM` e só mata depois de 2 s (no containerd: `StopContainer ... with timeout 2 (s)`). Na verificação de 25/11/2026, nesses 2 s o worker do B terminou o diário (~0,6 s), confirmou a mensagem e devolveu à fila as reservadas: nenhuma órfã, e o R1 não exercitou a recuperação. O kubelet reinicia o contêiner morto no mesmo pod (o Tika sidecar continua de pé). No Revoada não há acesso ao nó; o R1 fica só na campanha K.

No transporte Redis do Celery, a mensagem reservada por esse worker não volta para a lista `extraction`: ela fica guardada à parte, nas chaves `unacked` e `unacked_index`, e só é devolvida à fila depois do `visibility_timeout`. O padrão é 2 h, longo demais para um experimento. Por isso, no R1, o `extraction-worker` roda com o timeout reduzido:

```bash
kubectl set env deployment/extraction-worker -n $NS QUEUE_VISIBILITY_TIMEOUT=300
```

O valor precisa ser **maior que o tempo do diário mais demorado da amostra do D1**. Se ele for menor, a mensagem é entregue a outro worker enquanto o primeiro ainda processa o diário, e o teste passa a medir processamento duplicado em vez de recuperação. Antes do R1, conferir o máximo de `qd_gazette_processing_seconds` nas execuções do E1 no mesmo ambiente. Se algum diário passar de uns 4 min, subir o valor e registrar o novo. **Valor usado: 300 s** (atualizar aqui e no diário de bordo se mudar). Depois do R1, voltar ao padrão com `kubectl set env deployment/extraction-worker -n $NS QUEUE_VISIBILITY_TIMEOUT-`.

### Aplicação

1. Iniciar a carga do E1 com o timeout reduzido.
2. Quando houver pelo menos um worker processando um diário e **ainda houver fila para mais que `visibility_timeout` + 2 min de processamento** (por exemplo, com no máximo 25% dos diários processados), escolher um pod de worker e anotar t_kill:
   SIGKILL no contêiner `worker` desse pod, como acima.
3. Logo depois, identificar a mensagem órfã: `kubectl exec -n $NS deploy/redis-queue -c redis -- redis-cli ZRANGE unacked_index 0 -1 WITHSCORES` lista as mensagens reservadas e o instante da entrega. A do pod morto é a que continua lá depois que os demais workers passam para o próximo diário. `HGET unacked <tag>` mostra o corpo da mensagem, com o `gazette_id`.
4. Acompanhar até a tag sair de `unacked_index` (t_restore) e o diário ficar `processed=true` (t_reproc).

**Requisito para a recuperação:** quem devolve a mensagem órfã à fila é um worker vivo, que consulta periodicamente as mensagens não confirmadas cujo prazo venceu. O KEDA olha só o tamanho da lista `extraction` e não vê a órfã. Se a fila esvaziar e as réplicas voltarem a 0 antes do `visibility_timeout`, a órfã fica parada até algum worker subir de novo. O produtor também não a reenfileira enquanto a chave `qd:enqueued:{id}` existir, e ela dura 6 h. Por isso o passo 2 exige fila restante maior que o timeout. Se mesmo assim a fila esvaziar antes de t_restore, isso é registrado como resultado (é uma limitação real da combinação Celery + Redis + escala a zero) e entra nas limitações da ADR-0009.

| Modo | Aplicação e resposta esperada |
|---|---|
| A | SIGKILL no contêiner `data-processing` do pod do Job. Com `restartPolicy: OnFailure`, o kubelet reinicia o contêiner no mesmo pod, que relê os pendentes e reprocessa do início da lista, inclusive o diário interrompido. Não há `visibility_timeout`: o tempo de recuperação é a volta do contêiner. As métricas `qd_*` do pod morto se perdem (ver "Métricas do baseline") |
| B | O kubelet reinicia o contêiner do único worker no mesmo pod (o Tika sidecar continua de pé). O worker novo consome a fila e, depois de t_kill + `visibility_timeout`, recebe de volta a mensagem órfã |
| C | Os demais workers seguem. O contêiner morto é reiniciado pelo kubelet, e a órfã volta à fila depois do `visibility_timeout` |

**Medidas:** diários sintéticos `processed=false` no fim (alvo 0); retentativas (no B e no C, entregas repetidas do mesmo `gazette_id` nos logs dos workers; no A, diários processados mais de uma vez); t_restore − t_kill (esperado: ≈ `visibility_timeout`); t_reproc − t_kill; tempo extra até esvaziar em relação ao E1 do mesmo modo.

### R1a · Desligamento gracioso

Variante com `kubectl delete pod <pod> -n $NS`, sem `--force`, e com o `visibility_timeout` padrão. É o que acontece num scale-down do KEDA, num *rollout* ou num *drain* de nó.

- **B e C:** o worker recebe `SIGTERM`, termina o diário atual dentro dos 300 s de `terminationGracePeriodSeconds` e confirma a mensagem. O Tika sidecar continua de pé até o worker sair (native sidecar, ADR-0010). Esperado: 0 diários reprocessados e 0 perdidos. Medir a duração do desligamento (do `delete` até o pod sumir).
- **A:** o processo do CronJob não trata `SIGTERM` e morre na hora, como no R1. A diferença entre R1 e R1a só aparece nos modos com fila.

## R2 · PDFs corrompidos no meio da carga

**Objetivo:** mostrar que diários com defeito permanente são isolados sem travar nem atrasar os demais.

**Aplicação:** a carga do E1 com 10 diários corrompidos distribuídos no meio da inserção (por exemplo, entre 25% e 75% do volume). O simulador precisa de uma opção para isso (por exemplo, `--corrupt 10`), que grave os ids dos corrompidos para conferir depois.

**Como corromper:** um arquivo que começa com um cabeçalho PDF válido (`%PDF-1.7`) seguido de bytes aleatórios, sem objetos nem tabela `xref`, do tamanho de um PDF da amostra. Com o cabeçalho, o `libmagic` identifica `application/pdf` e o Tika tenta o PDFBox, que falha e devolve um erro HTTP. No worker, isso vira `requests.HTTPError`, que não está entre os erros transitórios da task: o diário vai direto para a DLQ, sem retentativa. Duas formas de corromper **não** servem:

- PDF truncado: o PDFBox é tolerante, recupera parte do texto e o diário termina `ok`;
- bytes aleatórios sem cabeçalho: o tipo vira `application/octet-stream` e o Tika pode devolver texto vazio com HTTP 200.

Antes da primeira execução, conferir um arquivo corrompido direto no Tika (`curl -s -o /dev/null -w '%{http_code}' -T corrompido.pdf http://localhost:9998/tika`, com port-forward) e confirmar que a resposta não é 200.

Conferido em 24/11/2026 com a imagem `okfn-brasil/querido-diario-apache-tika-server:latest` e um arquivo gerado pelo `pdf_corrompido()` do simulador: HTTP 422 e nenhum texto, com ou sem `Content-Type: application/pdf` (o `file --mime-type` também dá `application/pdf`). Um PDF sintético normal da amostra, para comparação, dá HTTP 200 com o texto completo.

| Modo | Resposta esperada |
|---|---|
| A | Cada corrompido gera um erro no log do Job, que segue para o próximo diário. Os 10 terminam `processed=false` e entram no push com `status="error"`. Não há DLQ: a cada execução de hora em hora, o CronJob tenta os 10 de novo |
| B e C | Cada corrompido falha uma vez e vai para `qd:extraction:dead`, com o erro. Os demais seguem normalmente. Os 10 não voltam à fila, porque a chave `qd:enqueued:{id}` fica sem expiração enquanto o diário está na DLQ |

**Medidas:** `LLEN qd:extraction:dead` = 10 e os ids da DLQ iguais aos 10 corrompidos (B e C); `qd_gazettes_processed_total{status="error"}` = 10; todos os outros N − 10 terminam `processed=true`; vazão dos demais em relação ao E1 do mesmo modo (o esperado é a mesma, dentro do desvio entre repetições).

## R3 · OpenSearch indisponível

**Objetivo:** mostrar que uma indisponibilidade curta de uma dependência é absorvida pela retentativa e não exige intervenção.

**Aplicação:** durante a carga do E1, com cerca de 25% dos diários processados:

```bash
kubectl scale sts opensearch -n $NS --replicas=0   # t_down
sleep 60
kubectl scale sts opensearch -n $NS --replicas=1   # t_up_cmd
kubectl wait pod/opensearch-0 -n $NS --for=condition=Ready --timeout=10m   # t_ready
```

A indisponibilidade real é **t_ready − t_down**, e não os 60 s nominais: o OpenSearch ainda leva um tempo para iniciar a JVM e recuperar os shards. Esse é o valor reportado.

**Mecanismos de retentativa envolvidos:**

- `OpenSearchInterface` tenta 3 vezes, com espera de 1, 2 e 4 s (`index/opensearch.py`), nos dois modos;
- só nos modos B e C, a task `extract_gazette` trata `opensearchpy.ConnectionError` como transitório e é reenfileirada até 5 vezes, com *backoff* exponencial e *jitter* (`retry_backoff_max=600`). Esgotadas as tentativas, o diário vai para a DLQ.

**Risco conhecido:** com `retry_jitter=True`, cada espera é sorteada entre 0 e 2ⁿ s, então as 5 retentativas somam no máximo cerca de 30 s, mais uns 7 s das tentativas internas a cada execução. Essa janela pode ser menor que a indisponibilidade real, e os diários que chegarem à indexação nesse intervalo podem esgotar as tentativas e ir para a DLQ. Eles não se perdem (continuam `processed=false` e estão na DLQ, com o erro), mas a resposta "recupera sozinho" não se cumpre para eles. Se isso acontecer, o resultado é registrado como está, e o ajuste (por exemplo, mais tentativas, ou um *backoff* que cubra alguns minutos) vira uma variante R3′, documentada na ADR-0009.

| Modo | Resposta esperada |
|---|---|
| A | Os diários que chegam à indexação durante a janela falham depois das 3 tentativas internas e são pulados. O Job termina com esses diários `processed=false`, que só seriam processados na próxima hora cheia. No experimento, um segundo Job é criado logo depois do primeiro, para medir quanto tempo ele leva. A espera até a próxima hora cheia é reportada à parte |
| B e C | As tasks afetadas são reenfileiradas com *backoff* e processadas quando o OpenSearch volta, sem intervenção |

**Medidas:** perdas = diários `processed=false` no fim que **não** estão na DLQ (alvo 0); diários na DLQ por causa da indisponibilidade (alvo 0 para "recupera sozinho"); diários pulados que ficaram para outra execução (A); retentativas (`Retry in` nos logs dos workers); tempo extra até esvaziar em relação ao E1 do mesmo modo; indisponibilidade real (t_ready − t_down).

## M1 · Diagnóstico de uma falha

**Objetivo:** avaliar se a observabilidade da proposta (ADR-0011) permite a quem mantém o Querido Diário entender uma falha sem ler o código.

**Aplicação:**

1. Rodar o R2 (10 PDFs corrompidos) sem avisar a pessoa participante de qual falha foi injetada.
2. Entregar o acesso ao Grafana (dashboard do pipeline) e aos logs (`kubectl logs`), com a pergunta: *"Algo deu errado no processamento dos diários desta execução. O que aconteceu e quais diários foram afetados?"*
3. Cronometrar até a pessoa dizer a causa (arquivo inválido/corrompido, erro do Tika) **e** quais diários foram afetados (os ids ou, pelo menos, a quantidade correta). Limite de 15 min. Se estourar, registrar como "não diagnosticado".
4. Aplicar o questionário do E-4 (5 a 7 perguntas, escala Likert e respostas abertas): clareza do fluxo, facilidade de diagnosticar, disposição de adotar.

| Modo | O que a pessoa tem para diagnosticar |
|---|---|
| A | o painel "Diários por status" do último push (`status="error"`) e os logs do Job |
| C | o painel de DLQ (linha 3 do dashboard), a DLQ no Redis (`LRANGE qd:extraction:dead 0 -1`, com o erro de cada diário) e os logs dos workers |

O modo B não entra: para o diagnóstico, ele é igual ao C.

Para não haver efeito de aprendizado, cada pessoa faz um único modo. Se houver só uma ou duas pessoas, ela faz os dois modos, primeiro o A, e isso é registrado. Com poucas participantes, M1 é qualitativo: os tempos são reportados individualmente, sem média.

**Medidas:** tempo até o diagnóstico; se a causa e os diários foram identificados corretamente; as respostas do questionário.

## Requisitos para os outros itens

O que este documento pressupõe e ainda precisa estar implementado:

- ~~**D2 (#28):** opção do simulador para inserir diários corrompidos no meio da carga (R2), gravando os ids.~~ Feito: `--corrupt K`, com os ids no `.json` da execução.
- ~~**D4 (#30):** além das séries do Prometheus, exportar a contagem de `processed` do Postgres ao longo da execução (necessária no modo A) e o conteúdo da DLQ no fim.~~ Feito: `export_metrics.py --acompanhar` grava a contagem durante a execução, e o export do fim junta as séries `pg_*` ao CSV e a DLQ ao `.json` ([exportacao.md](exportacao.md)).
- ~~**`run_experiment.sh` (E-2):** limpar o Redis da fila entre execuções (B e C); manter o CronJob suspenso no A, exceto no E2; disparar o processamento logo depois da inserção; registrar os instantes de cada injeção de falha; no R1, aplicar e reverter o `QUEUE_VISIBILITY_TIMEOUT`.~~ Feito: `simulador/run_experiment.sh` ([execucao.md](execucao.md)).
