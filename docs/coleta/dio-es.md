# Reconhecimento do portal do Diário Oficial do Espírito Santo (DIO-ES)

Levantamento feito em 10/10/2026 no portal `https://ioes.dio.es.gov.br`, para embasar o spider `es_estado`
(passo A5 do plano de implementação). As decisões que saem daqui estão na
[ADR-0008](../adrs/0008-coleta-do-diario-oficial-do-espirito-santo.md).

## Resumo

- O portal é o produto **DIONET**, da IONEWS, e tem uma API JSON pública que lista as edições de um dia.
  O `querido-diario` já tem uma base para essa plataforma (`BaseDionetSpider`), usada inclusive pelo `es_serra`,
  que aponta para este mesmo portal. O spider estadual não precisa de código de raspagem novo.
- O **Caderno dos Municípios Capixabas não é um arquivo separado**: desde 25/05/2020 ele vem dentro do mesmo
  PDF do diário estadual. Não dá para excluí-lo na coleta sem recortar o PDF.
- O acervo digital começa em **17/03/2003**, e não em 2014.
- O conteúdo é do Executivo estadual, com publicações residuais de outros poderes. `power="executive"`, sem alterar o schema.
- Os PDFs têm texto nativo. Não é preciso OCR.

## 1. Como listar as edições de um dia

```
GET https://ioes.dio.es.gov.br/apifront/portal/edicoes/edicoes_from_data/{AAAA-MM-DD}.json
```

A data vai no caminho da URL, sem POST, sem cookie e sem token. Não existe listagem mensal: `2026-10.json` devolve
`"Data inválida"`. A coleta é uma requisição por dia.

Resposta de um dia com edição normal e edição extra (08/10/2026):

```json
{
  "erro": false, "msg": "", "data": "2026-10-08", "numero": null, "ano": "",
  "itens": [
    {"id": 11538, "data": "08/10/2026", "suplemento": 1, "numero": 26826, "tipo_edicao_id": 1,
     "tipo_edicao_nome": "Diário Oficial do Espírito Santo", "capa": 1, "paginas": 2},
    {"id": 11533, "data": "08/10/2026", "suplemento": 0, "numero": 26826, "tipo_edicao_id": 1,
     "tipo_edicao_nome": "Diário Oficial do Espírito Santo", "capa": 1, "paginas": 63}
  ]
}
```

Dia sem edição (fim de semana, feriado ou lacuna do acervo): HTTP 200 com
`{"erro": true, "msg": "Edição não existente!", "itens": []}`. O status HTTP não distingue os dois casos; é preciso olhar o campo `erro`.

Outros diários hospedados no mesmo portal são selecionados pelo parâmetro `?subtheme=` na query string.
Sem o parâmetro, a API devolve só o diário estadual (`tipo_edicao_id = 1`).

| `subtheme` | Diário | `tipo_edicao_id` | Situação no Querido Diário |
| -------- | -------- | -------- | -------- |
| *(ausente)* | Diário Oficial do Espírito Santo | 1 | alvo do `es_estado` |
| `diariodaserra` | Prefeitura Municipal da Serra | 5 | já coletado pelo `es_serra` (`3205002`) |
| `dom` | DOM - AMUNES | 13 | não coletado; corresponderia ao território `3200000` |
| `caderno_municipios` | Caderno dos Municípios | 3 | ver a pergunta 3 |

Endpoints auxiliares encontrados, que o spider não precisa usar:

- `/apifront/portal/edicoes/ultimas_edicoes.json`: últimas edições publicadas.
- `/apifront/portal/edicoes/busca_edicao/{id}`: metadados de uma edição (data, número, páginas, `hash` de autenticidade).
- `/portal/visualizacoes/view_html_diario/{id}`: árvore de seções e matérias da edição, em HTML. Existe para as edições de 2015 em diante; a de 02/01/2014 devolve a árvore vazia.
- `/portal/edicoes/download/{id}/{pagina}`: PDF de uma única página.

## 2. Onde ficam os campos

Não há HTML para interpretar. Tudo vem do JSON da listagem:

| Campo do `Gazette` | Origem |
| -------- | -------- |
| `date` | a data pedida na URL (o campo `data` do item repete a mesma data em `DD/MM/AAAA`) |
| `edition_number` | `numero` |
| `is_extra_edition` | `suplemento == 1` |
| `file_urls` | `https://ioes.dio.es.gov.br/portal/edicoes/download/{id}` |

Observações:

- A edição extra **repete o `numero`** da edição normal do dia. O que diferencia as duas é o `id` e o `suplemento`.
- Edições até 05/02/2014 vêm com `numero = 0`; a numeração real só aparece depois disso (23943 em 12/02/2015).
  Em 2013 há ainda sete edições com números soltos e baixos, como `9`, que não são o número da edição.
  O spider deve omitir o `edition_number` quando ele for `0`, em vez de gravar `"0"`.
- O download responde direto com `application/pdf` e `Content-Disposition: attachment`, sem redirecionamento.
- `paginas` vem na listagem e bate com o PDF (83 páginas na edição de 09/10/2026).

