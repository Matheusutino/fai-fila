# Validação da demonstração

Este documento registra o que foi executado em **2 e 3 de novembro de 2026**. Para repetir os testes, siga [Testes e exemplos](testes.md).

## Cobertura e resultados

| Verificação | Resultado | Escopo |
| --- | --- | --- |
| Suíte com PostgreSQL e RabbitMQ, em 02/11 | 43 testes passaram | Versão anterior à inclusão de dois testes de visualização de arquivos |
| Suíte local com SQLite, em 03/11 | 43 passaram e 2 opcionais ignorados | 45 testes coletados na versão com visualização de arquivos |
| Corpus pela API, fila e worker | 16 de 16 decisões esperadas | Elasticsearch e OpenWebUI reais, 3 referências |
| Recuperação da origem | 13 de 13 consultas com origem conhecida | Inclui o recibo com campos insuficientes |
| Campos estruturados | 96 de 96 coincidiram com o gabarito | 6 campos por consulta; strings normalizadas na avaliação |
| Navegador Chrome | Passou | Upload, reset ao recarregar, consulta manual, PDFs, imagens e layout mobile |
| Aprovação e reuso | Passou | Verificação, indexação autenticada, idempotência e reenvio sinalizado |
| Ruff e sintaxe JavaScript | Passaram | Código Python e JavaScript |
| Configuração do Compose | Passou | Validação estrutural; containers não executados |

A suíte automatizada simula Elasticsearch e OpenWebUI; o teste de corpus exercitou esses serviços separadamente pela pipeline real. As quantidades acima se referem às execuções indicadas, não a uma nova rodada completa após cada alteração de documentação.

No teste atual do navegador, F5 limpa formulário, acompanhamento e resultado, mesmo com um token salvo pela versão antiga. A consulta de uma análise anterior só ocorre após informar o token e clicar em **Consultar**. Também foram verificados o versionamento dos assets, a recuperação da lista após HTTP 503 e o carregamento com armazenamento local bloqueado.

## Como interpretar a avaliação do corpus

Os 16 casos e suas expectativas estão descritos em [Testes e exemplos](testes.md). Na última rodada completa, os textos reais já extraídos foram reaproveitados pelo cache de hash. A LLM, a recuperação e as regras foram executadas novamente. Rodadas anteriores exercitaram o OCR de PDFs e imagens no OpenWebUI.

O manifesto não alimentou os campos extraídos, o índice de campos nem a decisão. Os resultados pertencem a uma base pequena de três referências e não estimam a precisão em documentos de produção.

O teste de aprovação usou um ID temporário e removeu somente o documento que criou no índice. As três referências originais foram preservadas.

## Evidências locais

Os arquivos abaixo são gerados no ambiente da demonstração e ignorados pelo Git. Os links estarão disponíveis onde esses artefatos existirem.

| Evidência | Arquivo |
| --- | --- |
| Relatório final do corpus | [evaluation-final.json](../var/evaluation-final.json) |
| Campos verdadeiros e relação entre documentos | [manifest.json](../fixtures/manifest.json) |
| Página no desktop e mobile | [desktop](../artifacts/desktop.png), [mobile](../artifacts/mobile.png) |
| Visualizador de PDFs | [desktop](../artifacts/pdf-viewer-desktop.png), [mobile](../artifacts/pdf-viewer-mobile.png) |
| Ciclo de aprovação | [approval.log](../var/approval.log) |

Rodadas de diagnóstico anteriores foram preservadas em `var/evaluation-initial.json`, `var/evaluation-before-cache.json` e `var/evaluation-cached-recheck.json`. Elas registram falhas anteriores aos ajustes de extração e cache; o relatório final é a referência para o resultado de 16/16.

## Ambiente utilizado

| Componente | Versão ou configuração usada |
| --- | --- |
| Python | 3.12 |
| OpenWebUI | 0.11.0, com OCR/Docling já configurado |
| Elasticsearch | 9.5.5 |
| PostgreSQL local | 16.15 |
| RabbitMQ local | 3.12.1 |
| LLM de extração na avaliação final | `deepseek/deepseek-v4-flash-0731` |
| Orçamento de saída | 4096 tokens, com `reasoning.effort=none` |
| Embeddings | MiniLM multilíngue, CPU, 384 dimensões |

PostgreSQL e RabbitMQ foram executados em diretórios locais no chope, sem instalação como serviços do sistema. A aplicação foi executada em Python. **O Dockerfile não foi construído nem executado nesta validação**, por falta de acesso ao daemon durante a preparação. As imagens PostgreSQL 17 e RabbitMQ 4 do Compose ainda precisam de validação em containers.

A integração com o evento real de aprovação do FAIWeb permanece pendente. O que foi validado é o contrato e o ciclo de indexação por meio do teste autenticado.
