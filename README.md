# FAI Fila

Serviço para verificar possíveis recibos duplicados em solicitações de prestação de contas. A aplicação recebe um PDF ou uma imagem, devolve um token de acompanhamento e processa a análise em segundo plano com RabbitMQ e um worker.

O worker usa o OCR/Docling já configurado no OpenWebUI, extrai os campos com uma LLM, busca recibos semelhantes no Elasticsearch e compara valor, data, estabelecimento e identificador. A página web permite enviar arquivos, acompanhar a tarefa e visualizar os PDFs originais da demonstração.

## Formas de execução

Há dois modos de execução:

| Modo | Situação | Como iniciar |
| --- | --- | --- |
| Python no chope | Usado e validado na demonstração | `.venv/bin/python -m scripts.dev_stack start` |
| Docker Compose | Arquivos preparados; build e execução ainda não validados | `docker compose up --build -d` após configurar o ambiente |

O [Dockerfile](Dockerfile) define a imagem da aplicação. O [compose.yaml](compose.yaml) usa essa imagem para API, publicador e worker, além de iniciar PostgreSQL e RabbitMQ. **Elasticsearch e OpenWebUI são serviços externos nos dois modos.** O projeto não instala outro Docling.

## Acessar a demonstração no chope

O ambiente já preparado utiliza `.venv`, `.env` e serviços locais. No terminal conectado ao servidor:

```bash
cd /exp/utinomatheus/fai-fila
.venv/bin/python -m scripts.dev_stack start
.venv/bin/python -m scripts.dev_stack status
```

Esse comando inicia API, publicador e worker. Banco, RabbitMQ, Elasticsearch e OpenWebUI precisam estar disponíveis.

Em outro terminal, **no seu computador**, mantenha o túnel SSH aberto:

```bash
ssh -N -o ExitOnForwardFailure=yes -L 8010:127.0.0.1:8010 chope
```

Abra **http://localhost:8010**. A documentação interativa da API fica em **http://localhost:8010/docs**.

Para preparar outro ambiente, consultar logs ou recuperar uma dependência, siga o [guia de execução](docs/execucao.md).

## Experimentar

1. Escolha um exemplo de teste na página e clique em **Usar**, ou envie seu arquivo PDF, JPEG ou PNG.
2. Clique em **Verificar duplicidade** e acompanhe as etapas da tarefa.
3. Confira a comparação dos campos e abra os PDFs originais dos candidatos de demonstração.

Os resultados possíveis são **possível duplicidade**, **nenhuma duplicidade encontrada** e **análise inconclusiva**. A conclusão considera somente os candidatos recuperados da base.

**F5 limpa a página.** Para consultar uma análise anterior, guarde o token e informe-o em **Retomar uma análise**.

## Documentação

| Quero… | Guia |
| --- | --- |
| Executar em Python ou acessar pelo SSH | [Execução](docs/execucao.md) |
| Entender e executar os containers | [Docker](docs/docker.md) |
| Preencher o `.env` | [Configuração](docs/configuracao.md) |
| Entender a fila, o RAG e as regras | [Arquitetura](docs/arquitetura.md) |
| Integrar o FAIWeb à API | [API](docs/api.md) |
| Gerar documentos e repetir os testes | [Testes e exemplos](docs/testes.md) |
| Conferir o que foi validado | [Validação](docs/VALIDACAO.md) |

O [índice de docs](docs/README.md) reúne todos os guias.

## Onde estão os arquivos

```text
app/                     API, persistência, fila, worker e integrações
frontend/                Página HTML, CSS e JavaScript
scripts/                 Execução local, geração de exemplos e avaliação
fixtures/reference/      3 PDFs originais usados como base
fixtures/queries/        16 arquivos de teste, incluindo cópias e alterações
fixtures/manifest.json   Relação dos exemplos e gabarito
var/uploads/             Arquivos enviados na execução local
artifacts/               Capturas dos testes de navegador
tests/                   Testes automatizados
docs/                    Documentação do serviço
fai-elasticsearch/       Projeto original usado como referência
```

Os recibos de teste, relatórios e capturas são gerados localmente e não são versionados. A pasta `fai-elasticsearch/` contém o projeto de referência; ela não precisa ser executada para iniciar este serviço.

## Verificação e cadastro são etapas diferentes

O upload verifica duplicidade e guarda a tarefa, mas **não adiciona o recibo ao índice de referências**. Depois de aprovar o recibo, o backend do FAIWeb deve chamar uma rota autenticada que agenda sua indexação. Assim, um envio futuro pode detectar o reuso do documento.

A demonstração já oferece essa rota e um teste do ciclo completo. A integração com o evento real de aprovação do FAIWeb ainda precisa ser feita. As regras e os documentos sintéticos servem para demonstrar a arquitetura; a aplicação ainda não inclui autenticação de usuários e organizações nem política de retenção dos arquivos.
