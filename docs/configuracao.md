# Configuração

As variáveis estão documentadas em [.env.example](../.env.example). Mantenha as credenciais em `.env`, fora do versionamento.

## Ordem de prioridade

Na execução Python, a aplicação usa:

1. Variáveis já exportadas no processo.
2. `.env` na raiz de `fai-fila`.
3. `fai-elasticsearch/.env`, apenas para variáveis ainda ausentes.
4. Valores padrão de `app/config.py`, quando disponíveis.

Uma variável definida como vazia continua definida: o fallback da referência não a preenche. Por exemplo, se o `.env` novo contém `OPENWEBUI_API_KEY=`, preencha a chave nele.

No Docker, os valores vêm do `.env` e das substituições explícitas no Compose. A pasta da referência não é copiada para a imagem.

## Conexões

| Variável | Padrão local | Finalidade |
| --- | --- | --- |
| `ELASTICSEARCH_URL` | `http://localhost:9201` | Busca e indexação dos recibos |
| `OPENWEBUI_BASE_URL` | `http://localhost:35000` | Upload, extração de texto e chamadas à LLM |
| `OPENWEBUI_API_KEY` | Sem chave padrão | Credencial da API do OpenWebUI |
| `OPENWEBUI_MODEL` | Sem modelo padrão | Identificador de um modelo disponível no OpenWebUI |
| `DATABASE_URL` | `sqlite:///var/tasks.db` | Tarefas, resultados, outbox e cache de OCR |
| `RABBITMQ_URL` | `amqp://fai:fai-local@localhost:5673/%2F` | Conexão AMQP; credenciais de demonstração |
| `STORAGE_DIR` | `var/uploads` no `.env.example` | Diretório de armazenamento dos uploads |

Para PostgreSQL, use uma URL no formato `postgresql+psycopg://USUARIO:SENHA@HOST:PORTA/BANCO`. O driver está nas dependências do projeto.

O OpenWebUI deve estar com OCR/Docling configurado e o modelo selecionado disponível. Escolha um modelo que retorne os campos no contrato JSON; a disponibilidade de um modelo, isoladamente, não garante uma extração válida.

## Recuperação e extração

| Variável | Padrão | Finalidade |
| --- | --- | --- |
| `RECEIPT_INDEX` | `fai-recibos` | Índice dedicado aos recibos aceitos |
| `EMBEDDING_MODEL` | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | Modelo usado tanto na ingestão quanto na consulta |
| `TOP_K` | `5` | Quantidade final de candidatos comparados |
| `MAX_UPLOAD_MB` | `10` | Limite do arquivo, em MiB |
| `EXTRACTION_TIMEOUT_SECONDS` | `300` | Prazo para aguardar o texto no OpenWebUI |
| `EXTRACTION_MAX_TOKENS` | `4096` | Orçamento de saída da extração de campos pela LLM |
| `EXTRACTION_REASONING_EFFORT` | Vazio | Opção enviada a provedores compatíveis: `none`, `minimal`, `low`, `medium` ou `high` |
| `OCR_CACHE_VERSION` | `v1` | Versão do cache de texto; altere ao mudar a configuração do OCR |
| `LEASE_SECONDS` | `90` | Prazo de posse da tarefa, renovado durante a execução |
| `MAX_ATTEMPTS` | `3` | Máximo de tentativas de processamento |

Alterar o modelo de embeddings exige planejar a reindexação em um índice compatível. A aplicação verifica o mapping e não apaga um índice incompatível para recriá-lo.

Os formatos aceitos são PDF, JPEG e PNG. O código também limita PDFs a dez páginas, sem senha, imagens a 25 megapixels e texto extraído a 24 mil caracteres. Esses limites complementares não são variáveis do `.env`.

## Aprovação pelo FAIWeb

`INDEX_API_KEY` protege `POST /api/approved-receipts`. Configure um segredo compartilhado entre o backend do FAIWeb e este serviço; a chamada envia esse valor em `X-Index-Key`.

A página de demonstração não usa essa chave. Sem a variável configurada, a rota de aprovação retorna HTTP 503; uploads e consultas continuam disponíveis. Consulte o [contrato da API](api.md#indexar-após-aprovação).

## Credenciais do Compose

| Variável | Padrão de demonstração |
| --- | --- |
| `RABBITMQ_USER` | `fai` |
| `RABBITMQ_PASSWORD` | `fai-local` |
| `POSTGRES_PASSWORD` | `fai-local` |

O Compose usa esses valores para suas conexões internas. Eles não reconfiguram um PostgreSQL ou RabbitMQ externo da execução Python. Alterar uma variável de inicialização também não altera automaticamente a senha de um serviço já inicializado em volume existente.

Reinicie os processos da aplicação depois de editar `.env`. Não sobrescreva o `.env` existente ao seguir uma instalação já preparada.
