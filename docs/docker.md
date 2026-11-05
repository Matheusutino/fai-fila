# Executar com Docker Compose

O repositório inclui [Dockerfile](../Dockerfile) e [compose.yaml](../compose.yaml). O Compose foi validado com `docker compose config --quiet`; **o build da imagem e a execução dos containers ainda não foram validados**. A demonstração no chope foi executada em Python, pois o usuário não tinha acesso ao daemon do Docker durante a preparação.

## O que será iniciado

| Serviço | Papel |
| --- | --- |
| `api` | Recebe uploads, consulta tarefas e serve a página web |
| `dispatcher` | Publica no RabbitMQ as tarefas registradas no banco |
| `worker` | Executa OCR, extração, busca, comparação e indexação |
| `postgres` | Persiste tarefas, resultados, cache de texto e outbox; imagem PostgreSQL 17 |
| `rabbitmq` | Fila de processamento e painel de administração; imagem RabbitMQ 4 Management |

API, publicador e worker usam o mesmo Dockerfile, com comandos de inicialização diferentes. O Dockerfile instala Python 3.12, dependências e embeddings para CPU, copia o código e gera os recibos sintéticos.

**Elasticsearch, OpenWebUI, Docling e provedor da LLM não são iniciados pelo Compose.** A aplicação se conecta aos serviços externos configurados no `.env`.

## Preparar a configuração

Requer Docker com Compose, acesso ao daemon e conexão dos containers com os serviços externos.

Na raiz do projeto, crie `.env` se necessário:

```bash
cp -n .env.example .env
```

Preencha `OPENWEBUI_API_KEY`, `OPENWEBUI_MODEL` e as URLs dos serviços. Se Elasticsearch e OpenWebUI estiverem no mesmo host do Docker, a configuração fornecida permite usar:

```dotenv
ELASTICSEARCH_URL=http://host.docker.internal:9201
OPENWEBUI_BASE_URL=http://host.docker.internal:35000
```

Dentro do container, `localhost` aponta para o próprio container. Os serviços no host precisam aceitar conexões pela interface alcançada por `host.docker.internal`; escutar somente em `127.0.0.1` pode impedir esse acesso. Se estiverem em outra máquina, use seus endereços de rede.

O Compose define os endereços internos do PostgreSQL e RabbitMQ e `STORAGE_DIR=/data/uploads`, substituindo esses valores do `.env` para os processos em containers. As credenciais são controladas por `POSTGRES_PASSWORD`, `RABBITMQ_USER` e `RABBITMQ_PASSWORD`.

A imagem não inclui `fai-elasticsearch/` nem seus arquivos de configuração. Preencha as credenciais no `.env` da raiz; o fallback local da referência não está disponível no container. Veja a lista de variáveis em [Configuração](configuracao.md).

## Subir e carregar a base

Use este modo sem outra instância Python ocupando as portas 8010 e 5673 no host.

```bash
docker compose config --quiet
docker compose up --build -d
docker compose ps
docker compose exec worker python -m scripts.check_services
```

Depois de confirmar as conexões, carregue os três originais sintéticos como recibos previamente aceitos:

```bash
docker compose exec worker python -m scripts.ingest_receipts
```

A carga não usa as consultas de teste nem o gabarito para preencher os campos. O primeiro uso pode baixar o modelo de embeddings.

| Endereço no host | Serviço |
| --- | --- |
| http://localhost:8010 | Página da aplicação |
| http://localhost:8010/docs | API interativa |
| http://localhost:15673 | RabbitMQ Management; credenciais do `.env` |
| `127.0.0.1:5673` | AMQP do RabbitMQ |

As portas publicadas estão limitadas ao loopback do host. Para acessar uma máquina remota, use o [túnel SSH](execucao.md#abrir-no-seu-navegador) ou configure um proxy reverso. O PostgreSQL não publica uma porta no host neste Compose.

## Logs e dados

```bash
docker compose logs -f api dispatcher worker
```

| Volume | Conteúdo |
| --- | --- |
| `postgres` | Banco de tarefas, resultados e extrações |
| `rabbitmq` | Dados persistentes da fila |
| `uploads` | Arquivos recebidos; compartilhado entre API e worker |
| `models` | Cache dos modelos de embeddings |

Os volumes pertencem ao Compose. Eles são distintos dos arquivos e do banco em `var/` usados na execução Python. Trocar o modo de execução não migra os dados automaticamente.

## Parar ou atualizar

Para parar e remover os containers preservando os volumes:

```bash
docker compose down
```

Para reconstruir e iniciar após alterações:

```bash
docker compose up --build -d
```

`docker compose down -v` também remove os volumes e seus dados. A configuração concede até oito minutos para o worker encerrar; API e publicador usam o prazo padrão do Compose.
