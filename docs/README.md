# Documentação do FAI Fila

O [README do projeto](../README.md) apresenta o serviço e como executá-lo. Os guias abaixo detalham cada parte sem misturar instalação, contrato da API e resultados de teste.

| Guia | Conteúdo |
| --- | --- |
| [Execução](execucao.md) | Iniciar em Python, acessar pelo SSH, consultar logs e resolver problemas comuns |
| [Docker](docker.md) | O que cada container faz, configuração, volumes e comandos do Compose |
| [Configuração](configuracao.md) | Variáveis de ambiente, prioridades e valores padrão |
| [Arquitetura](arquitetura.md) | Fluxo assíncrono, OCR, recuperação, regras e persistência |
| [API](api.md) | Upload, consulta por token, arquivos e indexação após aprovação |
| [Testes e exemplos](testes.md) | Gerar o corpus, carregar referências e executar testes |
| [Validação](VALIDACAO.md) | Resultados obtidos, evidências e limites da avaliação |
| [Ambiente do chope](ambiente-chope.md) | Iniciar e acessar a demo pelo SSH; recuperar o PostgreSQL e o RabbitMQ locais |

## Por onde começar

- **Vou usar a demo no chope:** siga [Ambiente do chope](ambiente-chope.md).
- **Vou instalar em outra máquina:** preencha a [Configuração](configuracao.md) e escolha [Python](execucao.md#instalação-em-outro-ambiente) ou [Docker](docker.md).
- **Vou integrar ao FAIWeb:** leia o [fluxo da arquitetura](arquitetura.md) e o [contrato da API](api.md).

Todos os comandos dos guias partem da raiz de `fai-fila`, exceto quando o texto indica o terminal do seu computador. Os endereços do chope descrevem a demonstração preparada; não são requisitos fixos para outra instalação.
