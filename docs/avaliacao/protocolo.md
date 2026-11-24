# Protocolo experimental

Este documento fixa **antes de qualquer execução** como os experimentos da Parte E são conduzidos (item E-1 do plano, issue #32): o que se compara, o que fica constante, como cada execução é preparada, repetida, validada e registrada, e como os números são resumidos. Os cenários em si (estímulo, resposta esperada, medidas e como aplicar cada um) estão em [cenarios.md](cenarios.md) e não são repetidos aqui.

Qualquer mudança neste protocolo depois da primeira execução válida é registrada na seção [Desvios do protocolo](#desvios-do-protocolo), com a data e o motivo, e as execuções afetadas são marcadas no diário de bordo.

## Perguntas e hipóteses

O experimento responde se a arquitetura proposta (fila de extração com Celery + Redis e workers escalados pelo KEDA, ADR-0009 e ADR-0010) melhora a arquitetura atual (CronJob sequencial) nos atributos de qualidade dos cenários.

| Hipótese | Enunciado | Cenários | Comparação |
|---|---|---|---|
| H1 · Elasticidade | Com um volume grande de diários chegando de uma vez, a proposta esvazia a fila em menos tempo e volta ao repouso sozinha | E1 | C × A |
| H2 · Custo em repouso | Sem diários para processar, a proposta reserva menos CPU e memória que o baseline | E2 | C × A |
| H3 · Robustez | Com um worker morto, PDFs corrompidos ou o OpenSearch fora do ar, a proposta não perde diários e isola os defeituosos sem parar os demais | R1, R1a, R2, R3 | B e C × A |
| H4 · Manutenibilidade | Quem mantém o Querido Diário diagnostica uma falha mais rápido com a observabilidade da proposta | M1 | C × A |

O modo B separa os dois efeitos da proposta:

- **B × A** isola o efeito da *fila* (retentativa, DLQ, devolução de mensagens), com o mesmo paralelismo do baseline (1 extração por vez);
- **C × B** isola o efeito do *paralelismo elástico*.

Sem o B, um ganho de C sobre A poderia ser atribuído só a "usar mais máquinas".

## Variáveis

**Independentes:** o modo (A, B, C) e o cenário (E1, E2, R1, R1a, R2, R3, M1).

**Dependentes:** as medidas de cada cenário, definidas em [cenarios.md](cenarios.md#instantes-e-medidas).

**Controladas**, iguais em todas as execuções de uma mesma campanha:

| Controle | Como é garantido |
|---|---|
| Mesmo cluster | Todas as execuções de uma campanha rodam no mesmo cluster (ver [Campanhas](#campanhas)). Resultados de campanhas diferentes nunca entram na mesma comparação |
| Mesma imagem de código | `querido-diario-data-processing:tcc-fila` nos três modos, como na validação funcional; no modo A, o CronJob `data-processing` é apontado para ela. O *digest* da imagem é registrado em cada execução |
| Mesmos limites do Tika | 512 Mi de *request* e 1500 Mi de *limit* de memória, tanto no Tika compartilhado (A) quanto no sidecar (B e C), pelos overlays `dev` e `dev-queue` |
| Mesmos limites da infraestrutura | Postgres, OpenSearch, Garage e Redis com os mesmos recursos nos três modos (vêm do overlay `dev`, que o `dev-queue` herda) |
| Mesma amostra de PDFs | `simulador/amostras/` ([amostra.md](amostra.md)), identificada pelo `manifest.csv` (com o `sha256` de cada arquivo) no commit registrado |
| Mesma carga | perfil, N e *seed* do simulador fixos por campanha (ver [Parâmetros fixados](#parâmetros-fixados)) |
| Mesmo estado inicial | preparação da seção [Antes de cada execução](#antes-de-cada-execução) |
| Excertos temáticos fora da medição | os excertos temáticos não fazem parte dos cenários. No A, as medidas terminam em t_vazio, antes de o Job passar aos temas. No B e no C, o CronJob `themes-from-queue` fica suspenso durante as execuções, para não disputar CPU e OpenSearch com a extração |

Os limites de cada componente que **é** a arquitetura não são igualados, porque são parte do que se compara: o pod do Job do baseline pede 1 Gi (*limit* de 8 Gi, porque também roda os temas), e cada worker pede 512 Mi (*limit* de 1 Gi) mais o seu Tika. As medidas de CPU·s e memória·s contabilizam o que cada modo efetivamente usou.

## Campanhas

| Campanha | Ambiente | Escopo | Situação |
|---|---|---|---|
| **K** (obrigatória) | kind local (`querido-diario-dev`), em uma única máquina, com o hardware registrado (CPU, memória dada ao Docker, versão do kind e do Kubernetes) | todos os cenários | — |
| **R** (se houver infraestrutura) | namespace `querido-diario-tcc` no Revoada (`--context revoada-testes`) | E1 e E2, com N maior e o teto do D5; R1a, R2 e R3 se couberem no dia | acesso configurado em 24/11; falta liberar `ServiceMonitor`/`PodMonitor` no namespace (#42) |

**Cada campanha roda em no máximo 1 dia**, sem intervenção depois do piloto (ver [Orçamento de tempo](#orçamento-de-tempo)). Isso reduz a variação do ambiente entre a primeira e a última execução e, no Revoada, o tempo em que o experimento divide o cluster com a produção do Querido Diário (namespace `querido-diario`).

Na campanha R, o monitoramento é o do próprio cluster (kube-prometheus com os padrões, no namespace `monitoring`). O Prometheus dele guarda **só 1 dia** (`retention.time=1d`), então o `export_metrics.py` roda ao fim de **cada** execução, e não ao fim da campanha. Ele roda de dentro do namespace `querido-diario-tcc` e consulta `http://prometheus-k8s.monitoring.svc:9090`.

Na campanha K, a máquina fica dedicada ao experimento durante cada execução: sem outros contêineres, builds, navegador com abas pesadas ou chamada de vídeo. No Revoada, que é compartilhado, registrar no diário de bordo a carga do nó no início da execução (`kubectl top nodes`, quando disponível) e qualquer atividade conhecida de outros usuários.

## Parâmetros fixados

Valores fixados para a campanha K. Eles são preenchidos **antes** da primeira execução válida e não mudam depois sem um registro em [Desvios do protocolo](#desvios-do-protocolo).

| Parâmetro | Valor (campanha K) | Observação |
|---|---|---|
| Perfil de carga | `burst` | N diários inseridos em 5 min (D2) |
| N do E1 e do R1 | 300 | dentro da faixa 200–500 do D2. O R1 não pode ter N menor: depois do t_kill, a fila precisa durar mais que `visibility_timeout` + 2 min (ver [cenarios.md](cenarios.md#r1--worker-morto-no-meio-do-processamento)) |
| N do R1a, R2 e R3 | 100 | esses cenários medem perda, isolamento e recuperação, não vazão. Com 100 diários, ainda há processamento antes, durante e depois de cada falha, e a campanha cabe em 1 dia |
| Revisão de N depois do piloto | — | refazer o [orçamento](#orçamento-de-tempo) com as durações medidas no piloto. Se a campanha passar de 20 h, reduzir o N do E1 (até 200) e registrar; o do R1 só cai se a condição de fila restante continuar valendo |
| Território | `3299999` | Governo do Estado do Espírito Santo |
| *Seed* do simulador | igual ao número da repetição (1, 2, 3) | a repetição *k* usa a mesma *seed* nos três modos, então os três processam a mesma sequência de PDFs |
| Teto do modo C | 2 | o do overlay `dev-queue`; o teto do D5 vale para a campanha R |
| `QUEUE_VISIBILITY_TIMEOUT` no R1 | 300 s | ver [cenarios.md](cenarios.md#r1--worker-morto-no-meio-do-processamento) |
| Diários corrompidos no R2 | 10 | entre 25% e 75% da inserção |
| Indisponibilidade do OpenSearch no R3 | 60 s nominais | reportar a real (t_ready − t_down) |
| Janela do E2 | 30 min | depois de 2 min de espera ociosa |
| Timeout de uma execução | 3 × a duração do E1 do modo A na execução piloto | estourou → execução inválida (ver [Validade](#validade-de-uma-execução)) |
| Passo das séries | 15 s | o Prometheus raspa a cada 10 s (`monitoring-values.yaml`) e os PodMonitors do worker e do `redis-queue` a cada 15 s; o `export_metrics.py` usa o maior dos dois como passo do `query_range` |

Na campanha R, mudam: N do E1 = 500, teto do modo C = o do D5, e passo das séries = 30 s (o kube-prometheus do Revoada raspa o cAdvisor e o kube-state-metrics a cada 30 s). O piloto da campanha R revisa esses valores da mesma forma.

## Execução piloto

Antes das execuções válidas, uma execução piloto de E1 em cada modo, que **não entra nos resultados**. Ela serve para:

- conferir que o `run_experiment.sh`, o simulador e o `export_metrics.py` funcionam de ponta a ponta e que o CSV sai com todas as séries;
- medir a duração do E1 do modo A, para fixar N e o timeout;
- conferir o máximo de `qd_gazette_processing_seconds`, que define se o `QUEUE_VISIBILITY_TIMEOUT` de 300 s do R1 basta;
- conferir que um PDF corrompido do R2 faz o Tika responder com erro (não 200).

- medir a duração de cada modo, para refazer o [orçamento de tempo](#orçamento-de-tempo) e, se preciso, revisar N.

O piloto é anotado no diário de bordo, marcado como piloto.

## Orçamento de tempo

Estimativa a partir da validação funcional (C7, no kind): ~4 s por diário no baseline e ~3,3 s por diário em cada worker. Cada execução soma ~3 min de preparação (checklist, cleanup e 2 min de repouso) e ~2 min de troca de modo, que acontece quase sempre por causa da ordem em quadrado latino. No modo C, somam-se o *cold start* do Tika (~30 s) e o `cooldownPeriod` do KEDA (120 s) até as réplicas voltarem a 0.

**Campanha K** (teto 2):

| Etapa | Execuções | Tempo |
|---|---|---|
| Piloto (E1 nos três modos) | 3 | ~1 h |
| E1 (N = 300) | 9 | ~3 h |
| R1 (N = 300, com o `visibility_timeout` de 300 s no B e no C) | 9 | ~3,5 h |
| R1a, R2, R3 (N = 100) | 27 | ~5 h |
| E2 (30 min, 1 por modo) | 3 | ~1,75 h |
| **Total** | **51** | **~14,5 h** |

**Campanha R** (teto do D5):

| Etapa | Execuções | Tempo |
|---|---|---|
| Piloto (E1 nos três modos) | 3 | ~1,25 h |
| D5: E1 no modo C com teto 2, 4, 6 e 8, 1 execução por teto (#31) | 4 | ~1 h |
| E1 (N = 500) | 9 | ~4,25 h |
| E2 (30 min, 1 por modo) | 3 | ~1,75 h |
| **Subtotal obrigatório** | **19** | **~8,25 h** |
| R1a, R2, R3 (N = 100), se couberem | 27 | ~4,5 h |

O R1 fica fora da campanha R: com o teto do D5, a fila esvazia rápido demais para a condição de fila restante sem um N muito maior. A margem até 24 h cobre o ambiente ser até ~1,6× (K) ou ~1,9× (R) mais lento que o estimado. Os tempos da campanha R são extrapolados do kind, e o piloto é o que os confirma.

O `run_experiment.sh` roda uma execução; a campanha inteira, na ordem abaixo, roda por um script que o chama em sequência (E-2, #33), continua depois de uma execução inválida (refazendo-a na mesma posição) e permite retomar do meio.

## Antes de cada execução

Checklist feito pelo `run_experiment.sh` (#33), ou à mão enquanto ele não existir. Cada item que falhar impede a execução.

1. O cluster e o modo estão certos: overlay aplicado (`dev` no A, `dev-queue` no B e no C) e, no B, o `ScaledObject` com `minReplicaCount=maxReplicaCount=1`; no C, com o teto da campanha.
2. Imagem: o *digest* da imagem do data-processing em uso é o registrado para a campanha.
3. Monitoramento: o Prometheus está de pé, raspando os alvos (`up == 1` para o `extraction-worker`, o `redis-queue` e o Pushgateway, conforme o modo), e as séries `redis_key_size` de `extraction` e `qd:extraction:dead` existem (B e C).
4. Infraestrutura saudável: o OpenSearch está *green* ou *yellow*, e todos os pods de infraestrutura estão `Ready`, sem reinícios desde a execução anterior (um reinício é anotado).
5. `python simulador/load_simulator.py --cleanup`.
6. B e C: fila vazia, 0 workers ocupados e `FLUSHDB` no `redis-queue` (ver [cenarios.md](cenarios.md#antes-de-cada-execução)).
7. CronJobs: no A, `data-processing` suspenso (exceto no E2); no B e no C, `themes-from-queue` suspenso.
8. Nenhum diário sintético pendente (`SELECT count(*) FROM gazettes WHERE file_url LIKE 'sim://%'` dá 0).
9. Espera de **2 min** com o sistema ocioso (no C, com 0 réplicas).

## Repetições e ordem

**3 repetições válidas por cenário × modo.** Há duas exceções: o **E2**, com 1 execução por modo, porque o consumo em repouso é quase determinístico (são os *requests* dos pods que ficam de pé, mais o eventual Job de hora cheia no A) e 3 janelas de 30 min por modo custariam 3 h a mais; e o **M1**, em que o número de execuções é o número de pessoas participantes (ver [cenarios.md](cenarios.md#m1--diagnóstico-de-uma-falha)).

Os cenários seguem a ordem do E-2: E1 → R1 → R1a → R2 → R3 → E2 → M1. Dentro de um cenário, a ordem dos modos gira a cada repetição (quadrado latino), para que efeitos do tempo (aquecimento de caches do OpenSearch e do sistema de arquivos, outras cargas no Revoada, aquecimento térmico do notebook) não favoreçam sempre o mesmo modo:

| Repetição | Ordem |
|---|---|
| 1 | A, B, C |
| 2 | B, C, A |
| 3 | C, A, B |

Uma execução inválida é refeita logo depois, na mesma posição da ordem.

Cada execução é identificada por `<cenario>-<modo>-<k>`, por exemplo `E1-C-2`. Uma execução refeita recebe a próxima letra (`E1-C-2b`); a inválida continua no diário de bordo.

## Validade de uma execução

Uma execução é **inválida** se acontecer qualquer um destes:

- o timeout estourou;
- um pod de infraestrutura (Postgres, OpenSearch, Garage, Redis, Prometheus) reiniciou ou foi `OOMKilled`, **salvo** quando isso é o estímulo do cenário (o OpenSearch no R3);
- o Prometheus ficou mais de 1 min sem raspar algum alvo usado pelas medidas (buraco nas séries);
- algum item do checklist anterior foi pulado ou estava errado (por exemplo, o modo B rodou com teto 2);
- uma interferência externa foi observada (no kind: outra carga pesada na máquina; no Revoada: manutenção ou carga anormal de terceiros).

**Não invalida** a execução um comportamento ruim *da arquitetura em teste*: worker `OOMKilled`, diários na DLQ, perdas, réplicas que não voltam a 0. Isso é resultado, e é registrado como tal. A diferença entre "o ambiente falhou" e "a arquitetura falhou" é decidida e justificada no diário de bordo no momento da execução.

Execuções inválidas nunca são apagadas: ficam no diário de bordo, com o motivo, e os CSVs delas vão para `resultados/<cenario>/<modo>/invalidas/`. Se um mesmo cenário × modo tiver mais de 3 execuções inválidas, as execuções param e o problema é investigado antes de continuar.

## Registro

### Diário de bordo

Cada execução, inclusive o piloto e as inválidas, ganha uma entrada em [`resultados/diario-de-bordo.md`](../../resultados/diario-de-bordo.md) **no momento em que roda**, seguindo o modelo que está no próprio arquivo: data e hora, campanha, identificador, commits, *digest* da imagem, parâmetros, instantes de cada falha injetada, se a execução é válida e as anomalias observadas.

### Arquivos

| Arquivo | Conteúdo | Quem gera |
|---|---|---|
| `resultados/<cenario>/<modo>/<run>.csv` | séries do Prometheus entre t0 e o fim (D4) | `export_metrics.py` |
| `resultados/<cenario>/<modo>/<run>.json` | metadados: instantes (t0, t_rep1, t_doc1, t_vazio, t_zero e os das falhas), parâmetros, commits, *digest*, contagens finais do Postgres e conteúdo da DLQ | `run_experiment.sh` + `export_metrics.py` |
| `resultados/<cenario>/<modo>/<run>.log` | saída do `run_experiment.sh` | `run_experiment.sh` |

Os commits registrados são os de `main-estados` de `querido-diario-data-processing` e `querido-diario-deployment`, e o da `main` deste repositório (que fixa o protocolo, o simulador e a amostra). Uma execução com mudanças locais não commitadas em qualquer desses repositórios não é válida.

## Análise

A análise é feita no notebook `resultados/analise.ipynb` (E-3, #34), lendo só os arquivos de `resultados/`, nunca o Prometheus diretamente.

- Para cada medida, cenário e modo: **média e desvio-padrão amostral** (n − 1) das 3 repetições válidas, junto com os 3 valores individuais. Com n = 3, o desvio é só indicativo.
- Não se aplicam testes de significância: com 3 repetições, eles não têm poder para isso. Uma diferença entre modos é tratada como clara quando os intervalos [mínimo, máximo] das repetições não se sobrepõem; caso contrário, é reportada como "inconclusiva com n = 3".
- Comparações são feitas como razões em relação ao baseline (C/A, B/A), e C/B para isolar o efeito do paralelismo, sempre dentro de uma mesma campanha e de uma mesma repetição *k* (que processou a mesma sequência de PDFs).
- Medidas que não se aplicam a um modo (por exemplo, réplicas no A, DLQ no A) aparecem como "—", e não como zero.
- O E2 (1 execução por modo) e o M1 são reportados individualmente, sem média.

## Ameaças à validade

Registradas antes de rodar, para serem retomadas na discussão dos resultados:

- **Escala:** o kind de um notebook comporta só 2 workers e N de algumas centenas. A campanha R reduz essa ameaça para E1 e E2.
- **Carga sintética:** os diários sintéticos repetem os mesmos PDFs da amostra (com um sufixo único para mudar o checksum). A distribuição de tamanhos segue a amostra (`manifest.csv`), e não a de um dia real de publicação.
- **Baseline favorecido:** no experimento, o Job do baseline é disparado logo depois da inserção. Em produção, ele espera até a próxima hora cheia. Essa espera é reportada à parte.
- **Poucas repetições:** 3 por cenário × modo, e 1 no E2; ver [Análise](#análise).
- **N reduzido nos cenários de robustez:** R1a, R2 e R3 usam N = 100 para a campanha caber em 1 dia. Eles respondem se há perda e isolamento, e não comparam vazão; a vazão sob falha é comparada com o E1 do mesmo modo só como indicação.
- **Ambiente compartilhado:** no Revoada, outras cargas podem interferir; o registro da carga do nó e o critério de validade reduzem, mas não eliminam, essa ameaça.
- **Pesquisadoras como operadoras:** as mesmas pessoas que propõem a arquitetura conduzem os experimentos. O protocolo escrito antes, a automação do `run_experiment.sh` e o registro das execuções inválidas reduzem o viés.
- **M1:** poucas pessoas participantes e efeito de aprendizado quando a mesma pessoa faz os dois modos.

## Desvios do protocolo

Mudanças feitas depois da primeira execução válida, com a data, o motivo e as execuções afetadas.

| Data | Mudança | Motivo | Execuções afetadas |
|---|---|---|---|
| — | — | — | — |

## Requisitos para os outros itens

- ~~**D2 (#28):** opção `--seed` no simulador, para que a repetição *k* sorteie a mesma sequência de PDFs nos três modos.~~ Feito: `--seed`, que fixa a sequência de PDFs e as posições dos corrompidos.
- ~~**D4 (#30):** passo do `query_range` de 15 s (30 s na campanha R) e saída dos metadados do Postgres e da DLQ no `.json` da execução; rodar ao fim de cada execução e, no Revoada, de dentro do namespace `querido-diario-tcc`.~~ Feito: `simulador/export_metrics.py` ([exportacao.md](exportacao.md)), com `--step`, a chave `export` no `.json` e o pod `simulador/k8s/export-metrics-pod.yaml` para o Revoada.
- **E-2 (#33):** o `run_experiment.sh` faz o checklist de [Antes de cada execução](#antes-de-cada-execução), suspende o `themes-from-queue` no B e no C, registra commits e *digest* e grava o `.json` e o `.log` de cada execução. Um script de campanha chama o `run_experiment.sh` para cada execução, na ordem de [Repetições e ordem](#repetições-e-ordem), e permite retomar do meio.
