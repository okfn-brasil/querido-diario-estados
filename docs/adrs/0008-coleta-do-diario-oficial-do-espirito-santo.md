# 0008. Coleta do diário oficial do Espírito Santo
Data: 10/10/2026
Status: Proposto

## Contexto e Declaração do Problema
A ADR-0005 escolheu o Espírito Santo como estado piloto e a ADR-0006 definiu o `territory_id` `3299999` para o governo estadual. Falta definir **como** coletar o Diário Oficial do Espírito Santo (DIO-ES), publicado em `https://ioes.dio.es.gov.br`: de onde vem a lista de edições, o que fazer com o Caderno dos Municípios, qual valor de `power` usar, a partir de que data coletar e com que ritmo de requisições.

O reconhecimento do portal, feito em 10/10/2026 e registrado em [`docs/coleta/dio-es.md`](../coleta/dio-es.md), mudou três premissas do plano de implementação:

1. O portal é o produto DIONET, da IONEWS, com uma API JSON que lista as edições de um dia. O `querido-diario` já tem uma base para essa plataforma, o `BaseDionetSpider`, usada por cinco spiders municipais, entre eles o `es_serra`, que consulta este mesmo portal.
2. O Caderno dos Municípios Capixabas não é um arquivo à parte. Desde 25/05/2020 ele vem dentro do mesmo PDF do diário estadual e responde por cerca de 27% das matérias de cada edição. O plano recomendava excluí-lo, supondo que fosse um caderno separado.
3. O acervo digital começa em 17/03/2003, e não em 2014, como apontava a matriz comparativa.

O levantamento também mostrou que o DIO-ES traz publicações avulsas de outros poderes (editais do Judiciário, autógrafos de lei da Assembleia), o que levanta a dúvida da issue A3: o enum `power` do `gazette_schema.json`, que hoje aceita `executive`, `legislative` e `executive_legislative`, precisa de um valor novo?

## Fatores Determinantes da Decisão
- Reaproveitamento do código existente (coerência com as ADRs 0002 e 0003)
- Baixo esforço para viabilizar o piloto dentro do prazo do TCC
- Fidelidade ao documento oficial: o PDF publicado tem assinatura digital e código de autenticidade
- Não atribuir ao governo estadual, na busca, atos que são de municípios
- Não alterar contratos compartilhados (schema, API) sem necessidade
- Cobertura histórica do acervo
- Carga imposta ao servidor do DIO-ES

## Alternativas Consideradas

**Fonte e listagem das edições**
- A1: Escrever um spider próprio, percorrendo o HTML do portal
- A2: Herdar de `BaseDionetSpider`, apontando para a API JSON `edicoes_from_data/{data}.json` sem `subtheme`

**Caderno dos Municípios**
- B1: Coletar o PDF completo, como publicado, e não coletar os subtemas municipais do portal
- B2: Recortar o PDF na coleta, descartando as páginas do caderno
- B3: Coletar o PDF completo e separar o conteúdo municipal no processamento, com um segmentador por território
- B4: Descartar as edições extras que contêm apenas o caderno

**Valor de `power`**
- C1: Usar `executive`, sem alterar o schema
- C2: Usar `executive_legislative`
- C3: Adicionar `judiciary` (ou um valor combinado) ao enum

**Data inicial (`start_date`)**
- D1: 17/03/2003, a primeira edição disponível
- D2: 01/01/2014, como previa a matriz
- D3: 25/05/2020, quando o formato atual do diário se estabiliza

**Ritmo de requisições**
- E1: Padrão do Scrapy (8 requisições concorrentes por domínio, sem intervalo)
- E2: `DOWNLOAD_DELAY` de 0,5 s com `RANDOMIZE_DOWNLOAD_DELAY`

## Alternativa Escolhida

**Fonte e listagem: A2.** O spider `es_estado` herda de `BaseDionetSpider` com `BASE_URL = "https://ioes.dio.es.gov.br"` e sem `url_subtheme`. A base já faz uma requisição por dia, lê `id`, `numero` e `suplemento` do JSON e monta a URL de download `/portal/edicoes/download/{id}`. Sobra um único ajuste: edições até fevereiro de 2014 vêm com `numero = 0`, e nesses casos o `edition_number` deve ser omitido.

**Caderno dos Municípios: B1.** O spider baixa o PDF de cada edição como publicado, com o caderno dentro, e coleta só o diário estadual: os subtemas `caderno_municipios`, `dom` (AMUNES) e `diariodaserra` do mesmo portal ficam de fora. Edições extras são coletadas mesmo quando contêm apenas matérias municipais.

Justificativa: a exclusão recomendada no plano pressupunha um arquivo separado, que não existe. Recortar o PDF (B2) exigiria uma requisição a mais por edição para descobrir as páginas, manipulação de PDF dentro do spider, que nenhum raspador do projeto faz, e produziria um arquivo diferente do documento assinado pelo DIO, cujo checksum deixaria de corresponder ao original. Descartar extras (B4) tem o mesmo custo de requisição e criaria buracos na numeração para economizar arquivos de duas páginas. O subtema `caderno_municipios` só teve edições avulsas entre 2020 e 2022, e eram cópia do que já estava no PDF principal.

