# 0007. Branches `main-estados` nos repositórios existentes do ecossistema
Data: 06/10/2026
Status: Proposto

## Contexto e Declaração do Problema
A ADR-0002 decidiu não consolidar os repositórios do ecossistema Querido Diário e criar o `querido-diario-estados` como um novo repositório independente, que concentra documentação, ADRs, simulador e resultados do TCC. Essa decisão, porém, não resolve onde fica o **código** da expansão estadual que precisa morar dentro dos repositórios já existentes: o raspador do diário estadual do Espírito Santo (ADR-0005) depende do framework de coleta do `querido-diario`, o `territory_id` estadual (ADR-0006) passa pela API e pelo pipeline de processamento, e a fila de extração elástica precisa ser implementada dentro do `querido-diario-data-processing` e implantada pelo `querido-diario-deployment`.

Copiar esse código para dentro do `querido-diario-estados` contrariaria a própria justificativa da ADR-0002 (reaproveitar ~90% do framework existente, que é território-agnóstico). Por outro lado, commitar direto na `main` de cada repositório misturaria código experimental do TCC com o ciclo de release municipal e tornaria difícil acompanhar as atualizações do upstream da OKBR.

É preciso, então, definir uma estratégia de branches que permita integrar as funcionalidades novas entre os repositórios, reaproveitando o código atual, sem interferir na `main` oficial de cada um.

## Fatores Determinantes da Decisão
- Reaproveitamento do código já existente em cada repositório (coerência com a ADR-0002)
- Isolamento em relação à `main` oficial e ao ciclo de release municipal
- Facilidade de integração entre funcionalidades novas de repositórios diferentes (coleta, API, processamento, deployment)
- Facilidade de acompanhar as atualizações do upstream da OKBR
- Possibilidade de devolver as contribuições ao upstream via PR quando estiverem estáveis
- Escopo e prazo do TCC

## Alternativas Consideradas
- Opção A: Commitar e abrir PRs diretamente contra a `main` oficial de cada repositório
- Opção B: Manter forks separados de cada repositório, com o código estadual vivendo apenas nos forks
- Opção C: Copiar os trechos necessários de cada repositório para dentro do `querido-diario-estados`
- Opção D: Criar, em cada repositório existente, uma branch de integração `main-estados` derivada da `main` oficial, com branches de funcionalidade abertas contra ela

## Alternativa Escolhida
Opção escolhida: Opção D — manter a `main` oficial intocada e criar uma branch `main-estados` em cada repositório do ecossistema que precisar de mudanças, usada como branch de integração da expansão estadual.

Justificativa: A `main-estados` parte da `main` oficial, então todo o código atual continua disponível sem cópia, que é exatamente o reaproveitamento defendido na ADR-0002. As funcionalidades novas são desenvolvidas em branches próprias (ex.: `tcc/es-estado`, `tcc/fila-extracao`, `tcc/observabilidade`) e integradas via PR na `main-estados`, que passa a representar o estado "integrado" do TCC em cada repositório. Com o mesmo nome de branch em todos os repositórios, fica explícito qual combinação de versões compõe o ambiente estadual: o `querido-diario-deployment` na `main-estados` implanta as imagens geradas a partir das `main-estados` dos demais.

A `main` oficial segue apenas espelhando o upstream. Atualizações da OKBR chegam à `main-estados` por merge (ou rebase) da `main`, e funcionalidades estáveis podem ser propostas ao upstream a partir da `main-estados`, sem que o trabalho em andamento do TCC bloqueie ou contamine o ciclo de release municipal.

O impacto não é igual em todos os repositórios:

- **`querido-diario`, `querido-diario-api` e `querido-diario-deployment`**: mudanças pontuais e aditivas (novo spider estadual, registro do `territory_id` em `territories.csv`, manifestos de implantação), com baixa divergência em relação à `main` oficial.
- **`querido-diario-data-processing`**: mudanças maiores, por conta da implementação da fila de extração (novo pacote `work_queue/`, produtor e consumidor Celery, novos pipelines em `execute_pipeline`). A `main-estados` desse repositório tende a divergir mais da `main` oficial, o que exige sincronizações frequentes com o upstream para evitar conflitos acumulados e torna mais provável que a contribuição ao upstream precise ser dividida em PRs menores.

## Prós e Contras das Alternativas

| Alternativa | Prós | Contras |
| -------- | -------- | -------- |
| Opção A — PRs direto na `main` oficial | Nenhuma divergência; código entra no upstream imediatamente | Acopla o trabalho experimental do TCC ao ciclo de release municipal; depende do ritmo de revisão dos mantenedores; integração entre repositórios fica bloqueada até cada PR ser aceito |
| Opção B — Forks separados | Isolamento total; liberdade para mudanças estruturais | Mais repositórios para manter, contrariando o espírito da ADR-0002; sincronização com upstream e devolução das contribuições ficam mais trabalhosas; código estadual fica menos visível para a comunidade |
| Opção C — Copiar código para o `querido-diario-estados` | Tudo em um único lugar | Duplica código já existente, contrariando a ADR-0002; cópias divergem do upstream rapidamente; dificulta devolver as melhorias à comunidade |
| Opção D — Branch `main-estados` em cada repositório (escolhida) | Reaproveita o código atual sem cópia; `main` oficial intocada; integração das funcionalidades novas via PR em um ponto único por repositório; nome comum deixa explícito o conjunto de versões do ambiente estadual; caminho natural para PRs ao upstream | Exige disciplina para sincronizar a `main-estados` com a `main` oficial; no `querido-diario-data-processing`, a divergência maior (fila de extração) aumenta o risco de conflitos e o esforço de devolver o código ao upstream; depende de permissão para criar branches nos repositórios |
