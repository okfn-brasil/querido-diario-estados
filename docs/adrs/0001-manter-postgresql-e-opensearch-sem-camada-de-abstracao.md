# 0001. Manter PostgreSQL e OpenSearch, sem camada de abstração
Data: 24/08/2026
Status: Aceito

## Contexto e Declaração do Problema
A arquitetura atual do ecossistema Querido Diário depende estruturalmente de PostgreSQL (via CloudNativePG, três bancos distintos) e OpenSearch (índice central de busca), conforme já formalizado nas ADR-002, ADR-003 e ADR-008 do repositório `querido-diario-deployment`. Não existe hoje nenhuma camada de abstração de persistência ou de indexação: backend, API e pipeline de processamento acessam essas tecnologias diretamente.

Com a expansão para cobertura estadual, surge a pergunta se essa dependência deveria ser revista — por exemplo, introduzindo uma camada de abstração que permitisse trocar o banco relacional ou o motor de busca/índice no futuro, ou avaliando motores alternativos de menor custo operacional (ex.: para o problema de custo do índice OpenSearch, hoje ~400GB). Precisamos decidir se essa revisão entra no escopo do TCC.

## Fatores Determinantes da Decisão
- Escopo do TCC (foco em elasticidade, manutenibilidade e robustez, não em reengenharia de persistência)
- Custo/benefício de uma migração ou de uma camada de abstração nesta fase
- Risco de regressão em funcionalidades já estáveis (busca textual, agregações, API)
- Tempo disponível no cronograma da expansão estadual

## Alternativas Consideradas
- Introduzir uma camada de abstração de storage/índice que permita substituir PostgreSQL e/ou OpenSearch por outros motores no futuro
- Avaliar e migrar para um motor de busca/índice alternativo de menor custo operacional
- Manter PostgreSQL e OpenSearch exatamente como estão, sem qualquer camada de abstração, nesta fase do projeto

## Alternativa Escolhida
Opção escolhida: Manter PostgreSQL e OpenSearch como estão, sem introduzir camada de abstração de storage ou índice.

Justificativa: A substituição ou abstração dessas tecnologias está fora do escopo do TCC. O diagnóstico do levantamento de requisitos não aponta essa dependência como um problema a ser resolvido nesta fase — os esforços de elasticidade, robustez e custo serão direcionados a outros pontos do sistema (autoscaling, tiering de storage, decomposição do pipeline em filas), sem exigir troca de banco ou de motor de busca. Introduzir uma camada de abstração agora adicionaria complexidade e risco sem entregar valor dentro do prazo do TCC.

## Prós e Contras das Alternativas

| Alternativa | Prós | Contras |
| -------- | -------- | -------- |
| Introduzir camada de abstração | Facilita troca futura de banco/índice; reduz acoplamento | Esforço de implementação alto; fora do escopo e do prazo do TCC; risco de regressão em funcionalidades estáveis |
| Migrar para motor de busca/índice alternativo | Pode reduzir custo operacional do índice (~400GB) | Migração de dados arriscada; exige revalidação de toda a superfície de busca já contratada pela API; fora do escopo do TCC |
| Manter PostgreSQL e OpenSearch como estão (escolhida) | Sem risco de regressão; preserva contrato de busca e API já validado; foco do TCC permanece em elasticidade/robustez/custo de infraestrutura | Mantém acoplamento direto às duas tecnologias; não resolve o custo estrutural do índice OpenSearch single-node (tratado por outras frentes, como tiering e dimensionamento, não substituição) |