É exatamente o que o `BaseDionetSpider` (`querido-diario/querido_diario_raspadores/gazette/spiders/base/dionet.py`) já faz.
O `es_estado` se resume a herdar dele com `BASE_URL = "https://ioes.dio.es.gov.br"` e sem `url_subtheme`.
Dois ajustes ficam para o A5: tratar o `numero = 0` e manter `power="executive"`, que a base já fixa.

## 3. Cadernos e o Caderno dos Municípios

Cada edição é **um único PDF**. As seções ficam dentro dele, nesta ordem:

| Seção no PDF | Nó na árvore do portal | Conteúdo |
| -------- | -------- | -------- |
| PODER EXECUTIVO | `Poder Executivo` | Governadoria, secretarias, autarquias e empresas estaduais |
| LICITAÇÕES | `Licitações` | licitações de órgãos estaduais |
| DIVERSOS | `Diversos` | Defensoria Pública, Ministério Público, publicações de terceiros, entidades federais |
| CADERNO DOS MUNICÍPIOS CAPIXABAS | `CM - EXECUTIVO` e `CM - LICITAÇÕES` | atos e licitações de prefeituras, câmaras e entidades municipais |

Sobre o Caderno dos Municípios:

- Ele passou a integrar o PDF do diário estadual em **25/05/2020** (a edição de 22/05/2020 ainda não tem as seções `CM`).
- Nas 25 edições amostradas de 2020 a 2026, ele responde por 27% das matérias. Na edição de 09/10/2026, ocupa cerca de 15 das 83 páginas.
- Algumas **edições extras são só Caderno dos Municípios**: as de 25/09/2026 e 08/10/2026 têm 2 páginas cada e uma única matéria municipal.
  A listagem não informa isso; só a árvore de seções ou o próprio PDF.
- O subtema `?subtheme=caderno_municipios` teve edições avulsas entre out/2020 e 2022 (por exemplo, a nº 106, de 10/03/2021, com 13 páginas).
  Nessas datas o caderno **também** estava dentro do PDF principal, então a edição avulsa é uma cópia. Em 2023 e em 2026 o subtema não devolve nada.

Consequência para a coleta: a recomendação original de **excluir** o caderno não se aplica como estava escrita, porque
não existe um arquivo do caderno para deixar de baixar. As opções e a decisão estão na ADR-0008. Em resumo: baixar o PDF
como publicado e não coletar os subtemas `caderno_municipios`, `dom` e `diariodaserra`.

## 4. Data da primeira edição

A primeira edição disponível é a de **17/03/2003** (`id` 347, 73 páginas). Nenhuma das datas testadas antes disso tem edição:
todos os dias úteis de 01/10/2002 a 14/03/2003 e 8 dias úteis por ano de 1996 a 2002.

A matriz apontava 2014. O acervo anterior existe e está em PDF com texto, mas tem lacunas:

| Ano | Dias úteis | Dias com edição | Cobertura |
| -------- | -------- | -------- | -------- |
| 2003 (a partir de 17/03) | 208 | 92 | 44% |
| 2004 | 262 | 233 | 89% |
| 2005 | 260 | 220 | 85% |
| 2006 | 260 | 229 | 88% |
| 2007 a 2015 | 2.349 | 2.202 | 94% |

A contagem de dias úteis não desconta feriados, então algo em torno de 94% já é acervo completo. As lacunas de fato são três:
de 01/08/2003 a 04/01/2004 (cinco meses sem nenhuma edição), junho de 2005 inteiro e dez dias em setembro de 2004.
De 2003 a 2015 o portal tem 2.996 edições, e as primeiras edições extras aparecem em 2014.
A varredura cobriu todos os dias úteis de 17/03/2003 a 31/12/2015; de 2016 em diante a conferência foi por amostragem.

Os `id` das edições não são cronológicos (o `id` 3 é de 15/05/2020 e o 1000 é de 14/07/2003), então não servem para
percorrer o acervo. A varredura tem que ser por data.

## 5. Concorrência

Teste feito em 10/10/2026, de madrugada, a partir de uma conexão residencial.

| Cenário | Requisições | Erros | Tempo total | Mediana por requisição |
| -------- | -------- | -------- | -------- | -------- |
| Listagem, sequencial, `DOWNLOAD_DELAY` 0,5 s | 40 | 0 | 30,6 s | 0,26 s |
| Listagem, 8 concorrentes, sem delay | 40 | 0 | 1,2 s | 0,22 s |
| PDF, sequencial, delay 0,5 s | 8 (27,2 MB) | 0 | 11,2 s | 0,91 s |
| PDF, 8 concorrentes, sem delay | 8 (26,7 MB) | 0 | 8,7 s | 7,33 s |

O servidor aguenta 8 requisições concorrentes sem erro, sem bloqueio e sem aumento de latência na listagem.
Além desses testes, o levantamento fez cerca de 3.700 requisições de listagem com intervalo de 0,5 s, todas com HTTP 200.

Nos PDFs a concorrência não rende: o volume baixado por segundo é praticamente o mesmo nos dois cenários (uns 3 MB/s),
e cada download concorrente fica 8 vezes mais lento. O teste não permite dizer se o limite é do servidor ou da conexão usada.

