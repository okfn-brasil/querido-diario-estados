# 0005. Adotar o Sudeste como primeira região e o Espírito Santo como estado piloto
Data: 09/09/2026
Status: Aceito

## Contexto e Declaração do Problema
A expansão do Querido Diário para diários oficiais estaduais precisa validar uma arquitetura de coleta e processamento capaz de atender diferentes portais, formatos de publicação e condições de acesso. O universo inicial de 27 unidades federativas é amplo demais para ser implementado e validado integralmente dentro do prazo disponível para o TCC.

Foi realizado um levantamento dos quatro estados da Região Sudeste como candidatos a uma prova de conceito: São Paulo, Rio de Janeiro, Minas Gerais e Espírito Santo. Para cada estado foram analisados o portal de publicação, o formato dos arquivos, as barreiras de acesso, o volume aparente e os riscos técnico e jurídico da raspagem.

A matriz comparativa mostrou que os estados do Sudeste apresentam desafios diferentes e, por isso, formam uma base relevante para preparar uma arquitetura extensível. São Paulo combina uma SPA em migração com um portal legado e grande acervo; o Rio de Janeiro utiliza um sistema antigo com PDF servido por JavaScript e parâmetros de sessão; Minas Gerais combina uma SPA com um acervo histórico separado e bloqueio formal de crawlers no DSpace; e o Espírito Santo oferece uma estrutura mais simples, com PDF disponível por URL direta previsível.

É necessário definir um recorte inicial que permita entregar uma camada completa, bem implementada e documentada, sem perder a capacidade de expansão futura para os demais estados.

## Fatores Determinantes da Decisão
- Prazo disponível para implementação e validação da prova de conceito
- Necessidade de entregar uma camada completa, incluindo coleta, processamento e integração com a arquitetura proposta
- Escalabilidade e capacidade de reutilizar a solução em outros estados
- Manutenibilidade e clareza da documentação produzida
- Diversidade técnica dos portais estaduais do Sudeste
- Risco técnico de raspagem, especialmente a dependência de SPA, JavaScript, APIs internas ou sistemas legados
- Respeito às políticas de acesso, incluindo `robots.txt`
- Valor da prova de conceito para validar a arquitetura antes de ampliar a cobertura

## Alternativas Consideradas
- Tentar implementar inicialmente os 27 estados e o Distrito Federal
- Escolher estados de diferentes regiões do país desde o início
- Escolher a Região Sudeste como recorte inicial, mas começar diretamente por um estado de maior complexidade técnica, como São Paulo, Rio de Janeiro ou Minas Gerais
- Escolher a Região Sudeste como recorte inicial e o Espírito Santo como primeiro estado piloto, ampliando depois para os demais estados conforme a arquitetura seja validada

## Alternativa Escolhida
Opção escolhida: Limitar a primeira etapa aos quatro estados da Região Sudeste e iniciar a implementação pelo Espírito Santo.

O Espírito Santo foi escolhido como estado piloto porque apresenta o menor risco técnico geral entre os candidatos avaliados. O sistema IOES disponibiliza PDFs em URLs diretas e previsíveis (`/portal/edicoes/download/{id}`), sem autenticação, sem CAPTCHA ou paywall identificados, sem SPA no caminho crítico de leitura e sem `robots.txt` restritivo. A publicação é diária, com edições extras, e o acervo estruturado oferece um recorte suficiente para validar a coleta e o processamento estadual.

A Região Sudeste foi escolhida como recorte inicial por permitir uma entrega limitada, mas representativa. Os quatro estados apresentam diferentes arquiteturas de portal, formatos de acesso e níveis de dificuldade. Assim, a implementação pode começar pelo caso mais simples no Espírito Santo e utilizar os casos de São Paulo, Rio de Janeiro e Minas Gerais como referência para projetar extensões e documentar os desafios de futuras etapas.

Justificativa: Tentar cobrir todos os estados no primeiro ciclo aumentaria o escopo e reduziria a probabilidade de entregar uma solução completa, testada e bem documentada. O recorte regional mantém o foco necessário para o prazo do TCC e, ao mesmo tempo, preserva a escalabilidade da arquitetura para outras unidades federativas. A escolha do Espírito Santo permite validar o fluxo completo sem consumir a maior parte do esforço inicial em engenharia reversa de SPA, APIs internas ou sistemas legados.

Os casos mais complexos do Sudeste podem não revelar todos os gargalos específicos de outros estados ou regiões, como diferentes mecanismos de acesso, formatos de publicação, políticas institucionais e volumes. Esse risco será tratado por meio de pesquisa inicial, registro dos limites conhecidos e documentação dos pontos de extensão. A arquitetura deverá manter componentes e contratos suficientemente desacoplados para que novos estados sejam adicionados sem reescrever o fluxo principal.

## Prós e Contras das Alternativas

| Alternativa | Prós | Contras |
| -------- | -------- | -------- |
| Implementar os 27 estados e o Distrito Federal inicialmente | Maior cobertura territorial desde o começo; permite observar uma variedade ampla de portais | Escopo incompatível com o prazo; aumenta a quantidade de riscos simultâneos; reduz o tempo para testes, documentação e estabilização; pode resultar em uma solução incompleta |
| Escolher estados de diferentes regiões desde o início | Representa mais realidades regionais e pode revelar dificuldades fora do Sudeste | Aumenta a dispersão do esforço; dificulta a comparação entre os candidatos; reduz a profundidade da análise regional e da documentação da prova de conceito |
| Começar por um estado mais complexo do Sudeste | Expõe antecipadamente a arquitetura a SPA, APIs internas, sistemas legados ou acervos fragmentados | Eleva o risco de a primeira entrega ficar concentrada em engenharia reversa; pode atrasar a validação do fluxo completo de coleta e processamento |
| Sudeste como primeira região e Espírito Santo como piloto (escolhida) | Mantém o escopo controlado; permite validar uma camada completa; começa pelo menor risco técnico; oferece estados com desafios diferentes para evolução posterior; favorece escalabilidade, manutenibilidade e documentação | Pode não revelar gargalos específicos de outros estados ou regiões; posterga a cobertura nacional; exige pesquisa e documentação contínuas para orientar as próximas expansões |
