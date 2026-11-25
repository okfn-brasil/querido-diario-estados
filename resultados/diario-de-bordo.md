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
