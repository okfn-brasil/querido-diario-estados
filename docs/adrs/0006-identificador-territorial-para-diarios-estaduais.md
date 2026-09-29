# 0006. Identificador territorial (`territory_id`) para diários do governo estadual
Data: 29/09/2026
Status: Aceito

## Contexto e Declaração do Problema
A expansão do Querido Diário para diários oficiais estaduais (ADR-0005) exige que cada diário raspado seja associado a um `territory_id`, campo hoje obrigatório e validado como uma string numérica de exatamente 7 dígitos (`ScrapedGazetteBody.territory_id`, no `querido-diario-api`). Esse formato segue o padrão oficial do IBGE para municípios: 2 dígitos de UF, 4 dígitos de município dentro da UF e 1 dígito verificador (ex.: Belo Horizonte = `3106200`).

O diário oficial do governo estadual, no entanto, não pertence a um município específico e não possui um código IBGE de 7 dígitos correspondente. Era necessário decidir como representar esse território dentro do formato existente, sem quebrar a validação atual da API nem o restante do pipeline de coleta e processamento, que também depende de `territory_id` (segmentação, pipelines do spider, índice de busca).

Durante a investigação, foi levantada a hipótese de reaproveitar o padrão `UF` + `00000` (2 dígitos de UF preenchidos com 5 zeros) como identificador do governo estadual, por parecer, à primeira vista, uma sequência livre: nenhum município real usa `0000` como os 4 dígitos centrais do código, já que a numeração municipal dentro de cada UF nunca começa em zero.

Uma checagem direta em `querido-diario/data_collection/gazette/resources/territories.csv` mostrou que esse padrão **já está em uso** para outra finalidade: ele identifica o Diário Oficial dos Municípios, publicado pela associação civil de municípios de cada estado (uma entidade real e distinta do governo estadual). Exemplos já cadastrados:

```
2700000,Associação dos Municípios Alagoanos,AL,Alagoas
3200000,Associação dos Municípios do Espírito Santo,ES,Espírito Santo
```

O caso de Alagoas já está inclusive conectado a um spider ativo e a um segmentador dedicado:

```python
# querido-diario/data_collection/gazette/spiders/al/al_associacao_municipios.py
class AlAssociacaoMunicipiosSpider(BaseSigpubSpider):
    name = "al_associacao_municipios"
    TERRITORY_ID = "2700000"
```

```python
# querido-diario-data-processing/segmentation/factory.py
territory_to_segmenter_class = {
    "2700000": "ALAssociacaoMunicipiosSegmenter",
}
```

Ou seja, apesar de `UF00000` não ser um código oficial do IBGE, é uma convenção já estabelecida pelo próprio Querido Diário, e usá-la novamente para o governo estadual criaria uma colisão de significado dentro do próprio sistema (o mesmo valor passaria a representar duas entidades diferentes, a associação de municípios e o governo do estado).

## Fatores Determinantes da Decisão
- Não quebrar a validação atual da API (`territory_id` obrigatório, 7 dígitos numéricos)
- Não colidir com convenções já existentes e ativas no sistema (caso `UF00000`)
- Baixo esforço de implementação para viabilizar o piloto do Espírito Santo
- Clareza para futuros contribuidores, evitando confundir o identificador com um código IBGE oficial
- Manutenibilidade e nomes claros nos registros de gazettes exibidos na API
- Escalabilidade da convenção para os demais estados (27 UFs no total, o que deixa muitas sequências livres dentro do espaço de 4 dígitos)

## Alternativas Consideradas
- Opção A: Reaproveitar o formato de 7 dígitos, usando `UF` + um sufixo numérico livre, preenchido com `9` (ex.: `3299999` para o Espírito Santo), reservado explicitamente para o governo do estado
- Opção B: Usar apenas o código de UF de 2 dígitos (ex.: `32`) como `territory_id`, sem completar para 7 dígitos
- Opção C: Tornar `territory_id` opcional (`null`) para diários que não pertencem a um município específico, introduzindo um sinal explícito de "nível estadual" no lugar de um número

## Alternativa Escolhida
Opção escolhida: Opção A — usar `UF` + sufixo preenchido com `9` (ex.: `3299999` para o Espírito Santo) como `territory_id` do governo estadual.

Justificativa: Essa opção não exige nenhuma mudança na validação da API, no schema do índice de busca, no modelo de resposta (`GazetteItem`, `City`) nem no pipeline dos spiders, pois todos continuam recebendo uma string de 7 dígitos, exatamente como esperam hoje. O preenchimento com `9`, em vez de `0`, foi escolhido deliberadamente para diferenciar visualmente esse padrão do já usado para associações de municípios (`UF00000`), reduzindo o risco de confusão entre as duas convenções ao ler o código ou a documentação. Como o Brasil tem menos de 30 UFs, o espaço de 4 dígitos livres é grande o suficiente para reservar uma sequência fixa por estado sem risco de esgotamento ou de conflito entre estados.

Essa alternativa é reconhecidamente uma solução de curto prazo: ela reaproveita um formato pensado para municípios para representar uma entidade de natureza diferente, o que só funciona porque o valor é tratado como um identificador opaco pelo sistema, não como um código IBGE interpretado semanticamente. Por isso, a Opção C — tornar `territory_id` opcional e introduzir um sinal explícito de nível territorial — fica registrada como direção futura preferencial, a ser retomada com mais tempo e, idealmente, discutida com outros contribuidores do ecossistema antes de ser aplicada, já que exigiria mudanças coordenadas na API, no índice de busca e no modelo de resposta.

Fica registrada também a sugestão de que essa mesma decisão — e a convenção `UF00000` para associações de municípios que a motivou — sejam formalizadas em uma ADR própria em outro repositório do ecossistema (provavelmente `querido-diario` ou `querido-diario-api`, onde o formato de `territory_id` é definido e validado). Hoje essa convenção existe apenas implicitamente no código e nos dados (`territories.csv`, `factory.py`), sem nenhuma decisão arquitetural documentada, o que dificulta a vida de futuros contribuidores que precisarem entender por que certos `territory_id` não correspondem a municípios reais.

## Prós e Contras das Alternativas

| Alternativa | Prós | Contras |
| -------- | -------- | -------- |
| Opção A — `UF` + sufixo `9` (escolhida) | Nenhuma mudança na validação da API, no índice de busca ou no modelo de resposta; baixo esforço; reaproveita a segmentação existente sem mudança estrutural; espaço de sufixos suficiente para as 27 UFs; visualmente distinguível da convenção `UF00000` já em uso | É uma convenção do próprio Querido Diário, não um código IBGE oficial; ainda "finge" ser um `territory_id` de 7 dígitos, exigindo documentação clara para não ser confundido com um código real |
| Opção B — código de UF puro (2 dígitos) | Semanticamente mais transparente, sem fingir ser um código municipal | Quebra a validação atual (`min_length`/`max_length`/regex de `ScrapedGazetteBody.territory_id`); exige mudanças coordenadas na API, no índice de busca e possivelmente no modelo de resposta; maior esforço e mais pontos de mudança simultânea |
| Opção C — `territory_id` opcional/nulo | Mais correta a longo prazo; introduz um sinal explícito de nível territorial em vez de um número arbitrário; caminho mais alinhado a uma representação limpa de "diário sem município associado" | Maior esforço; depende de mudanças na API que não bloqueiam o piloto atual; exige coordenação com outros mantenedores do ecossistema antes de ser aplicada |
