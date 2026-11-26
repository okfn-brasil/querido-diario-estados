# Diário de bordo dos experimentos

Registro de **todas** as execuções da Parte E, inclusive o piloto e as inválidas, feito no momento em que cada uma roda. As regras estão no [protocolo](../docs/avaliacao/protocolo.md) e os cenários, em [cenarios.md](../docs/avaliacao/cenarios.md).

Uma entrada por execução, da mais antiga para a mais nova. Entradas não são apagadas nem reescritas depois: uma correção vira uma nota datada no fim da própria entrada.

## Modelo

Copie o bloco abaixo para o fim do arquivo e preencha.

```markdown
### <cenario>-<modo>-<k> · AAAA-MM-DD HH:MM

- **Campanha:** K | R
- **Tipo:** piloto | válida | inválida
- **Commits:** data-processing `<sha>` · deployment `<sha>` · estados `<sha>`
- **Imagem:** `querido-diario-data-processing@sha256:<digest>`
- **Parâmetros:** N = <n>, *seed* = <k>, teto = <teto>, outros do cenário (ex.: `QUEUE_VISIBILITY_TIMEOUT` = 300 s)
- **Instantes:** t0 = <ISO 8601>; falhas injetadas (t_kill, t_down, t_ready...) = <...>; fim = <...>
- **Resultado rápido:** pendentes no fim = <n>; na DLQ = <n>; duração = <min>
- **Arquivos:** `resultados/<cenario>/<modo>/<run>.{csv,json,log}`
- **Anomalias:** <o que fugiu do esperado, ou "nenhuma">
- **Validade:** <se inválida, qual critério do protocolo e por quê; se a anomalia é da arquitetura (resultado) ou do ambiente (inválida)>
```

## Execuções

### VAL-A-1 e VAL-C-1 · 2026-11-24 21:30 (BRT)

