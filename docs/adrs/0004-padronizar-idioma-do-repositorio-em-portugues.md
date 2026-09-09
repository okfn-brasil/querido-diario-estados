# 0004. Padronizar o idioma do repositório em português
Data: 09/09/2026
Status: Aceito

## Contexto e Declaração do Problema
O `querido-diario-estados` é um projeto brasileiro, voltado principalmente para o público brasileiro, e a aplicação do Querido Diário utiliza o português como idioma de sua interface. A documentação em arquivos Markdown é uma das principais portas de entrada do projeto: ela deve permitir que pessoas interessadas compreendam sua proposta e arquitetura sem exigir conhecimento detalhado de inglês ou do funcionamento interno de cada componente.

Os demais repositórios do ecossistema não apresentam um padrão único para o idioma de sua documentação, branches e pull requests. Essa falta de consistência dificulta a definição de uma convenção para novas contribuições. Como parte do TCC, o repositório também deve demonstrar boas práticas de engenharia de software, incluindo organização, documentação e versionamento claros e previsíveis.

É necessário decidir se o idioma das comunicações e dos artefatos de colaboração será deixado livre, se serão aceitos múltiplos idiomas sob regras de consistência ou se o repositório adotará o português como padrão.

## Fatores Determinantes da Decisão
- Público principal brasileiro e aplicação voltada ao contexto brasileiro
- Acessibilidade da documentação para pessoas que precisam de uma visão menos granular do projeto
- Consistência entre documentação, branches e pull requests
- Organização, documentação e versionamento como práticas de engenharia de software demonstradas pelo TCC
- Ausência de um padrão de idioma consistente nos demais repositórios do ecossistema
- Impacto sobre contribuições de pessoas estrangeiras

## Alternativas Consideradas
- Deixar o idioma livre para cada pessoa autora de documentação, branch ou pull request
- Permitir mais de um idioma, desde que cada contribuição mantenha consistência entre o nome da branch, o título e a descrição do pull request e os arquivos de documentação relacionados
- Padronizar o português como idioma dos textos humanos do repositório, incluindo documentação Markdown, branches, títulos e descrições de pull requests

## Alternativa Escolhida
Opção escolhida: Padronizar o português como idioma do conteúdo textual do repositório.

A documentação em arquivos Markdown, os nomes de branches, os títulos e as descrições de pull requests devem ser escritos em português. Prefixos convencionais de versionamento, como `feat`, `fix`, `docs`, `refactor` e `chore`, podem ser mantidos em sua forma original nos nomes de branches e títulos de pull requests, desde que a descrição que os acompanha esteja em português. Issues, comentários de revisão e demais textos de colaboração também devem seguir essa convenção sempre que forem produzidos pelo projeto.

A decisão não se aplica a identificadores técnicos que precisem seguir uma convenção externa ou já existente, como nomes de classes, funções, variáveis, endpoints, campos de API, comandos, nomes de bibliotecas, arquivos exigidos por ferramentas e termos técnicos consagrados. Nesses casos, a nomenclatura original deve ser preservada para manter compatibilidade com o código e com o ecossistema utilizado.

Justificativa: O português torna a documentação mais acessível ao público principal e cria uma convenção única para a colaboração. A padronização também transforma a ausência de consistência observada nos demais repositórios em uma oportunidade de aplicar boas práticas de organização, documentação e versionamento no repositório estadual. Embora a regra exija esforço adicional de adoção e possa limitar contribuições de pessoas estrangeiras que não dominem português, esses custos são considerados aceitáveis diante da clareza e da consistência obtidas no contexto do projeto e do TCC.

## Prós e Contras das Alternativas

| Alternativa | Prós | Contras |
| -------- | -------- | -------- |
| Idioma livre | Menor esforço inicial; permite que cada pessoa contribua no idioma em que se sente mais confortável | Mistura de idiomas; reduz a consistência da documentação e da colaboração; dificulta a leitura por parte do público brasileiro; não estabelece uma prática de organização reproduzível |
| Mais de um idioma com regras de consistência | Pode ampliar a participação de pessoas estrangeiras; preserva consistência dentro de cada contribuição | Exige definir e fiscalizar regras adicionais; aumenta o esforço de manutenção; pode gerar documentação fragmentada; mantém a necessidade de decidir qual idioma usar em cada contexto |
| Português como padrão (escolhida) | Facilita a entrada do público brasileiro; mantém documentação, branches e pull requests coerentes; demonstra boas práticas de engenharia de software no TCC; estabelece uma convenção simples para o projeto | Pode limitar contribuições de pessoas estrangeiras que não falem português; exige esforço adicional para aplicar a regra; diverge de convenções comuns de nomes técnicos e documentação em inglês, que continuam sendo preservadas quando necessárias |