Não há Cloudflare, captcha nem exigência de cookie. O `robots.txt` não existe (a URL devolve a página inicial do portal).

## 6. Os PDFs têm texto nativo?

Sim. As cinco amostras foram conferidas com `pdftotext` e `pdffonts`:

| Arquivo | Data | Páginas | Tamanho | Caracteres extraídos | Gerado por |
| -------- | -------- | -------- | -------- | -------- | -------- |
| `es_estado_2003-03-17_347.pdf` | 17/03/2003 | 73 | 4,5 MB | 394.169 | Win2PDF / PDFlib |
| `es_estado_2014-01-02_1849.pdf` | 02/01/2014 | 100 | 19,2 MB | 727.391 | PageMaker / Acrobat |
| `es_estado_2022-01-03_6530.pdf` | 03/01/2022 | 181 | 8,5 MB | 542.514 | InDesign / Ghostscript |
| `es_estado_2026-10-08_11538_extra.pdf` | 08/10/2026 (extra) | 2 | 1,0 MB | 1.972 | InDesign |
| `es_estado_2026-10-09_11542.pdf` | 09/10/2026 | 83 | 3,2 MB | 324.262 | Acrobat / Ghostscript |

Todos têm fontes embutidas e texto extraível, da edição mais antiga à mais recente. O Tika não precisa de OCR.

Dois detalhes que afetam o processamento:

- A capa das edições recentes é uma imagem. O texto que sai dela vem com ruído (`lnformaçiio com t,..nspar<incia`),
  mas o corpo da edição é texto nativo limpo.
- Cada matéria vem delimitada por marcadores no texto extraído, como `<#DIOES#1883473#1#2038079>` na abertura e
  `<#DIOES#1883473#1#2038079/>` no fechamento. Eles podem servir à segmentação, mas poluem o texto indexado se não forem removidos.

As amostras ficam em `simulador/amostras/`, fora do git (`.gitignore`). O `simulador/amostras/manifest.csv` é versionado e traz
tamanho, páginas, SHA-256 e a URL de cada arquivo, para quem precisar baixá-los de novo. Elas serão reaproveitadas no simulador (D1).

## Poderes que publicam no DIO-ES (issue A3)

Para responder se o schema precisa de `"judiciary"`, as matérias de 47 edições normais (uma por trimestre, de fev/2015 a ago/2026)
foram classificadas pelo órgão que aparece na árvore de seções do portal. Total: 13.071 matérias.

| Origem | Matérias | Parcela |
| -------- | -------- | -------- |
| Executivo estadual (seções Poder Executivo e Licitações) | 8.569 | 65,6% |
| Caderno dos Municípios (prefeituras, câmaras, entidades municipais) | 2.333 | 17,8% |
| Publicações de terceiros e entidades federais | 1.575 | 12,0% |
| Defensoria Pública | 289 | 2,2% |
| Ministério Público | 231 | 1,8% |
| Poder Legislativo (Assembleia) | 45 | 0,3% |
| Poder Judiciário | 14 | 0,1% |
| Tribunal de Contas | 8 | 0,1% |
| Entidades estaduais (em Diversos) | 7 | 0,1% |

O Judiciário aparece em 10 das 47 edições, sempre na seção Diversos, com um a quatro editais avulsos por edição
(editais de citação e de notificação de comarcas). Não há caderno do Judiciário: o Diário da Justiça é publicado pelo TJ-ES em outro sistema.
O Legislativo aparece com autógrafos de lei e decretos legislativos da Assembleia, também em Diversos.
Na edição de 2003, as páginas do Tribunal de Contas vêm sob o cabeçalho "Poder Legislativo".

O campo `power` é um valor por edição, não por matéria, e não há como marcar essas publicações avulsas com ele.
Conclusão: o DIO-ES é o diário do Executivo, `power="executive"`, e o `gazette_schema.json` fica como está.

Como o `power` é usado hoje nos outros repositórios (verificado com `grep`):

- `querido-diario`: enum com `executive`, `legislative` e `executive_legislative` em `gazette_schema.json`; os spiders usam `executive` (38) ou `executive_legislative` (39).
- `querido-diario-api`: `power` é `Optional[str]` em `api/api.py`, gravado como texto. Não valida contra o enum.
- `querido-diario-frontend`: não referencia o campo.
- `querido-diario-data-processing`: só aparece em dados de teste.

Um valor novo no enum só exigiria mudar o `gazette_schema.json`, caso um dia seja necessário.

## Como reproduzir

```bash
# listagem de um dia
curl -s "https://ioes.dio.es.gov.br/apifront/portal/edicoes/edicoes_from_data/2026-10-08.json"

# download e conferência do texto
curl -s -o edicao.pdf "https://ioes.dio.es.gov.br/portal/edicoes/download/11542"
pdftotext edicao.pdf - | head

# árvore de seções de uma edição
curl -s "https://ioes.dio.es.gov.br/portal/visualizacoes/view_html_diario/11542"
```
