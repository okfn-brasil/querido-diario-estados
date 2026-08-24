# 0003. Manter Scrapy como framework de raspagem
Data: 24/08/2026
Status: Aceito

## Contexto e Declaração do Problema
O `querido-diario` já possui 447 spiders ativos construídos sobre Scrapy (`scrapy==2.14.2`, confirmado em `pyproject.toml`), com abstrações próprias território-agnósticas (`BaseGazetteSpider`, item `Gazette`, pipelines, persistência, scheduler e monitores via Spidermon).

Com a expansão para diários oficiais estaduais, surgem exigências novas de raspagem que o padrão municipal não cobria: sites estaduais mais heterogêneos, possível necessidade de JavaScript/SPA em alguns casos e volumes distintos por UF. É preciso decidir se a expansão estadual continua usando Scrapy ou se adota outro framework/abordagem de coleta (ex.: Playwright/Selenium como base, ou uma solução própria) para lidar com esses casos mais adversos.

## Fatores Determinantes da Decisão
- Reaproveitamento de código e conhecimento já existente (~90% do framework é território-agnóstico)
- Preferência explícita do time/projeto por Scrapy (requisito 12 do levantamento)
- Maturidade e estabilidade do framework em produção (447 spiders já rodando)
- Necessidade eventual de lidar com sites estaduais mais complexos (SPA, bloqueios de robots.txt)

## Alternativas Consideradas
- Adotar um framework diferente (ex.: baseado em Playwright/Selenium) como padrão para os novos spiders estaduais
- Manter Scrapy como framework único, usando extensões do próprio ecossistema Scrapy (ex.: `scrapy-playwright`) apenas nos casos pontuais que exigirem renderização de JavaScript
- Adotar uma solução híbrida com múltiplos frameworks de coleta convivendo lado a lado, sem padrão único

## Alternativa Escolhida
Opção escolhida: Manter Scrapy como framework único de raspagem para os spiders estaduais, reaproveitando as abstrações já existentes (`BaseGazetteSpider`, pipelines, monitores Spidermon), recorrendo a extensões do próprio Scrapy quando um caso específico exigir renderização de JavaScript.

Justificativa: Trocar de framework de raspagem não resolve nenhum dos requisitos priorizados pelo TCC (elasticidade, manutenibilidade, robustez) e jogaria fora ~90% do código já validado em produção. A preferência por Scrapy já está formalizada como requisito do projeto, e os casos mais adversos identificados na matriz comparativa do Sudeste (RJ/SP, MG) são tratáveis com extensões do próprio ecossistema Scrapy, sem justificar a adoção de um framework paralelo.

## Prós e Contras das Alternativas

| Alternativa | Prós | Contras |
| -------- | -------- | -------- |
| Framework alternativo (Playwright/Selenium como base) | Lida nativamente com SPA e JavaScript pesado | Descarta o reaproveitamento de ~90% do framework atual; exige reescrever pipelines, persistência e monitoramento já validados; contraria requisito explícito de preferência por Scrapy |
| Scrapy único, com extensões pontuais para JS (escolhida) | Reaproveita todo o framework existente e o conhecimento do time; mantém um único padrão de manutenção; extensões cobrem os poucos casos de SPA sem exigir novo framework | Extensões de renderização (ex. `scrapy-playwright`) adicionam dependência e custo de execução nos spiders que precisarem delas |
| Múltiplos frameworks convivendo sem padrão único | Flexibilidade máxima por estado/caso | Fragmenta ainda mais a manutenção (contraria requisito 14, de simplificar contribuição); duplica esforço de pipelines, testes e monitoramento por framework |
