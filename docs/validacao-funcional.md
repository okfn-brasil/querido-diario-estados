# Validação funcional: baseline × fila de extração

Este documento registra a validação funcional da fila de extração (item C7 do plano, issue #25): se a arquitetura proposta (fila com Celery + Redis e workers escalados pelo KEDA, ADR-0009 e ADR-0010) entrega o **mesmo resultado funcional** que a arquitetura atual (CronJob sequencial `data-processing`, o baseline).

Aqui não se compara desempenho. Tempos, vazão e uso de recursos são objeto dos experimentos da Parte E, com protocolo, cenários e carga definidos antes. As durações abaixo são só uma observação informal.

## Resultado

**Os dois modos passaram em todos os itens, com resultado idêntico** (0 diferença nas 17 comparações do roteiro).

| # | Item | Baseline (CronJob) | Fila (KEDA) |
|---|---|---|---|
| 1 | Coletar, processar e ter `processed=true` em todas as linhas | ✅ 27/27 | ✅ 27/27 |
| 2 | `GET /gazettes?territory_ids=3299999&querystring=decreto` retorna resultados | ✅ 26 diários | ✅ 26 diários (os mesmos) |
| 3 | Operadores da busca avançada com resultados equivalentes | ✅ 13 consultas | ✅ 13 consultas (mesmos diários em todas) |
| 4 | Excertos temáticos criados depois do processamento dos temas | ✅ 22 + 9 excertos | ✅ 22 + 9 excertos (os mesmos) |
| 5 | O PDF original abre a partir do frontend | ✅ | ✅ |

## Ambiente e dados

- Cluster kind local (`querido-diario-dev`), Docker Desktop com ~6 GB de memória, em 31/10/2026.
- Dados: os **27 diários do Governo do Estado do Espírito Santo** (`3299999`) coletados com o spider `es_estado`, de 01/09 a 09/10/2026 (25 dias com edição e 2 edições extras). A issue pedia uma semana; o período usado cobre mais de cinco.
- **Mesma imagem de código nos dois modos** (`querido-diario-data-processing:tcc-fila`, `main-estados` com C3, C4 e C5). No baseline, o CronJob `data-processing` foi apontado para essa imagem; assim, a única diferença entre os modos é a arquitetura.

| | Baseline | Fila |
|---|---|---|
| Overlay | `k8s/overlays/dev` (`make k8s-local-queue-down`) | `k8s/overlays/dev-queue` (`make k8s-local-queue`) |
| Extração | um Job do CronJob processa os diários em sequência | `enqueue-extraction` enfileira; até 2 workers (KEDA) processam |
| Tika | Deployment compartilhado (`apache-tika`) | sidecar em cada worker; o compartilhado fica em 0 |
| Excertos temáticos | no mesmo Job, depois da extração | CronJob `themes-from-queue` |

## Procedimento

Antes de cada modo, o roteiro volta o território ao estado "coletado, não processado": `processed=false` no Postgres e, no OpenSearch, sem os documentos do território (`queridodiario`) e sem os excertos deles (`educacao` e `ambiental`). Os PDFs continuam no Garage.

```bash
# Baseline
make -C ../querido-diario-deployment k8s-local-queue-down
python3 scripts/validacao_funcional.py zerar
make -C ../querido-diario-deployment k8s-local-data-processing   # e esperar o Job terminar
python3 scripts/validacao_funcional.py coletar --modo baseline \
  --saida resultados/validacao-funcional/baseline.json

# Fila
make -C ../querido-diario-deployment k8s-local-queue
python3 scripts/validacao_funcional.py zerar
kubectl create job --from=cronjob/enqueue-extraction c7-enqueue -n querido-diario
# esperar os diários ficarem processed=true
kubectl create job --from=cronjob/themes-from-queue c7-themes -n querido-diario
python3 scripts/validacao_funcional.py coletar --modo fila \
  --saida resultados/validacao-funcional/fila.json

# Comparação
python3 scripts/validacao_funcional.py comparar \
  resultados/validacao-funcional/baseline.json resultados/validacao-funcional/fila.json
```

O roteiro (`scripts/validacao_funcional.py`, só biblioteca padrão) consulta a API pública local (`api.queridodiario.local`) e o Postgres do cluster. Para as buscas, compara o **conjunto** de diários retornados (território, data e checksum de cada um) e, para os temas, o conjunto de excertos. Os resultados completos estão em `resultados/validacao-funcional/`.

## Item 3: operadores da busca avançada

A API repassa o texto ao OpenSearch como *simple query string*, com o operador padrão **OU** entre termos (`querido-diario-api/index/opensearch.py`). Resultados nos 27 diários:

| Consulta | O que testa | Baseline | Fila |
|---|---|---|---|
| `decreto` | termo simples (item 2) | 26 | 26 |
| `"secretaria de estado"` | frase entre aspas | 25 | 25 |
| `+decreto +nomear` | `+` obrigatório (E) | 25 | 25 |
| `decreto -portaria` | `-` exclusão, como um usuário escreveria | 27 | 27 |
| `decreto +-portaria` | `-` exclusão que funciona com o padrão OU | 1 | 1 |
| `decreto \| portaria` | `\|` OU | 26 | 26 |
| `exoner*` | `*` prefixo | 23 | 23 |
| `"secretaria educação"~3` | `~N` proximidade em frase | 25 | 25 |
| `govenador~1` | `~N` aproximação (erro de digitação) | 25 | 25 |
| `exonaração~1` | `~N` aproximação em palavra reduzida pelo stemmer | 0 | 0 |
| `(decreto \| portaria) +educação` | `( )` agrupamento | 25 | 25 |
| `nomeação` | com acento | 19 | 19 |
| `nomeacao` | sem acento | 19 | 19 |

## Observações

Nenhuma das observações abaixo depende do modo: aparecem igualmente no baseline e na fila, porque vêm da API, do índice ou da coleta.

1. **Exclusão com `-` não exclui sozinha.** Com o operador padrão OU, `decreto -portaria` vira "decreto OU (não portaria)" e devolve mais diários (27) do que `decreto` (26). A exclusão só funciona escrita como `decreto +-portaria` (1 diário), igual ao OpenSearch consultado diretamente com `default_operator: and`. Um usuário comum escreveria `decreto -portaria`; vale avaliar com o Querido Diário se o padrão deveria ser E ou se a documentação da busca deveria explicar isso.
2. **Aproximação (`~N`) não passa pelo stemmer.** `govenador~1` encontra "governador", mas `exonaração~1` não encontra "exoneração": o índice guarda o radical (`exoner`) e a busca aproximada compara o termo digitado, sem reduzi-lo.
3. **A busca no texto ignora acentos; a busca de município não.** `nomeação` e `nomeacao` trazem os mesmos 19 diários. Já o `GET /cities` (campo de município do frontend) compara o nome com acento: "Espirito", "Sao Paulo" e "Vitoria" retornam 0, inclusive na API de produção (`api.queridodiario.org.br`). É o comportamento atual do upstream (`cities/city_access.py`), candidato a sugestão para o Querido Diário.
4. **PDF sem `Content-Type`.** O Garage entrega os PDFs sem o cabeçalho `Content-Type`; o navegador identifica o arquivo pelo conteúdo (`%PDF-`) e abre normalmente. Quem grava o arquivo é o raspador, então isso independe do modo.
5. **Ordem dos resultados com relevância empatada.** Numa busca sem palavra-chave, o primeiro diário retornado mudou entre os modos (30/09 no baseline, 09/10 na fila): com relevância igual, a ordem depende da ordem de indexação, que na fila é paralela. O conjunto de resultados é o mesmo; por isso o roteiro compara conjuntos, não a ordem.
6. **Caderno dos Municípios sob `3299999`.** Atos de prefeituras e câmaras publicados no Caderno dos Municípios Capixabas aparecem como resultados do governo estadual, porque vêm dentro do mesmo PDF. É o comportamento esperado pela ADR-0008.
7. **Item 5 no frontend.** O PDF foi aberto pelo frontend local (`queridodiario.local`) numa busca pelo "Governo do Estado do Espírito Santo". O roteiro confirma, nos dois modos, que a URL devolvida pela API responde 200 com um PDF.

## Durações (observação informal, não é resultado)

Medidas uma única vez, com 27 diários e sem controle de carga, só para planejar a Parte E:

| | Baseline | Fila |
|---|---|---|
| Extração dos 27 diários | 107 s, no mesmo Job dos temas | 44 s (do enfileiramento ao último `processed=true`, 2 workers) |
| Excertos temáticos | incluídos nos 107 s | 102 s (Job `themes-from-queue`, com o carregamento do BERT) |

Os números não são comparáveis entre si: o Job do baseline faz extração e temas juntos e carrega o BERT uma vez, os workers da fila começam do zero (inicialização do Tika) e a amostra é pequena.
