# Execução dos experimentos (E-2)

Dois scripts conduzem as execuções do [protocolo](protocolo.md) (issue #33):

- `simulador/run_experiment.sh <cenario> <modo> <run>` roda **uma** execução: aplica o modo, faz o checklist de [Antes de cada execução](protocolo.md#antes-de-cada-execução), insere a carga, dispara o processamento, injeta a falha do cenário, espera o fim, exporta as séries (D4) e anota o diário de bordo;
- `simulador/run_campaign.sh <K|R> [bloco ...]` chama o `run_experiment.sh` para cada execução de uma campanha, na ordem do protocolo, refaz as inválidas na mesma posição e retoma do meio.

Os parâmetros fixados de cada campanha ficam em `simulador/campanhas/K.env` e `R.env`. Uma variável definida no ambiente tem precedência (útil em teste, por exemplo `N_E1=10 OCIOSO_S=20`), mas uma execução válida usa os valores do arquivo, que é versionado. Mudar o arquivo depois da primeira execução válida é um desvio do protocolo.

## Antes da campanha

1. Repositórios irmãos em `main-estados`, sem mudanças locais: `querido-diario-deployment` (os overlays saem dele) e `querido-diario-data-processing` (só o commit é registrado). Por padrão ficam ao lado deste repositório; em outro lugar, `QD_DEPLOYMENT_DIR` e `QD_DATA_PROCESSING_DIR`. Até okfn-brasil/querido-diario-data-processing#133 entrar na `main-estados`, a imagem da campanha K é a do commit `144d805` (branch `tcc/pushadd-metricas`): aponte `QD_DATA_PROCESSING_DIR` para um checkout dessa branch, para o commit registrado bater com a imagem.
2. A amostra do D1 baixada em `simulador/amostras/` (os PDFs não são versionados): `python3 simulador/montar_amostra.py baixar`.
3. `uv`, `jq`, `kubectl` e, no kind, `docker` (para ler o *digest* da imagem no nó).
4. Kind: a pilha de pé (`make k8s-local-up`, `make k8s-local-monitoring` e `make k8s-local-queue` uma vez, para o KEDA e a imagem `:tcc-fila`). Revoada: VPN ligada e os segredos do namespace criados (`k8s/overlays/revoada-tcc/README.md` no deployment).
5. Máquina dedicada (kind): nenhum outro contêiner no Docker além do nó do kind, ou o checklist falha; feche também o navegador e outros programas pesados. Nos testes de 24/11/2026 a máquina (7,4 GiB) travou duas vezes, com outros 6 contêineres de pé.
6. Disco: o script para com 95% de uso ou mais. Ele também registra a memória disponível e a carga da máquina no `.json` e avisa com menos de 1 GiB livre.

## Campanha

```bash
simulador/run_campaign.sh K piloto      # E1 nos três modos, em resultados/piloto/
# conferir o piloto e fixar IMAGEM_DIGEST, TIMEOUT_S e, se preciso, N em campanhas/K.env
simulador/run_campaign.sh K             # E1 → R1 → R1a, R2, R3 → E2
simulador/run_campaign.sh K --listar    # situação de cada posição
```

A campanha é dividida em **blocos**, sempre entre cenários: `piloto`, `E1`, `R1`, `robustez` (R1a, R2 e R3) e `E2` na campanha K; `piloto`, `E1`, `E2` e `robustez` na R, em que o E1 e o E2 são os obrigatórios e o resto entra se couber no dia. Sem bloco na linha de comando, rodam todos os blocos depois do piloto. Isso permite parar entre blocos, se a máquina não aguentar a campanha inteira de uma vez, sem recriar o kind nem trocar a imagem. Uma campanha dividida que passe de 1 dia é registrada em [Desvios do protocolo](protocolo.md#desvios-do-protocolo).

Dentro de um cenário, os modos giram por repetição (quadrado latino do protocolo), e cada execução se chama `<cenario>-<modo>-<k>`. A situação fica em `resultados/campanha-<K|R>.tsv`, uma linha por tentativa:

| Código | Significado | O que a campanha faz |
|---|---|---|
| 0 | execução válida (ou piloto concluído) | segue para a próxima posição |
| 2 | execução inválida | refaz logo, na mesma posição, com a próxima letra (`E1-C-2b`). Com mais de 3 inválidas num mesmo cenário × modo, para |
| 1 | não rodou (checklist ou ambiente) | para. O `.json` e o `.log` vão para `resultados/nao-executadas/`; corrigir e rodar de novo, que retoma da mesma posição |

O M1 e o D5 (#31) não entram na campanha. O M1 é um R2 conduzido com cada pessoa participante: `run_experiment.sh M1 C M1-C-1`, e o diagnóstico é cronometrado à parte. O D5 usa `run_experiment.sh E1 C E1-C-D5t4-1 --teto 4`.

## Uma execução

```bash
simulador/run_experiment.sh E1 C E1-C-2
simulador/run_experiment.sh R3 A R3-A-1b --campanha K
simulador/run_experiment.sh E1 B E1-B-piloto --piloto
simulador/run_experiment.sh E1 A E1-A-1 --so-checklist   # só prepara e confere
```

O que ela faz, na ordem:

1. **Modo.** A: remove a fila (o `ScaledObject` primeiro), aplica o overlay do baseline (`dev` ou `revoada-tcc`) e, no kind, aponta o CronJob `data-processing` para a imagem `:tcc-fila`. B e C: aplica o overlay da fila (`dev-queue` mais os PodMonitors, ou `revoada-tcc-queue`) e fixa o `ScaledObject`, com `min = max = 1` no B e `min = 0`, `max = teto` no C. O `kubectl apply` não desfaz um `patch` ou um `set env` anterior (o *merge* é de três vias), então o teto e o `QUEUE_VISIBILITY_TIMEOUT` são sempre fixados explicitamente.
2. **Checklist** do protocolo. Cada item vai para `checklist` no `.json`; se um falhar, a execução não roda (código 1). Os alvos do Prometheus são esperados por até 4 min, porque logo depois de uma troca de modo os PodMonitors recriados ainda não foram descobertos. Além dos itens do protocolo, confere os commits: mudanças locais em qualquer dos três repositórios impedem a execução (no piloto, só ficam anotadas). Reinícios de pods de infraestrutura desde a execução anterior são anotados como anomalia.
3. **Espera ociosa** de 2 min (no C, com 0 réplicas).
4. **Carga:** `load_simulator.py --profile burst --total N --seed k`, com `--corrupt 10` no R2 e no M1. O `export_metrics.py --acompanhar` grava a contagem do Postgres durante toda a execução.
5. **Disparo** logo depois da inserção: Job a partir do `data-processing` (A) ou do `enqueue-extraction` (B e C). A criação do Job é o **t0**. No B e no C, o agendamento do `enqueue-extraction` fica suspenso do checklist até aqui e é reativado logo depois do t0, para que nada seja enfileirado durante a inserção ([cenarios.md](cenarios.md#carga)). Todo CronJob reativado pelo script (o `enqueue-extraction` aqui, o `data-processing` no E2-A) ganha `startingDeadlineSeconds: 60`: sem isso, o Kubernetes dispara na hora o último horário perdido enquanto ele estava suspenso, o que não aconteceria em produção.
6. **Espera** até não haver pendentes (sem os da DLQ no B e no C, sem os corrompidos no A) e, no B e no C, a lista `extraction` vazia, com o timeout da campanha. No A, se o Job terminar com pendentes, a execução termina ali (no R3, um segundo Job é criado antes). Depois de t_vazio: no C, espera as réplicas voltarem a 0 (t_zero); no A, espera o Job terminar, porque as métricas `qd_*` só vão ao Pushgateway no fim dele, depois dos temas, e mais 2 × o passo + 15 s, para o Prometheus raspar esse push; no B, a mesma margem depois de t_vazio, para o último scrape do worker. A exportação vai até o último desses instantes, e a análise corta em t_vazio.
7. **Falha**, quando os processados chegam à fração do cenário:

   | Cenário | Quando | O que o script faz |
   |---|---|---|
   | R1 | ~10% processados e um worker ocupado | `QUEUE_VISIBILITY_TIMEOUT=300` no `extraction-worker` antes da carga; SIGKILL no processo do worker mais antigo (A: no contêiner do Job), pelo nó do kind (`crictl inspect` → PID → `kill -KILL`; ver [cenarios.md](cenarios.md#r1--worker-morto-no-meio-do-processamento)), t_kill. Guarda as mensagens de `unacked` no instante da falha e quando cada uma saiu de `unacked_index`; a última a sair é a órfã (t_restore). No A, a recuperação é a volta do contêiner do Job. No fim, restaura o timeout padrão |
   | R1a | ~10% processados | `kubectl delete pod` (SIGTERM), t_kill, e t_pod_removido quando o pod some (duração do desligamento) |
   | R3 | ~25% processados | `scale sts opensearch --replicas=0` (t_down), 60 s, `--replicas=1` (t_up_cmd) e espera o pod pronto (t_ready). Indisponibilidade real = t_ready − t_down |
   | E2 | — | sem carga: janela de 30 min. No A, o CronJob `data-processing` é reativado durante a janela e suspenso de novo no fim |

8. **Validade.** A execução é marcada inválida se o timeout estourou, se a falha do cenário não chegou a ser injetada, se um pod de infraestrutura reiniciou, foi recriado ou sumiu (menos o OpenSearch no R3), se um pod rodou com outro *digest*, se o export falhou, ou se as séries têm buracos de mais de 1 min (`registro_execucao.py lacunas`: `up` do Pushgateway e do `redis-queue`, e as séries do kube-state-metrics e do cAdvisor). A interferência externa continua sendo julgada por quem conduz, no diário.
9. **Export** (D4) ao fim de cada execução. No Revoada, pelo pod `export-metrics`, que o script cria se faltar.
10. **Registro:** a entrada no diário de bordo, gerada a partir do `.json`. Uma execução inválida tem os arquivos movidos para `invalidas/`.

Interrompido (Ctrl+C) ou com erro depois de a carga começar, o script restaura o `QUEUE_VISIBILITY_TIMEOUT` e a suspensão do CronJob, marca a execução como inválida e a registra.

### Arquivos

Em `resultados/<cenario>/<modo>/` (no piloto, `resultados/piloto/...`):

| Arquivo | Conteúdo |
|---|---|
| `<run>.json` | parâmetros, commits, *digest* (o do cluster e o de cada pod que rodou), máquina local, checklist, instantes (`instantes`, em Unix, e `instantes_iso`), `falha`, infraestrutura no início e no fim, `validade` (`valida`, `motivos`, `anomalias`), `lacunas`, `carga` (registro do simulador, com os ids dos corrompidos) e a chave `export` do D4 |
| `<run>.csv` | séries do Prometheus ([exportacao.md](exportacao.md)) |
| `<run>.log` | saída do `run_experiment.sh` |
| `<run>-postgres.csv` | contagem do Postgres a cada 15 s |
| `<run>-carga.json`, `<run>-carga.csv` | registro do simulador (um diário por linha) |

Instantes observados pelo script, além dos do protocolo: `t_carga_inicio`, `t_carga_fim`, `t_rep1_obs` e `t_doc1_obs` (resolução de ~5 s; a análise usa o Prometheus e o Postgres), `t_job_fim` (A) e `t_fim` (fim da exportação).
