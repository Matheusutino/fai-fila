# API

Base local: `http://localhost:8010`. O contrato interativo está em `/docs`, e o OpenAPI em `/openapi.json`.

## Rotas

| Método e rota | Finalidade |
| --- | --- |
| `POST /api/receipt-checks` | Enviar recibo e receber token |
| `GET /api/receipt-checks/{token}` | Consultar tarefa e resultado |
| `GET /api/receipt-checks/{token}/file` | Abrir o arquivo enviado |
| `POST /api/approved-receipts` | Agendar indexação de um recibo aprovado |
| `GET /api/examples` | Listar consultas sintéticas da demonstração |
| `GET /api/examples/{filename}` | Obter arquivo de exemplo permitido |
| `GET /api/reference-receipts` | Listar os PDFs originais da demonstração |
| `GET /api/reference-receipts/{receipt_id}/file` | Abrir um desses PDFs originais |
| `GET /health/live` | Verificar se a API responde |
| `GET /health/ready` | Verificar banco e atividade recente dos processos da fila |

## Enviar um recibo

Envie `multipart/form-data` com o campo `file`:

```bash
curl --fail-with-body http://localhost:8010/api/receipt-checks \
  -H 'Idempotency-Key: exemplo-001' \
  -F 'file=@fixtures/queries/demo-001-copia.pdf'
```

Resposta HTTP **202**, com os campos principais abaixo (recorte do corpo):

```json
{
  "token": "TOKEN_DA_ANALISE",
  "kind": "check",
  "status": "pending",
  "stage": "waiting",
  "attempts": 0,
  "filename": "demo-001-copia.pdf",
  "mime": "application/pdf",
  "status_url": "/api/receipt-checks/TOKEN_DA_ANALISE",
  "result": null,
  "error": null
}
```

`Idempotency-Key` é opcional, com 1 a 120 caracteres após remover espaços nas pontas. Repetir a mesma chave e conteúdo retorna a tarefa original; reutilizar a chave com outro conteúdo retorna HTTP 409.

O servidor valida os bytes do arquivo. Aceita PDF sem senha, JPEG e PNG, com limites descritos em [Configuração](configuracao.md). Erros de formato retornam 422; tamanho acima do limite retorna 413.

## Consultar uma tarefa

```bash
curl --fail-with-body http://localhost:8010/api/receipt-checks/TOKEN_DA_ANALISE
```

| `status` | Significado |
| --- | --- |
| `pending` | Solicitação persistida, aguardando publicação |
| `queued` | Publicada na fila |
| `processing` | Worker executando |
| `retrying` | Aguardando nova tentativa |
| `succeeded` | Execução concluída com resultado |
| `failed` | Execução encerrada com erro |

`stage` detalha a etapa, conforme o tipo de tarefa e seu andamento:

| `stage` | Etapa |
| --- | --- |
| `waiting` | Espera para iniciar ou tentar novamente |
| `extracting` | Obtenção do texto pelo OCR |
| `structuring` | Extração dos campos pela LLM |
| `retrieving` | Recuperação dos candidatos |
| `comparing` | Aplicação das regras |
| `indexing` | Registro de um recibo aprovado |
| `completed` | Execução concluída |
| `failed` | Execução encerrada com erro |

O corpo também contém as datas `created_at` e `updated_at` em UTC.

Para uma verificação concluída, `result` contém:

| Campo | Conteúdo |
| --- | --- |
| `decision` | `possible_duplicate`, `no_duplicate_found` ou `inconclusive` |
| `receipt` | Campos estruturados do upload e evidências da extração |
| `matches` | Candidatos, campos da base, comparação e justificativa por candidato |
| `text` | Texto extraído do upload |
| `retrieval` | Método e quantidade de candidatos recuperados |
| `rule_version` | Versão da política de comparação |
| `duration_ms` | Tempo de execução da pipeline |
| `limitation` | Escopo da conclusão |

`failed` preenche `error` com `code` e `message`; não equivale a uma conclusão de ausência de duplicidade. Token desconhecido retorna 404. Na página, a consulta continua até um estado terminal; F5 interrompe o acompanhamento visual e limpa a tela, sem cancelar a tarefa no servidor.

## Visualizar arquivos

As rotas terminadas em `/file` devolvem o documento com disposição `inline`, permitindo usar o leitor do navegador. O upload é acessado pelo mesmo token usado na consulta da tarefa. Não há listagem pública do diretório de uploads.

`GET /api/reference-receipts` lista somente os originais sintéticos permitidos pelo manifesto, com identificador, nome, hash e URL. Ela não é uma listagem geral de todos os recibos do Elasticsearch.

## Indexar após aprovação

Esta chamada pertence à integração entre backends. Configure `INDEX_API_KEY` e envie o segredo no header `X-Index-Key`. O corpo é:

```json
{
  "check_token": "TOKEN_DE_UMA_ANALISE_CONCLUIDA",
  "receipt_id": "faiweb-recibo-123",
  "approval_id": "aprovacao-456",
  "revision": 1,
  "project": "FAI-2026-041"
}
```

| Campo | Regra |
| --- | --- |
| `check_token` | Token de uma tarefa de verificação concluída com `succeeded` |
| `receipt_id` | Identificador estável do recibo no FAIWeb; letras, números, `_` e `-`, até 100 caracteres |
| `approval_id` | Referência da decisão externa de aprovação, de 1 a 100 caracteres |
| `revision` | Inteiro positivo; padrão 1 |
| `project` | Identificador opcional do projeto, até 100 caracteres |

A resposta HTTP **202** contém outro token, desta vez de uma tarefa `kind: index`. Consulte a mesma rota de acompanhamento até `succeeded`. O resultado de indexação contém `receipt_id`, `indexed: true` e `revision`.

O FAIWeb é responsável por decidir e registrar a aprovação antes dessa chamada. A rota aceita aprovação humana de um caso sinalizado e não exige que a verificação tenha retornado ausência de duplicidade.

Repetir a mesma aprovação e revisão devolve a tarefa original. Reutilizar o mesmo `receipt_id` e revisão com conteúdo diferente gera conflito. Revisões antigas não sobrescrevem revisões novas no Elasticsearch.

| HTTP | Situação |
| --- | --- |
| `403` | Chave ausente ou inválida |
| `404` | Análise de origem não encontrada ou de tipo incorreto |
| `409` | Análise ainda não concluída ou conflito de idempotência |
| `422` | Corpo fora do contrato |
| `503` | Integração sem chave configurada ou falha de acesso ao banco |

## Prontidão

`/health/live` retorna HTTP 200 quando o processo da API está respondendo. `/health/ready` retorna 200 com `status: ok` quando consegue acessar o banco e encontra atividade recente de publicador e worker conectados ao RabbitMQ; caso contrário, retorna 503.

Prontidão não certifica OCR, modelo da LLM nem índice de recibos. Para verificar o fluxo completo, use os [testes pela pipeline](testes.md).