- **Campanha:** R, **fora da campanha** (validação ponta a ponta da E-0, #55; não entra em nenhuma comparação)
- **Tipo:** validação do ambiente
- **Commits:** data-processing `ae4abc3` · deployment `a4ec0c9` (PR #67) · estados `5fb39e1`
- **Imagem:** `querido-diario-data-processing@sha256:addd0fcb4255e8a0a9fb03f1fe47c61e5e78de8200677ea5769e4af136c3a010` (`:tcc-fila`); Tika `@sha256:d72830f9cedb8c02c5b2d1052634f1ff4baa3cd2ca1f868d57f8970136b8a36b`
- **Ambiente:** Revoada, k3s `v1.33.6+k3s1`, namespace `querido-diario-tcc`. O token do namespace não lê nós, então hardware e carga dos nós ficam para registrar com o administrador (o OpenSearch subiu no nó `hipo2`)
- **Parâmetros:** `burst`, N = 20, *seed* = 1; teto = 6 no `ScaledObject`, mas os workers foram escalados à mão para 2 (ver anomalias); DLQ com `--total 4 --corrupt 1`
- **Instantes (UTC):** A: inserção 00:32:53–00:37:40, Job `data-processing` em ~44 s. C: inserção 00:39:10–00:43:58, workers escalados às 00:44:40, fila vazia às 00:45:07; corrompido inserido às 00:50:49
- **Resultado rápido:** A: 20/20 `processed=true` e 20 no índice. C: 20/20 processados; o corrompido (id 42) em `qd:extraction:dead` com Tika HTTP 422, os outros 3 processados. `--cleanup` deixou 0 diários
- **Arquivos:** `VAL-C-1.{csv,json}` gerados pelo `export_metrics.py` no pod `export-metrics` (passo 30 s, 1558 linhas; séries vazias: só `oomkilled`); não versionados, por serem de validação
- **Anomalias:** o operador do KEDA do Revoada não reconciliou o `ScaledObject` (sem finalizer, status ou HPA), então o escalonamento 0 → teto → 0 não foi validado. O OpenSearch não subiu no Ceph sem `fsGroup: 1000` (corrigido no overlay)
- **Validade:** fora da campanha. Os modos B e C da campanha R dependem de o KEDA funcionar no namespace
- **Nota (25/11/2026):** causa do KEDA: o operador do Revoada só observa objetos com o label `keda=enabled` (corrigido no deployment#68; ver VAL-C-2). Hardware informado pelo administrador: os pods só caem na `hipo2` ou na `hipo3` (Xeon Gold 5418Y, 48 núcleos com HT, 512 GB de RAM); os outros nós têm o taint `control-plane:NoSchedule`. Todos os pods desta validação rodaram na `hipo2`

### VAL-C-2 · 2026-11-25 13:43 (BRT)

- **Campanha:** R, **fora da campanha** (validação do KEDA, #58; não entra em nenhuma comparação)
- **Tipo:** validação do ambiente
- **Commits:** data-processing `ae4abc3` · deployment `9c92878` (PR #68) · estados `c385c01`
- **Imagem:** `querido-diario-data-processing@sha256:addd0fcb4255e8a0a9fb03f1fe47c61e5e78de8200677ea5769e4af136c3a010` (`:tcc-fila`)
- **Ambiente:** Revoada, k3s `v1.33.6+k3s1`, todos os pods na `hipo2` (Xeon Gold 5418Y, 48 núcleos com HT, 512 GB). `kubectl top nodes` no início: `hipo2` com 18,9 núcleos (19%) e 86,6 GiB (16%) em uso por outras cargas do cluster
- **Parâmetros:** `burst`, *seed* = 1, teto = 6, `ScaledObject` com o label `keda=enabled`; duas cargas: N = 30 (`--duration 30s`) e N = 60 (`--duration 60s --workers 8`); processamento disparado por Job do `enqueue-extraction`
- **Instantes (UTC):** N = 30: enqueue às 16:43:10, fila vazia às 16:43:49, réplicas em 0 às 16:45:56. N = 60: enqueue às 16:49:48, fila vazia às 16:50:32, réplicas em 0 às 16:52:30
- **Resultado rápido:** N = 30: 0 → 5 → 1 → 0 réplicas, 30/30 processados. N = 60: 0 → 5 → 6 (teto) → 0 réplicas, 60/60 processados em ~40 s. Volta a 0 em ~2 min (`cooldownPeriod` de 120 s). DLQ vazia; `--cleanup` deixou 0 diários
- **Arquivos:** nenhum (sem `export_metrics.py` nesta validação)
- **Anomalias:** a inserção do simulador ficou mais de 30 s atrás da agenda nas duas cargas (`--duration` curto para o N). Na `hipo2`, cada diário da amostra leva bem menos que no kind, então N = 30 esvazia a fila antes de o HPA chegar ao teto
- **Validade:** fora da campanha. O escalonamento 0 → teto → 0 da #55 está validado

### E1-A-piloto · 2026-11-25 02:34

- **Campanha:** K
- **Tipo:** piloto
- **Commits:** data-processing `ae4abc3` (main-estados) · deployment `e704158` (main-estados) · estados `fa08a37` (tcc/e2-execucao)
- **Imagem:** `sha256:fc8e0e5a8dad58477e531cd0d9cb4566bc81db43c352f430230217cf9ea95c6b`
- **Parâmetros:** N = 300, *seed* = 1, timeout = 7200 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-25T05:36:33+00:00; t_carga_fim = 2026-11-25T05:41:35+00:00; t0 = 2026-11-25T05:41:35+00:00; t_vazio = 2026-11-25T05:44:52+00:00; t_job_fim = 2026-11-25T05:46:43+00:00; t_fim = 2026-11-25T05:47:28+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = —; duração = 3.3 min até t_vazio
- **Arquivos:** `resultados/K/piloto/E1/A/E1-A-piloto.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** piloto, fora dos resultados

### E1-B-piloto · 2026-11-25 02:47

- **Campanha:** K
- **Tipo:** piloto
- **Commits:** data-processing `ae4abc3` (main-estados) · deployment `e704158` (main-estados) · estados `fa08a37` (tcc/e2-execucao)
- **Imagem:** `sha256:fc8e0e5a8dad58477e531cd0d9cb4566bc81db43c352f430230217cf9ea95c6b`
- **Parâmetros:** N = 300, *seed* = 1, teto = 1, timeout = 7200 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-25T05:50:24+00:00; t_carga_fim = 2026-11-25T05:55:25+00:00; t0 = 2026-11-25T05:55:25+00:00; t_vazio = 2026-11-25T05:58:51+00:00; t_fim = 2026-11-25T05:59:36+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 3.4 min até t_vazio
- **Arquivos:** `resultados/K/piloto/E1/B/E1-B-piloto.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** piloto, fora dos resultados

### E1-C-piloto · 2026-11-25 02:59

- **Campanha:** K
- **Tipo:** piloto
- **Commits:** data-processing `ae4abc3` (main-estados) · deployment `e704158` (main-estados) · estados `fa08a37` (tcc/e2-execucao)
- **Imagem:** `sha256:fc8e0e5a8dad58477e531cd0d9cb4566bc81db43c352f430230217cf9ea95c6b`
- **Parâmetros:** N = 300, *seed* = 1, teto = 2, timeout = 7200 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-25T06:01:56+00:00; t_carga_fim = 2026-11-25T06:06:56+00:00; t0 = 2026-11-25T06:06:56+00:00; t_vazio = 2026-11-25T06:09:19+00:00; t_zero = 2026-11-25T06:11:14+00:00; t_fim = 2026-11-25T06:11:14+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 2.4 min até t_vazio
- **Arquivos:** `resultados/K/piloto/E1/C/E1-C-piloto.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** piloto, fora dos resultados

### Ajustes depois do piloto da campanha K · 2026-11-25

- **Métricas do modo A:** no E1-A-piloto, as séries `qd_*` vieram vazias, sem que o script percebesse. Causa (reproduzida com os logs das duas tentativas): o Job extrai os 300 diários e falha nos temas com HTTP 429 do OpenSearch (circuit breaker, heap de 512 MiB no kind); o `finally` envia as métricas, o `restartPolicy: OnFailure` sobe outra tentativa, que não acha pendentes e enviava o registro vazio com PUT, apagando o grupo. O mesmo ocorreu no R1-A e no E2-A dos testes de 24/11. Correção: `pushadd_to_gateway` (POST) em okfn-brasil/querido-diario-data-processing#133. A imagem `tcc-fila` foi refeita a partir da anterior trocando só `monitoring/metrics.py` (o resto do código é idêntico ao `ae4abc3`; a anterior ficou como `tcc-fila-ae4abc3`). Novo *digest*: `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`. Os tempos do piloto não mudam (a extração é a mesma); só o push mudou
- **`run_experiment.sh`:** no modo A, o checklist apaga o grupo `job=data-processing` do Pushgateway (só no kind); o reinício do contêiner do Job vira anomalia, com os logs das tentativas em `<run>-job.log`; o A sem séries `qd_*` é inválido (fora do R1 e do R1a). Conferido num E1-A de validação (fora da campanha): Job reiniciou como antes, 300 observações no Pushgateway, execução válida
- **Parâmetros fixados:** `IMAGEM_DIGEST` acima; `TIMEOUT_S` = 3 × 197 s = 591 s; N do R1 = 1500 (com 300, a fila esvaziaria em 142–206 s, antes de `visibility_timeout` + 2 min), com timeout próprio de 3300 s; máximo de `qd_gazette_processing_seconds` < 10 s, bem abaixo do `visibility_timeout` de 300 s do R1; orçamento revisado para ~13 h
- **Memória:** mínimo de 827 MiB disponíveis no piloto (E1-C, 2 workers + Tika), swap até 2,8 GiB


### E1-A-piloto · 2026-11-25 16:39

- **Campanha:** R
- **Tipo:** piloto
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `863ac0d` (tcc/e2-execucao)
- **Imagem:** —
- **Parâmetros:** N = 500, *seed* = 1, timeout = 7200 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-25T19:42:25+00:00; t_carga_fim = 2026-11-25T20:04:37+00:00; t0 = 2026-11-25T20:04:37+00:00; t_vazio = 2026-11-25T20:22:36+00:00
- **Resultado rápido:** pendentes no fim = — (— fora da DLQ); na DLQ = —; duração = 18.0 min até t_vazio
- **Arquivos:** `resultados/R/piloto/E1/A/E1-A-piloto.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** piloto, fora dos resultados (critérios: erro do run_experiment.sh (código 130))

### E1-A-pilotob · 2026-11-25 17:54

- **Campanha:** R
- **Tipo:** piloto
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `faff6fd` (tcc/revoada-opensearch-memoria) · estados `863ac0d` (tcc/e2-execucao)
- **Imagem:** —
- **Parâmetros:** N = 500, *seed* = 1, timeout = 7200 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-25T20:56:50+00:00
- **Resultado rápido:** pendentes no fim = — (— fora da DLQ); na DLQ = —; duração = —
- **Arquivos:** `resultados/R/piloto/E1/A/E1-A-pilotob.{csv,json,log}`
- **Anomalias:** querido-diario-deployment na branch 'tcc/revoada-opensearch-memoria', não em main-estados
- **Validade:** piloto, fora dos resultados (critérios: erro do run_experiment.sh (código 130))

### E1-A-pilotoc · 2026-11-25 18:10

- **Campanha:** R
- **Tipo:** piloto
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `faff6fd` (tcc/revoada-opensearch-memoria) · estados `04ed0eb` (tcc/e2-execucao)
- **Imagem:** —
- **Parâmetros:** N = 500, *seed* = 1, timeout = 7200 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-25T21:12:26+00:00; t_carga_fim = 2026-11-25T21:17:26+00:00; t0 = 2026-11-25T21:17:27+00:00; t_vazio = 2026-11-25T21:31:45+00:00; t_job_fim = 2026-11-25T21:38:02+00:00; t_fim = 2026-11-25T21:39:18+00:00
- **Resultado rápido:** pendentes no fim = — (— fora da DLQ); na DLQ = —; duração = 14.3 min até t_vazio
- **Arquivos:** `resultados/R/piloto/E1/A/E1-A-pilotoc.{csv,json,log}`
- **Anomalias:** querido-diario-deployment na branch 'tcc/revoada-opensearch-memoria', não em main-estados
- **Validade:** piloto, fora dos resultados (critérios: erro do run_experiment.sh (linha 1210: [[ -n $PF_PID ]]))

### E1-A-pilotod · 2026-11-25 18:39

- **Campanha:** R
- **Tipo:** piloto
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `faff6fd` (tcc/revoada-opensearch-memoria) · estados `04ed0eb` (tcc/e2-execucao)
- **Imagem:** —
- **Parâmetros:** N = 500, *seed* = 1, timeout = 7200 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-25T21:41:42+00:00; t_carga_fim = 2026-11-25T21:46:43+00:00; t0 = 2026-11-25T21:46:49+00:00; t_vazio = 2026-11-25T22:01:06+00:00; t_job_fim = 2026-11-25T22:07:16+00:00; t_fim = 2026-11-25T22:08:32+00:00
- **Resultado rápido:** pendentes no fim = — (— fora da DLQ); na DLQ = —; duração = 14.3 min até t_vazio
- **Arquivos:** `resultados/R/piloto/E1/A/E1-A-pilotod.{csv,json,log}`
- **Anomalias:** querido-diario-deployment na branch 'tcc/revoada-opensearch-memoria', não em main-estados
- **Validade:** piloto, fora dos resultados (critérios: erro do run_experiment.sh (linha 1210: [[ -n $PF_PID ]]))

### E1-A-pilotoe · 2026-11-25 19:08

- **Campanha:** R
- **Tipo:** piloto
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `faff6fd` (tcc/revoada-opensearch-memoria) · estados `04ed0eb` (tcc/e2-execucao)
- **Imagem:** —
- **Parâmetros:** N = 500, *seed* = 1, timeout = 7200 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-25T22:11:07+00:00
- **Resultado rápido:** pendentes no fim = — (— fora da DLQ); na DLQ = —; duração = —
- **Arquivos:** `resultados/R/piloto/E1/A/E1-A-pilotoe.{csv,json,log}`
- **Anomalias:** querido-diario-deployment na branch 'tcc/revoada-opensearch-memoria', não em main-estados
- **Validade:** piloto, fora dos resultados (critérios: erro do run_experiment.sh (código 130))

### E1-A-pilotof · 2026-11-25 19:14

- **Campanha:** R
- **Tipo:** piloto
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `faff6fd` (tcc/revoada-opensearch-memoria) · estados `ac5a208` (tcc/e2-execucao)
- **Imagem:** —
- **Parâmetros:** N = 500, *seed* = 1, timeout = 7200 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-25T22:16:55+00:00; t_carga_fim = 2026-11-25T22:21:56+00:00; t0 = 2026-11-25T22:21:57+00:00; t_vazio = 2026-11-25T22:36:39+00:00; t_job_fim = 2026-11-25T22:37:09+00:00; t_fim = 2026-11-25T22:38:25+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = —; duração = 14.7 min até t_vazio
- **Arquivos:** `resultados/R/piloto/E1/A/E1-A-pilotof.{csv,json,log}`
- **Anomalias:** querido-diario-deployment na branch 'tcc/revoada-opensearch-memoria', não em main-estados; o contêiner do Job reiniciou: exp-e1-a-pilotof-1795645317-whlxg: 1 reinício(s), última falha com código ? (?) (ver E1-A-pilotof-job.log)
- **Validade:** piloto, fora dos resultados (critérios: sem séries qd_* do Pushgateway: o push do Job não chegou ou veio vazio (ver E1-A-pilotof-job.log))

### E1-B-piloto · 2026-11-25 19:38

- **Campanha:** R
- **Tipo:** piloto
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `faff6fd` (tcc/revoada-opensearch-memoria) · estados `ac5a208` (tcc/e2-execucao)
- **Imagem:** —
- **Parâmetros:** N = 500, *seed* = 1, teto = 1, timeout = 7200 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-25T22:42:12+00:00
- **Resultado rápido:** pendentes no fim = — (— fora da DLQ); na DLQ = —; duração = —
- **Arquivos:** `resultados/R/piloto/E1/B/E1-B-piloto.{csv,json,log}`
- **Anomalias:** querido-diario-deployment na branch 'tcc/revoada-opensearch-memoria', não em main-estados
- **Validade:** piloto, fora dos resultados (critérios: erro do run_experiment.sh (código 130))

### E1-A-pilotog · 2026-11-25 19:46

- **Campanha:** R
- **Tipo:** piloto
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `275a847` (tcc/revoada-opensearch-memoria) · estados `c4c0493` (tcc/e2-execucao)
- **Imagem:** —
- **Parâmetros:** N = 500, *seed* = 1, timeout = 7200 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-25T22:50:00+00:00; t_carga_fim = 2026-11-25T22:55:02+00:00; t0 = 2026-11-25T22:55:03+00:00; t_vazio = 2026-11-25T23:08:43+00:00; t_job_fim = 2026-11-25T23:16:01+00:00; t_fim = 2026-11-25T23:17:18+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = —; duração = 13.7 min até t_vazio
- **Arquivos:** `resultados/R/piloto/E1/A/E1-A-pilotog.{csv,json,log}`
- **Anomalias:** querido-diario-deployment na branch 'tcc/revoada-opensearch-memoria', não em main-estados
- **Validade:** piloto, fora dos resultados

### E1-A-1 · 2026-11-25 20:59

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `65b09d0` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 300, *seed* = 1, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T00:01:49+00:00; t_carga_fim = 2026-11-26T00:06:50+00:00; t0 = 2026-11-26T00:06:50+00:00; t_vazio = 2026-11-26T00:10:07+00:00; t_job_fim = 2026-11-26T00:10:30+00:00; t_fim = 2026-11-26T00:11:16+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = —; duração = 3.3 min até t_vazio
- **Arquivos:** `resultados/K/E1/A/E1-A-1.{csv,json,log}`
- **Anomalias:** o contêiner do Job reiniciou: exp-e1-a-1-1795651610-27rsj: 1 reinício(s), última falha com código ? (?) (ver E1-A-1-job.log)
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### E1-B-1 · 2026-11-25 21:11

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `65b09d0` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 300, *seed* = 1, teto = 1, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T00:14:12+00:00; t_carga_fim = 2026-11-26T00:19:13+00:00; t0 = 2026-11-26T00:19:13+00:00; t_vazio = 2026-11-26T00:22:35+00:00; t_fim = 2026-11-26T00:23:20+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 3.4 min até t_vazio
- **Arquivos:** `resultados/K/E1/B/E1-B-1.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### E1-C-1 · 2026-11-25 21:23

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `65b09d0` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 300, *seed* = 1, teto = 2, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T00:25:40+00:00; t_carga_fim = 2026-11-26T00:30:40+00:00; t0 = 2026-11-26T00:30:40+00:00; t_vazio = 2026-11-26T00:33:01+00:00; t_zero = 2026-11-26T00:34:57+00:00; t_fim = 2026-11-26T00:34:57+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 2.3 min até t_vazio
- **Arquivos:** `resultados/K/E1/C/E1-C-1.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### E1-B-2 · 2026-11-25 21:35

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `65b09d0` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 300, *seed* = 2, teto = 1, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T00:37:22+00:00; t_carga_fim = 2026-11-26T00:42:23+00:00; t0 = 2026-11-26T00:42:23+00:00; t_vazio = 2026-11-26T00:45:55+00:00; t_fim = 2026-11-26T00:46:40+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 3.5 min até t_vazio
- **Arquivos:** `resultados/K/E1/B/E1-B-2.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### E1-C-2 · 2026-11-25 21:46

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `65b09d0` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 300, *seed* = 2, teto = 2, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T00:48:59+00:00; t_carga_fim = 2026-11-26T00:54:00+00:00; t0 = 2026-11-26T00:54:00+00:00; t_vazio = 2026-11-26T00:56:21+00:00; t_zero = 2026-11-26T00:58:19+00:00; t_fim = 2026-11-26T00:58:19+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 2.3 min até t_vazio
- **Arquivos:** `resultados/K/E1/C/E1-C-2.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### E1-A-2 · 2026-11-25 21:58

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `65b09d0` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 300, *seed* = 2, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T01:00:51+00:00; t_carga_fim = 2026-11-26T01:05:52+00:00; t0 = 2026-11-26T01:05:52+00:00; t_vazio = 2026-11-26T01:09:14+00:00; t_job_fim = 2026-11-26T01:12:51+00:00; t_fim = 2026-11-26T01:13:36+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = —; duração = 3.4 min até t_vazio
- **Arquivos:** `resultados/K/E1/A/E1-A-2.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### Parada no E1-C-3 · 2026-11-25 22:14

- **O que houve:** o checklist do E1-C-3 reprovou o item `modo` (`ScaledObject min=0 max=2 Ready=False`): o ScaledObject tinha sido recriado ao aplicar o modo C 1 s antes, e o KEDA ainda reconciliava (`Ready=True` segundos depois). A execução não rodou (código 1) e a campanha parou, como previsto
- **Correção:** `a3b81f3`, o `aplicar_modo` espera até 120 s pelo `Ready` nos modos B e C. Não muda o que é medido ([Desvios do protocolo](../docs/avaliacao/protocolo.md#desvios-do-protocolo))
- **Retomada:** `run_campaign.sh K E1 R1` às 22:19, a partir do E1-C-3; as 6 execuções válidas anteriores foram mantidas

### E1-C-3 · 2026-11-25 22:19

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `a3b81f3` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 300, *seed* = 3, teto = 2, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T01:22:00+00:00; t_carga_fim = 2026-11-26T01:27:01+00:00; t0 = 2026-11-26T01:27:01+00:00; t_vazio = 2026-11-26T01:29:47+00:00; t_zero = 2026-11-26T01:31:37+00:00; t_fim = 2026-11-26T01:31:37+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 2.8 min até t_vazio
- **Arquivos:** `resultados/K/E1/C/E1-C-3.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### E1-A-3 · 2026-11-25 22:31

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `a3b81f3` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 300, *seed* = 3, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T01:34:09+00:00; t_carga_fim = 2026-11-26T01:39:10+00:00; t0 = 2026-11-26T01:39:10+00:00; t_vazio = 2026-11-26T01:43:05+00:00; t_job_fim = 2026-11-26T01:46:55+00:00; t_fim = 2026-11-26T01:47:41+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = —; duração = 3.9 min até t_vazio
- **Arquivos:** `resultados/K/E1/A/E1-A-3.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### E1-B-3 · 2026-11-25 22:47

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `a3b81f3` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 300, *seed* = 3, teto = 1, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T01:51:13+00:00; t_carga_fim = 2026-11-26T01:56:14+00:00; t0 = 2026-11-26T01:56:14+00:00; t_vazio = 2026-11-26T02:00:24+00:00; t_fim = 2026-11-26T02:01:09+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 4.2 min até t_vazio
- **Arquivos:** `resultados/K/E1/B/E1-B-3.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1-A-1 · 2026-11-25 23:01

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `a3b81f3` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 1500, *seed* = 1, timeout = 3300 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T02:03:41+00:00; t_carga_fim = 2026-11-26T02:08:43+00:00; t0 = 2026-11-26T02:08:43+00:00; t_kill = 2026-11-26T02:10:38+00:00; t_vazio = 2026-11-26T02:25:43+00:00; t_job_fim = 2026-11-26T02:29:28+00:00; t_fim = 2026-11-26T02:30:13+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = —; duração = 17.0 min até t_vazio
- **Arquivos:** `resultados/K/R1/A/R1-A-1.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1-B-1 · 2026-11-25 23:30

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `a3b81f3` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 1500, *seed* = 1, teto = 1, `QUEUE_VISIBILITY_TIMEOUT` = 300 s, timeout = 3300 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T02:33:09+00:00; t_carga_fim = 2026-11-26T02:38:10+00:00; t0 = 2026-11-26T02:38:10+00:00; t_kill = 2026-11-26T02:40:13+00:00; t_restore = 2026-11-26T02:46:51+00:00; t_vazio = 2026-11-26T02:56:25+00:00; t_fim = 2026-11-26T02:57:10+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 18.2 min até t_vazio
- **Arquivos:** `resultados/K/R1/B/R1-B-1.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1-C-1 · 2026-11-25 23:57

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `a3b81f3` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 1500, *seed* = 1, teto = 2, `QUEUE_VISIBILITY_TIMEOUT` = 300 s, timeout = 3300 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T02:59:34+00:00; t_carga_fim = 2026-11-26T03:04:35+00:00; t0 = 2026-11-26T03:04:35+00:00; t_kill = 2026-11-26T03:06:11+00:00; t_restore = 2026-11-26T03:11:27+00:00; t_vazio = 2026-11-26T03:15:59+00:00; t_zero = 2026-11-26T03:17:49+00:00; t_fim = 2026-11-26T03:17:49+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 11.4 min até t_vazio
- **Arquivos:** `resultados/K/R1/C/R1-C-1.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1-B-2 · 2026-11-26 00:17

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `a3b81f3` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 1500, *seed* = 2, teto = 1, `QUEUE_VISIBILITY_TIMEOUT` = 300 s, timeout = 3300 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T03:20:27+00:00; t_carga_fim = 2026-11-26T03:25:29+00:00; t0 = 2026-11-26T03:25:29+00:00; t_kill = 2026-11-26T03:27:26+00:00; t_restore = 2026-11-26T03:34:03+00:00; t_vazio = 2026-11-26T03:43:40+00:00; t_fim = 2026-11-26T03:44:25+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 18.2 min até t_vazio
- **Arquivos:** `resultados/K/R1/B/R1-B-2.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1-C-2 · 2026-11-26 00:44

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `a3b81f3` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 1500, *seed* = 2, teto = 2, `QUEUE_VISIBILITY_TIMEOUT` = 300 s, timeout = 3300 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T03:46:52+00:00; t_carga_fim = 2026-11-26T03:51:54+00:00; t0 = 2026-11-26T03:51:54+00:00; t_kill = 2026-11-26T03:53:27+00:00; t_restore = 2026-11-26T03:58:46+00:00; t_vazio = 2026-11-26T04:03:10+00:00; t_zero = 2026-11-26T04:05:06+00:00; t_fim = 2026-11-26T04:05:06+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 11.3 min até t_vazio
- **Arquivos:** `resultados/K/R1/C/R1-C-2.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1-A-2 · 2026-11-26 01:05

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `a3b81f3` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 1500, *seed* = 2, timeout = 3300 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T04:07:42+00:00; t_carga_fim = 2026-11-26T04:12:44+00:00; t0 = 2026-11-26T04:12:44+00:00; t_kill = 2026-11-26T04:14:35+00:00; t_vazio = 2026-11-26T04:30:14+00:00; t_job_fim = 2026-11-26T04:30:41+00:00; t_fim = 2026-11-26T04:31:26+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = —; duração = 17.5 min até t_vazio
- **Arquivos:** `resultados/K/R1/A/R1-A-2.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1-C-3 · 2026-11-26 01:31

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `a3b81f3` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 1500, *seed* = 3, teto = 2, `QUEUE_VISIBILITY_TIMEOUT` = 300 s, timeout = 3300 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T04:35:07+00:00; t_carga_fim = 2026-11-26T04:40:08+00:00; t0 = 2026-11-26T04:40:08+00:00; t_kill = 2026-11-26T04:41:34+00:00; t_restore = 2026-11-26T04:46:55+00:00; t_vazio = 2026-11-26T04:50:51+00:00; t_zero = 2026-11-26T04:52:49+00:00; t_fim = 2026-11-26T04:52:49+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 10.7 min até t_vazio
- **Arquivos:** `resultados/K/R1/C/R1-C-3.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1-A-3 · 2026-11-26 01:52

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `a3b81f3` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 1500, *seed* = 3, timeout = 3300 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T04:55:26+00:00; t_carga_fim = 2026-11-26T05:00:28+00:00; t0 = 2026-11-26T05:00:28+00:00; t_kill = 2026-11-26T05:02:14+00:00; t_vazio = 2026-11-26T05:17:22+00:00; t_job_fim = 2026-11-26T05:17:58+00:00; t_fim = 2026-11-26T05:18:44+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = —; duração = 16.9 min até t_vazio
- **Arquivos:** `resultados/K/R1/A/R1-A-3.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1-B-3 · 2026-11-26 02:18

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `a3b81f3` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 1500, *seed* = 3, teto = 1, `QUEUE_VISIBILITY_TIMEOUT` = 300 s, timeout = 3300 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T05:21:25+00:00; t_carga_fim = 2026-11-26T05:26:27+00:00; t0 = 2026-11-26T05:26:27+00:00; t_kill = 2026-11-26T05:28:18+00:00; t_restore = 2026-11-26T05:34:55+00:00; t_vazio = 2026-11-26T05:43:32+00:00; t_fim = 2026-11-26T05:44:17+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 17.1 min até t_vazio
- **Arquivos:** `resultados/K/R1/B/R1-B-3.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1a-A-1 · 2026-11-26 02:53

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 1, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T05:55:37+00:00; t_carga_fim = 2026-11-26T06:00:36+00:00; t0 = 2026-11-26T06:00:36+00:00; t_kill = 2026-11-26T06:00:48+00:00; t_pod_removido = 2026-11-26T06:01:19+00:00; t_vazio = 2026-11-26T06:01:49+00:00; t_job_fim = 2026-11-26T06:02:40+00:00; t_fim = 2026-11-26T06:03:25+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = —; duração = 1.2 min até t_vazio; desligamento = 31 s
- **Arquivos:** `resultados/K/R1a/A/R1a-A-1.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1a-B-1 · 2026-11-26 03:03

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 1, teto = 1, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T06:06:15+00:00; t_carga_fim = 2026-11-26T06:11:14+00:00; t0 = 2026-11-26T06:11:14+00:00; t_kill = 2026-11-26T06:11:27+00:00; t_pod_removido = 2026-11-26T06:11:30+00:00; t_vazio = 2026-11-26T06:12:33+00:00; t_fim = 2026-11-26T06:13:18+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 1.3 min até t_vazio; desligamento = 3 s
- **Arquivos:** `resultados/K/R1a/B/R1a-B-1.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1a-C-1 · 2026-11-26 03:13

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 1, teto = 2, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T06:15:38+00:00; t_carga_fim = 2026-11-26T06:20:37+00:00; t0 = 2026-11-26T06:20:37+00:00; t_kill = 2026-11-26T06:21:03+00:00; t_pod_removido = 2026-11-26T06:21:07+00:00; t_vazio = 2026-11-26T06:21:44+00:00; t_zero = 2026-11-26T06:23:34+00:00; t_fim = 2026-11-26T06:23:34+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 1.1 min até t_vazio; desligamento = 5 s
- **Arquivos:** `resultados/K/R1a/C/R1a-C-1.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1a-B-2 · 2026-11-26 03:23

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 2, teto = 1, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T06:25:59+00:00; t_carga_fim = 2026-11-26T06:30:57+00:00; t0 = 2026-11-26T06:30:57+00:00; t_kill = 2026-11-26T06:31:12+00:00; t_pod_removido = 2026-11-26T06:31:15+00:00; t_vazio = 2026-11-26T06:32:18+00:00; t_fim = 2026-11-26T06:33:03+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 1.3 min até t_vazio; desligamento = 4 s
- **Arquivos:** `resultados/K/R1a/B/R1a-B-2.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1a-C-2 · 2026-11-26 03:33

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 2, teto = 2, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T06:35:22+00:00; t_carga_fim = 2026-11-26T06:40:20+00:00; t0 = 2026-11-26T06:40:20+00:00; t_kill = 2026-11-26T06:40:47+00:00; t_pod_removido = 2026-11-26T06:40:52+00:00; t_vazio = 2026-11-26T06:41:22+00:00; t_zero = 2026-11-26T06:43:20+00:00; t_fim = 2026-11-26T06:43:20+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 1.0 min até t_vazio; desligamento = 5 s
- **Arquivos:** `resultados/K/R1a/C/R1a-C-2.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1a-A-2 · 2026-11-26 03:43

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 2, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T06:45:52+00:00; t_carga_fim = 2026-11-26T06:50:51+00:00; t0 = 2026-11-26T06:50:51+00:00; t_kill = 2026-11-26T06:51:03+00:00; t_pod_removido = 2026-11-26T06:51:33+00:00; t_vazio = 2026-11-26T06:51:57+00:00; t_job_fim = 2026-11-26T06:52:53+00:00; t_fim = 2026-11-26T06:53:39+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = —; duração = 1.1 min até t_vazio; desligamento = 31 s
- **Arquivos:** `resultados/K/R1a/A/R1a-A-2.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1a-C-3 · 2026-11-26 03:53

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 3, teto = 2, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T06:57:10+00:00; t_carga_fim = 2026-11-26T07:02:09+00:00; t0 = 2026-11-26T07:02:09+00:00; t_kill = 2026-11-26T07:02:40+00:00; t_pod_removido = 2026-11-26T07:02:45+00:00; t_vazio = 2026-11-26T07:03:29+00:00; t_zero = 2026-11-26T07:05:20+00:00; t_fim = 2026-11-26T07:05:20+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 1.3 min até t_vazio; desligamento = 5 s
- **Arquivos:** `resultados/K/R1a/C/R1a-C-3.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1a-A-3 · 2026-11-26 04:05

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 3, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T07:07:52+00:00; t_carga_fim = 2026-11-26T07:12:51+00:00; t0 = 2026-11-26T07:12:51+00:00; t_kill = 2026-11-26T07:13:04+00:00; t_pod_removido = 2026-11-26T07:13:35+00:00; t_vazio = 2026-11-26T07:14:10+00:00; t_job_fim = 2026-11-26T07:15:09+00:00; t_fim = 2026-11-26T07:15:54+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = —; duração = 1.3 min até t_vazio; desligamento = 31 s
- **Arquivos:** `resultados/K/R1a/A/R1a-A-3.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R1a-B-3 · 2026-11-26 04:15

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 3, teto = 1, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T07:19:15+00:00; t_carga_fim = 2026-11-26T07:24:14+00:00; t0 = 2026-11-26T07:24:14+00:00; t_kill = 2026-11-26T07:24:33+00:00; t_pod_removido = 2026-11-26T07:24:38+00:00; t_vazio = 2026-11-26T07:25:50+00:00; t_fim = 2026-11-26T07:26:35+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 1.6 min até t_vazio; desligamento = 5 s
- **Arquivos:** `resultados/K/R1a/B/R1a-B-3.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R2-A-1 · 2026-11-26 04:26

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 1, corrompidos = 10, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T07:29:08+00:00; t_carga_fim = 2026-11-26T07:34:07+00:00; t0 = 2026-11-26T07:34:07+00:00; t_vazio = 2026-11-26T07:35:07+00:00; t_job_fim = 2026-11-26T07:36:12+00:00; t_fim = 2026-11-26T07:36:57+00:00
- **Resultado rápido:** pendentes no fim = 10 (10 fora da DLQ); na DLQ = —; duração = 1.0 min até t_vazio
- **Arquivos:** `resultados/K/R2/A/R2-A-1.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R2-B-1 · 2026-11-26 04:36

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 1, teto = 1, corrompidos = 10, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T07:39:38+00:00; t_carga_fim = 2026-11-26T07:44:37+00:00; t0 = 2026-11-26T07:44:37+00:00; t_vazio = 2026-11-26T07:45:40+00:00; t_fim = 2026-11-26T07:46:26+00:00
- **Resultado rápido:** pendentes no fim = 10 (0 fora da DLQ); na DLQ = 10; duração = 1.1 min até t_vazio
- **Arquivos:** `resultados/K/R2/B/R2-B-1.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R2-C-1 · 2026-11-26 04:46

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 1, teto = 2, corrompidos = 10, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T07:48:44+00:00; t_carga_fim = 2026-11-26T07:53:43+00:00; t0 = 2026-11-26T07:53:43+00:00; t_vazio = 2026-11-26T07:54:43+00:00; t_zero = 2026-11-26T07:56:41+00:00; t_fim = 2026-11-26T07:56:41+00:00
- **Resultado rápido:** pendentes no fim = 10 (0 fora da DLQ); na DLQ = 10; duração = 1.0 min até t_vazio
- **Arquivos:** `resultados/K/R2/C/R2-C-1.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R2-B-2 · 2026-11-26 04:56

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 2, teto = 1, corrompidos = 10, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T07:59:16+00:00; t_carga_fim = 2026-11-26T08:04:15+00:00; t0 = 2026-11-26T08:04:15+00:00; t_vazio = 2026-11-26T08:05:18+00:00; t_fim = 2026-11-26T08:06:03+00:00
- **Resultado rápido:** pendentes no fim = 10 (0 fora da DLQ); na DLQ = 10; duração = 1.1 min até t_vazio
- **Arquivos:** `resultados/K/R2/B/R2-B-2.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R2-C-2 · 2026-11-26 05:06

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 2, teto = 2, corrompidos = 10, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T08:08:22+00:00; t_carga_fim = 2026-11-26T08:13:21+00:00; t0 = 2026-11-26T08:13:21+00:00; t_vazio = 2026-11-26T08:14:20+00:00; t_zero = 2026-11-26T08:16:09+00:00; t_fim = 2026-11-26T08:16:09+00:00
- **Resultado rápido:** pendentes no fim = 10 (0 fora da DLQ); na DLQ = 10; duração = 1.0 min até t_vazio
- **Arquivos:** `resultados/K/R2/C/R2-C-2.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R2-A-2 · 2026-11-26 05:16

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 2, corrompidos = 10, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T08:18:40+00:00; t_carga_fim = 2026-11-26T08:23:39+00:00; t0 = 2026-11-26T08:23:39+00:00; t_vazio = 2026-11-26T08:24:40+00:00; t_job_fim = 2026-11-26T08:25:49+00:00; t_fim = 2026-11-26T08:26:34+00:00
- **Resultado rápido:** pendentes no fim = 10 (10 fora da DLQ); na DLQ = —; duração = 1.0 min até t_vazio
- **Arquivos:** `resultados/K/R2/A/R2-A-2.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R2-C-3 · 2026-11-26 05:26

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 3, teto = 2, corrompidos = 10, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T08:29:30+00:00; t_carga_fim = 2026-11-26T08:34:29+00:00; t0 = 2026-11-26T08:34:29+00:00; t_vazio = 2026-11-26T08:35:37+00:00; t_zero = 2026-11-26T08:37:25+00:00; t_fim = 2026-11-26T08:37:25+00:00
- **Resultado rápido:** pendentes no fim = 10 (0 fora da DLQ); na DLQ = 10; duração = 1.1 min até t_vazio
- **Arquivos:** `resultados/K/R2/C/R2-C-3.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R2-A-3 · 2026-11-26 05:37

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 3, corrompidos = 10, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T08:39:57+00:00; t_carga_fim = 2026-11-26T08:44:56+00:00; t0 = 2026-11-26T08:44:56+00:00; t_vazio = 2026-11-26T08:46:07+00:00; t_job_fim = 2026-11-26T08:47:18+00:00; t_fim = 2026-11-26T08:48:03+00:00
- **Resultado rápido:** pendentes no fim = 10 (10 fora da DLQ); na DLQ = —; duração = 1.2 min até t_vazio
- **Arquivos:** `resultados/K/R2/A/R2-A-3.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R2-B-3 · 2026-11-26 05:48

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 3, teto = 1, corrompidos = 10, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T08:51:44+00:00; t_carga_fim = 2026-11-26T08:56:42+00:00; t0 = 2026-11-26T08:56:43+00:00; t_vazio = 2026-11-26T08:58:04+00:00; t_fim = 2026-11-26T08:58:49+00:00
- **Resultado rápido:** pendentes no fim = 10 (0 fora da DLQ); na DLQ = 10; duração = 1.4 min até t_vazio
- **Arquivos:** `resultados/K/R2/B/R2-B-3.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R3-A-1 · 2026-11-26 05:58

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 1, indisponibilidade nominal = 60 s, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T09:01:20+00:00; t_carga_fim = 2026-11-26T09:06:19+00:00; t0 = 2026-11-26T09:06:19+00:00; t_down = 2026-11-26T09:06:42+00:00; t_up_cmd = 2026-11-26T09:07:42+00:00; t_ready = 2026-11-26T09:08:22+00:00; t_job2 = 2026-11-26T09:10:13+00:00; t_vazio = 2026-11-26T09:10:19+00:00; t_job_fim = 2026-11-26T09:10:35+00:00; t_fim = 2026-11-26T09:11:21+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = —; duração = 4.0 min até t_vazio; indisponibilidade real = 101 s
- **Arquivos:** `resultados/K/R3/A/R3-A-1.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R3-B-1 · 2026-11-26 06:11

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 1, teto = 1, indisponibilidade nominal = 60 s, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T09:14:37+00:00; t_carga_fim = 2026-11-26T09:19:35+00:00; t0 = 2026-11-26T09:19:35+00:00; t_down = 2026-11-26T09:19:59+00:00; t_up_cmd = 2026-11-26T09:20:59+00:00; t_ready = 2026-11-26T09:21:40+00:00; t_vazio = 2026-11-26T09:22:26+00:00; t_fim = 2026-11-26T09:23:11+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 2.8 min até t_vazio; indisponibilidade real = 101 s
- **Arquivos:** `resultados/K/R3/B/R3-B-1.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R3-C-1 · 2026-11-26 06:23

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 1, teto = 2, indisponibilidade nominal = 60 s, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T09:25:30+00:00; t_carga_fim = 2026-11-26T09:30:29+00:00; t0 = 2026-11-26T09:30:29+00:00; t_down = 2026-11-26T09:31:00+00:00; t_up_cmd = 2026-11-26T09:32:00+00:00; t_ready = 2026-11-26T09:32:41+00:00; t_vazio = 2026-11-26T09:33:12+00:00; t_zero = 2026-11-26T09:35:10+00:00; t_fim = 2026-11-26T09:35:10+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 2.7 min até t_vazio; indisponibilidade real = 101 s
- **Arquivos:** `resultados/K/R3/C/R3-C-1.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R3-B-2 · 2026-11-26 06:35

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 2, teto = 1, indisponibilidade nominal = 60 s, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T09:37:49+00:00; t_carga_fim = 2026-11-26T09:42:48+00:00; t0 = 2026-11-26T09:42:48+00:00; t_down = 2026-11-26T09:43:12+00:00; t_up_cmd = 2026-11-26T09:44:12+00:00; t_ready = 2026-11-26T09:44:52+00:00; t_vazio = 2026-11-26T09:45:38+00:00; t_fim = 2026-11-26T09:46:23+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 2.8 min até t_vazio; indisponibilidade real = 101 s
- **Arquivos:** `resultados/K/R3/B/R3-B-2.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R3-C-2 · 2026-11-26 06:46

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 2, teto = 2, indisponibilidade nominal = 60 s, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T09:48:43+00:00; t_carga_fim = 2026-11-26T09:53:42+00:00; t0 = 2026-11-26T09:53:42+00:00; t_down = 2026-11-26T09:54:17+00:00; t_up_cmd = 2026-11-26T09:55:17+00:00; t_ready = 2026-11-26T09:55:58+00:00; t_vazio = 2026-11-26T09:56:24+00:00; t_zero = 2026-11-26T09:58:19+00:00; t_fim = 2026-11-26T09:58:19+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 2.7 min até t_vazio; indisponibilidade real = 101 s
- **Arquivos:** `resultados/K/R3/C/R3-C-2.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R3-A-2 · 2026-11-26 06:58

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 2, indisponibilidade nominal = 60 s, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T10:00:52+00:00; t_carga_fim = 2026-11-26T10:05:51+00:00; t0 = 2026-11-26T10:05:51+00:00; t_down = 2026-11-26T10:06:13+00:00; t_up_cmd = 2026-11-26T10:07:13+00:00; t_ready = 2026-11-26T10:07:54+00:00; t_job2 = 2026-11-26T10:09:40+00:00; t_vazio = 2026-11-26T10:09:46+00:00; t_job_fim = 2026-11-26T10:10:02+00:00; t_fim = 2026-11-26T10:10:48+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = —; duração = 3.9 min até t_vazio; indisponibilidade real = 101 s
- **Arquivos:** `resultados/K/R3/A/R3-A-2.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R3-C-3 · 2026-11-26 07:10

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 3, teto = 2, indisponibilidade nominal = 60 s, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T10:13:48+00:00; t_carga_fim = 2026-11-26T10:18:47+00:00; t0 = 2026-11-26T10:18:47+00:00; t_down = 2026-11-26T10:19:30+00:00; t_up_cmd = 2026-11-26T10:20:30+00:00; t_ready = 2026-11-26T10:21:10+00:00; t_vazio = 2026-11-26T10:21:42+00:00; t_zero = 2026-11-26T10:23:36+00:00; t_fim = 2026-11-26T10:23:36+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 2.9 min até t_vazio; indisponibilidade real = 101 s
- **Arquivos:** `resultados/K/R3/C/R3-C-3.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R3-A-3 · 2026-11-26 07:23

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 3, indisponibilidade nominal = 60 s, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T10:26:08+00:00; t_carga_fim = 2026-11-26T10:31:07+00:00; t0 = 2026-11-26T10:31:07+00:00; t_down = 2026-11-26T10:31:35+00:00; t_up_cmd = 2026-11-26T10:32:36+00:00; t_ready = 2026-11-26T10:33:16+00:00; t_job2 = 2026-11-26T10:35:25+00:00; t_vazio = 2026-11-26T10:35:30+00:00; t_job_fim = 2026-11-26T10:35:42+00:00; t_fim = 2026-11-26T10:36:27+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = —; duração = 4.4 min até t_vazio; indisponibilidade real = 101 s
- **Arquivos:** `resultados/K/R3/A/R3-A-3.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### R3-B-3 · 2026-11-26 07:36

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** `sha256:58fc08b35ec2ae4c0cae17f61729903a813b8756a9bd465c79de6e35ac22fade`
- **Parâmetros:** N = 100, *seed* = 3, teto = 1, indisponibilidade nominal = 60 s, timeout = 591 s
- **Instantes (UTC):** t_carga_inicio = 2026-11-26T10:39:53+00:00; t_carga_fim = 2026-11-26T10:44:52+00:00; t0 = 2026-11-26T10:44:52+00:00; t_down = 2026-11-26T10:45:22+00:00; t_up_cmd = 2026-11-26T10:46:22+00:00; t_ready = 2026-11-26T10:47:02+00:00; t_vazio = 2026-11-26T10:48:00+00:00; t_fim = 2026-11-26T10:48:45+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 3.1 min até t_vazio; indisponibilidade real = 101 s
- **Arquivos:** `resultados/K/R3/B/R3-B-3.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### E2-A-1 · 2026-11-26 07:48

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** —
- **Parâmetros:** N = 0, *seed* = 1, janela = 1800 s, timeout = 591 s
- **Instantes (UTC):** t0 = 2026-11-26T10:51:16+00:00; t_fim = 2026-11-26T11:21:17+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = —; duração = 30.0 min de janela
- **Arquivos:** `resultados/K/E2/A/E2-A-1.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### E2-B-1 · 2026-11-26 08:21

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** —
- **Parâmetros:** N = 0, *seed* = 1, teto = 1, janela = 1800 s, timeout = 591 s
- **Instantes (UTC):** t0 = 2026-11-26T11:24:02+00:00; t_fim = 2026-11-26T11:54:02+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 30.0 min de janela
- **Arquivos:** `resultados/K/E2/B/E2-B-1.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### E2-C-1 · 2026-11-26 08:54

- **Campanha:** K
- **Tipo:** válida
- **Commits:** data-processing `144d805` (tcc/pushadd-metricas) · deployment `d267e50` (main-estados) · estados `f7079d6` (tcc/e2-execucao)
- **Imagem:** —
- **Parâmetros:** N = 0, *seed* = 1, teto = 2, janela = 1800 s, timeout = 591 s
- **Instantes (UTC):** t0 = 2026-11-26T11:56:18+00:00; t_fim = 2026-11-26T12:26:26+00:00
- **Resultado rápido:** pendentes no fim = 0 (0 fora da DLQ); na DLQ = 0; duração = 30.1 min de janela
- **Arquivos:** `resultados/K/E2/C/E2-C-1.{csv,json,log}`
- **Anomalias:** nenhuma detectada pelo script
- **Validade:** válida pelos critérios automáticos do `run_experiment.sh`; conferir as anomalias e a interferência externa

### Fim da campanha K · 2026-11-26 09:26

- **Execuções:** 48 de 48 válidas (E1, R1, R1a, R2, R3: 9 cada; E2: 3). Uma tentativa não rodou (E1-C-3, 25/11 22:14, checklist; ver "Parada no E1-C-3")
- **Blocos:** E1 + R1 em 25/11 20:59 – 26/11 02:44; robustez + E2 em 26/11 02:53–09:26
- **Pods fora do experimento:** api, backend, celery-beat, celery-worker, frontend e garage-webui ficaram em 1 réplica desde o E1-A-1 (o `apply` do overlay `dev` os recria). Iguais em todas as execuções; registrado em [Desvios do protocolo](../docs/avaliacao/protocolo.md#desvios-do-protocolo)
- **Memória da máquina:** mínimo de 770 MiB disponíveis nos blocos robustez + E2 (26/11 03:43, entre o R1a-C-2 e o R1a-A-2), amostrada a cada 10 s; sem travamento
- **Repetição 3 do E1:** 15–20% mais lenta nos três modos (A 234 s, B 249 s, C 166 s, contra ~200/~205/140 s em k=1 e k=2); efeito da máquina, não do modo
- **Modo A:** o reinício do Job por 429 do OpenSearch (temas) aparece em parte das execuções; muda `t_job_fim − t_vazio` (23 s com reinício contra 216 s sem), não `t0 → t_vazio`
