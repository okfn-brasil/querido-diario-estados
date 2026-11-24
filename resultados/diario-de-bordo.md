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

Nenhuma execução registrada ainda.
