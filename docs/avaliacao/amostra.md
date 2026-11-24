# Amostra de PDFs do simulador

Este documento descreve o conjunto de PDFs reais que o simulador de carga (D2, `simulador/load_simulator.py`) usa para gerar diários sintéticos (item D1 do plano, issue #27). A amostra é uma das variáveis controladas do [protocolo](protocolo.md): todas as execuções de uma campanha usam a mesma.

## Como obter

Os PDFs (490 MB) ficam em `simulador/amostras/`, fora do git (`.gitignore`). O que é versionado é o `simulador/amostras/manifest.csv`, com a URL e o SHA-256 de cada arquivo, e o script que monta a amostra:

```bash
python3 simulador/montar_amostra.py baixar   # baixa o que falta e confere o SHA-256 de cada arquivo
python3 simulador/montar_amostra.py resumo   # tabelas desta página, a partir do manifest.csv
python3 simulador/montar_amostra.py montar   # refaz o sorteio e o manifesto (só para mudar a amostra)
```

O script usa só a biblioteca padrão do Python e o `poppler-utils` (`pdfinfo` e `pdftotext`).

O `manifest.csv` é a referência da amostra: se um portal republicar uma edição, o `baixar` acusa o SHA-256 diferente, em vez de trocar o arquivo sem aviso.

## Composição

104 edições, sendo 54 do diário estadual do Espírito Santo e 50 de cinco municípios:

| Grupo | Fonte | Edições | Como foram escolhidas |
|---|---|---|---|
| `a4` | DIO-ES, estado (`3299999`) | 5 | as amostras do reconhecimento do portal (A4), descritas em [dio-es.md](../coleta/dio-es.md#6-os-pdfs-têm-texto-nativo) |
| `a6` | DIO-ES, estado | 27 | todas as edições de 01/09 a 09/10/2026, o período da coleta real no cluster local (A6) e da [validação funcional](../validacao-funcional.md). O portal lista hoje 29 edições nesse período (27 dias com edição e 2 extras); 2 delas já estão no grupo `a4` |
| `historico` | DIO-ES, estado | 22 | uma edição sorteada por ano, de 2004 a 2025 |
| `municipal` | 5 municípios | 50 | 10 edições sorteadas de cada um, de 01/2025 a 10/2026 |

Os municípios são os que publicam na mesma plataforma do DIO-ES (DIONET, da IONEWS) e já têm raspador no `querido-diario` (`gazette/spiders/base/dionet.py`). Assim, as URLs vêm da mesma API que os raspadores usam (`/apifront/portal/edicoes/edicoes_from_data/<data>.json`). Eles cobrem portes bem diferentes:

| Fonte | Município | Por que ajuda |
|---|---|---|
| `rj_rio_de_janeiro` | Rio de Janeiro (RJ), capital | edições muito grandes, de até 500 páginas |
| `sp_sao_jose_dos_campos` | São José dos Campos (SP) | município grande do Sudeste |
| `es_serra` | Serra (ES) | município do estado piloto, publicado no próprio portal do DIO-ES |
| `ms_corumba` | Corumbá (MS) | município médio, fora do Sudeste |
| `ro_jaru` | Jaru (RO) | município pequeno, fora do Sudeste |

Nos sorteios, o script escolhe um dia ao acaso no intervalo. Se não houver edição nesse dia (fim de semana ou feriado), ele avança dia a dia até achar uma e sorteia uma das edições daquele dia, que pode ser uma extra. A semente é fixa (`SEMENTE = 2026`), então `montar` refaz o mesmo sorteio enquanto os portais não mudarem.

### Diferença em relação ao plano

O plano pedia, além do ES, diários municipais **do bucket local**. No momento da montagem (24/11/2026), o cluster kind estava parado, e a API pública do Querido Diário, que listaria os diários do bucket de produção, respondia 503. Os municipais vieram então direto dos portais oficiais, pelo mesmo caminho dos raspadores. Isso tem duas vantagens: cada arquivo tem uma URL pública no manifesto, e a amostra pode ser refeita em qualquer máquina, sem depender de um bucket.

## Distribuição

Gerada com `python3 simulador/montar_amostra.py resumo`:

| Grupo | Arquivos | Tamanho (MB): mín · Q1 · mediana · Q3 · máx | Total (MB) | Páginas: mín · Q1 · mediana · Q3 · máx | Caracteres/página (mediana) |
|---|---|---|---|---|---|
| ES estadual | 54 | 0,7 · 2,4 · 4,2 · 8,3 · 20,6 | 322,7 | 2 · 72 · 82 · 100 · 204 | 4.342 |
| Municipal | 50 | 0,2 · 1,6 · 3,2 · 4,4 · 10,3 | 167,3 | 2 · 10 · 16 · 38 · 504 | 4.266 |
| Total | 104 | 0,2 · 2,2 · 3,8 · 5,2 · 20,6 | 490,0 | 2 · 16 · 72 · 92 · 504 | 4.342 |

| Fonte | Grupo | Arquivos | Páginas (total) | Tamanho (MB, total) | Sem texto extraível* |
|---|---|---|---|---|---|
| `es_estado` | a4 | 5 | 439 | 36,4 | 0 |
| `es_estado` | a6 | 27 | 2.201 | 82,1 | 0 |
| `es_estado` | historico | 22 | 2.001 | 204,2 | 0 |
| `es_serra` | municipal | 10 | 203 | 30,9 | 0 |
| `ms_corumba` | municipal | 10 | 234 | 28,1 | 0 |
| `rj_rio_de_janeiro` | municipal | 10 | 2.122 | 60,5 | 0 |
| `ro_jaru` | municipal | 10 | 182 | 35,3 | 0 |
| `sp_sao_jose_dos_campos` | municipal | 10 | 332 | 12,5 | 0 |

\* menos de 100 caracteres por página no `pdftotext`: provavelmente digitalizado (precisaria de OCR).

O que isso diz para os experimentos:

- **Todos os PDFs têm texto nativo.** Nenhum precisa de OCR, então o tempo de extração no Tika depende do tamanho e do número de páginas, e não de reconhecimento de imagem. A amostra não representa diários digitalizados, que existem em outros municípios do Querido Diário.
- **O tamanho em bytes não acompanha o número de páginas.** As edições do ES ficam mais leves com o tempo: cerca de 130 kB por página de 2004 a 2015, 67 kB de 2016 a 2025 e 37 kB em 2026. Por isso os 22 arquivos históricos somam 204 MB, contra 82 MB dos 27 de 2026. Já a maior edição em páginas (Rio de Janeiro, 504 páginas) tem só 4,3 MB. É isso que separa o tempo de download e upload do tempo de extração.
- **A distribuição tem cauda longa.** A mediana é de 72 páginas, mas seis arquivos passam de 180, e três edições do Rio de Janeiro passam de 400. Eles definem o diário mais demorado, que o R1 usa para calibrar o `QUEUE_VISIBILITY_TIMEOUT` ([cenarios.md](cenarios.md#r1--worker-morto-no-meio-do-processamento)). O piloto do protocolo mede esse tempo.
- **8 das 104 edições são extras.** Sete são curtas (de 2 a 12 páginas), como no dia a dia dos portais. A exceção é uma extra do Rio de Janeiro com 504 páginas, a maior edição da amostra.

## Uso no simulador

O simulador sorteia, para cada diário sintético, um PDF da amostra, anexa um comentário único no fim para mudar o checksum e o insere como diário não processado (D2). Nos cenários, todos os diários são inseridos com `--territory 3299999`, então PDFs municipais entram como se fossem edições do estado. Isso não altera o caminho de processamento: a segmentação por município só se aplica a diários de associações de municípios, e o Tika e o OpenSearch tratam todos os PDFs da mesma forma.

## Colunas do manifesto

| Coluna | Conteúdo |
|---|---|
| `arquivo` | nome do arquivo em `simulador/amostras/`: `<fonte>_<data>_<edicao_id>[_extra].pdf` |
| `fonte` | raspador de origem (`es_estado`, `rj_rio_de_janeiro` etc.) |
| `grupo` | `a4`, `a6`, `historico` ou `municipal` (ver [Composição](#composição)) |
| `territory_id`, `territorio` | código IBGE e nome do território de origem |
| `data`, `edicao_id`, `numero`, `extra` | data de publicação, id da edição no portal, número da edição (vazio quando o portal informa 0) e se é extra |
| `tamanho_bytes`, `paginas` | tamanho do arquivo e número de páginas (`pdfinfo`) |
| `caracteres_texto` | caracteres extraídos pelo `pdftotext` |
| `produtor` | campo `Producer` do PDF (ferramenta que o gerou) |
| `sha256` | hash do arquivo, conferido pelo `baixar` |
| `url` | URL de download no portal oficial |
