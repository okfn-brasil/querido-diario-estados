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

