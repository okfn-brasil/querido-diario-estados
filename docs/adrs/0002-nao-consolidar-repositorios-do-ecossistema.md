# 0002. Não consolidar os repositórios do ecossistema Querido Diário
Data: 24/08/2026
Status: Aceito

## Contexto e Declaração do Problema
O ecossistema Querido Diário está hoje fragmentado em 6 repositórios (coleta, processamento, API, backend, deployment, frontend), cada um com ciclo de release e governança independentes. Essa fragmentação foi citada no próprio levantamento de requisitos como uma dificuldade para novos contribuidores, que precisam entender múltiplos repositórios com pouca integração explícita entre eles.

Com a criação do `querido-diario-estados` para a expansão estadual, é preciso decidir se esse é o momento de reduzir a fragmentação — por exemplo, fundindo repositórios relacionados (como coleta municipal e estadual) em um monorepo, ou se a expansão deve simplesmente seguir o padrão já estabelecido, criando mais um repositório independente.

## Fatores Determinantes da Decisão
- Manutenibilidade e facilidade de contribuição
- Escopo e prazo do TCC
- Risco de quebrar pipelines de CI/CD e processos de release já estabelecidos nos repositórios existentes
- Reaproveitamento do framework de coleta já existente (~90% do `querido-diario` é território-agnóstico)

## Alternativas Consideradas
- Fundir o novo código de coleta/processamento estadual nos repositórios municipais existentes (`querido-diario`, `querido-diario-data-processing`)
- Consolidar todo o ecossistema em um monorepo único
- Criar o `querido-diario-estados` como um novo repositório independente, seguindo o esqueleto padrão do ecossistema, sem alterar a organização dos repositórios existentes

## Alternativa Escolhida
Opção escolhida: Manter os repositórios existentes como estão e criar `querido-diario-estados` como um novo repositório independente.

Justificativa: O ganho de manutenibilidade identificado no diagnóstico vem de documentação e integração mais explícita entre os repositórios, não de reorganização estrutural. Fundir repositórios ou migrar para um monorepo é uma mudança de alto risco e esforço, que impactaria pipelines de CI/CD e processos de release já validados, sem relação direta com os objetivos de elasticidade, manutenibilidade e robustez do TCC. O novo repositório seguirá o esqueleto padrão do ecossistema (README/CONTRIBUTING/CODE_OF_CONDUCT/SUPPORT bilíngue, ADRs no padrão MADR) e referenciará a documentação central em vez de duplicá-la.

## Prós e Contras das Alternativas

| Alternativa | Prós | Contras |
| -------- | -------- | -------- |
| Fundir com repositórios municipais existentes | Reaproveitamento direto de código e CI já configurado | Acopla o código estadual ao ciclo de release municipal; risco de regressão nos spiders/pipelines já em produção |
| Monorepo único para todo o ecossistema | Máxima integração e visibilidade entre componentes | Reorganização de altíssimo esforço e risco; fora do escopo e do prazo do TCC; impacta 6 times/fluxos de release simultaneamente |
| Novo repositório independente, seguindo o padrão (escolhida) | Baixo risco; reaproveita ~90% do framework via dependência/cópia controlada; mantém ciclos de release isolados; documentação resolve a queixa de fragmentação sem reorganização | Mantém a fragmentação em 6 repositórios; integração entre eles continua dependendo de disciplina de documentação, não de estrutura |