O efeito conhecido dessa escolha é que atos de prefeituras e câmaras capixabas passam a aparecer em buscas pelo território `3299999`. A separação correta é a B3, um segmentador que reatribui as matérias do caderno aos municípios, como o `ALAssociacaoMunicipiosSegmenter` faz para Alagoas. Os marcadores `<#DIOES#...>` que delimitam cada matéria no texto extraído e os cabeçalhos `CADERNO DOS MUNICÍPIOS CAPIXABAS` tornam isso viável. Fica registrada como trabalho futuro, fora do escopo do TCC, que está na fila de extração e não na segmentação.

**Valor de `power`: C1.** O `es_estado` usa `power="executive"` e o `gazette_schema.json` não é alterado.

Justificativa: em 47 edições amostradas de 2015 a 2026 (13.071 matérias), o Judiciário responde por 0,1% das matérias, o Legislativo por 0,3% e o Tribunal de Contas por 0,1%, sempre como publicações avulsas na seção Diversos ou em Licitações. Não existe caderno do Judiciário nem do Legislativo: o Diário da Justiça é publicado pelo TJ-ES em outro sistema. O campo `power` vale para a edição inteira e identifica quem publica o diário, que é o Executivo, por meio do Departamento de Imprensa Oficial. Usar `executive_legislative` (C2) descreveria mal um diário em que o Legislativo é residual, e um valor novo (C3) não descreveria melhor a edição do que `executive`.

Caso um diário estadual futuro reúna os três poderes, a mudança é barata: a API trata `power` como texto livre (`Optional[str]`), o frontend não usa o campo e só o `gazette_schema.json` valida o enum.

**Data inicial: D1.** `start_date = date(2003, 3, 17)`.

Justificativa: é a convenção dos raspadores do Querido Diário (a data da primeira edição disponível), e os PDFs de 2003 têm texto nativo, então o acervo antigo não muda o custo de processamento. O acervo tem lacunas em 2003 (de agosto a dezembro) e em junho de 2005, o que não atrapalha: dia sem edição custa uma requisição JSON pequena. Para o piloto e para os experimentos do TCC, o período coletado é limitado pelos argumentos `start` e `end` do spider, sem mexer no `start_date`.

**Ritmo de requisições: E2.** `custom_settings = {"DOWNLOAD_DELAY": 0.5, "RANDOMIZE_DOWNLOAD_DELAY": True}`.

Justificativa: o servidor respondeu sem erros a 8 requisições concorrentes, então o padrão do Scrapy funcionaria. Mas a concorrência não acelerou o download dos PDFs no teste (o volume por segundo ficou igual e cada download ficou 8 vezes mais lento), e o servidor é o mesmo que atende o `es_serra` e o portal público do DIO. O intervalo de 0,5 s custa pouco na coleta diária, de uma ou duas edições, e mantém a carga baixa numa coleta histórica de mais de vinte anos.

## Prós e Contras das Alternativas

| Alternativa | Prós | Contras |
| -------- | -------- | -------- |
| A1 — Spider próprio sobre o HTML | Nenhum | Reescreve o que a base já faz; o portal monta a página por JavaScript a partir da mesma API |
| A2 — Herdar de `BaseDionetSpider` (escolhida) | Spider de poucas linhas; base já testada em cinco municípios; mesma API usada pelo `es_serra` | Depende de uma API interna do portal, sem documentação pública |
| B1 — PDF completo, sem subtemas (escolhida) | Nenhum código novo; preserva o documento oficial e seu checksum; sem requisições extras | Atos municipais ficam indexados sob o território do estado até existir segmentação |
| B2 — Recortar o PDF na coleta | Índice do estado só com atos estaduais | Manipulação de PDF no spider; arquivo deixa de ser o documento assinado; uma requisição a mais por edição; só funciona de 2015 em diante, onde há árvore de seções |
| B3 — Segmentar no processamento | Solução correta: reatribui cada ato ao seu município | Esforço alto; mexe no `querido-diario-data-processing`; fora do escopo do TCC |
| B4 — Descartar extras só municipais | Menos arquivos irrelevantes para o estado | Uma requisição a mais por edição extra; ganho pequeno (arquivos de 2 páginas); não resolve o caderno nas edições normais |
| C1 — `executive`, schema intacto (escolhida) | Nenhuma mudança de contrato; descreve quem publica o diário | Não sinaliza os atos avulsos de outros poderes |
| C2 — `executive_legislative` | Valor já existente no enum | Impreciso: o Legislativo é 0,3% das matérias e tem diário próprio |
| C3 — Novo valor no enum | Explícito quanto ao Judiciário | Muda um schema compartilhado por causa de 0,1% das matérias; continua sendo um rótulo por edição, e não por ato |
| D1 — `start_date` em 17/03/2003 (escolhida) | Cobre todo o acervo disponível; segue a convenção do projeto | Coleta histórica maior (2.996 edições até 2015 e, por estimativa, cerca de 5.700 no total); lacunas em 2003 e 2005 |
| D2 — `start_date` em 2014 | Coincide com a matriz comparativa | Descarta 11 anos de diários disponíveis, sem motivo técnico |
| D3 — `start_date` em 25/05/2020 | Formato homogêneo; todas as edições com árvore de seções | Descarta 17 anos de acervo |
| E1 — Padrão do Scrapy | Listagem histórica mais rápida | Sem ganho no download dos PDFs; carga maior num servidor compartilhado com outros diários |
| E2 — `DOWNLOAD_DELAY` 0,5 s (escolhida) | Carga baixa e previsível; suficiente para a coleta diária | Coleta histórica completa mais lenta |
