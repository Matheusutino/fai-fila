# Dependências locais da demonstração no chope

Este guia é específico do ambiente em `/exp/utinomatheus/fai-fila`. Para o uso normal, siga [Execução](execucao.md); para uma instalação nova, use as instruções de Python ou [Docker](docker.md).

## Como o ambiente foi preparado

A demonstração usa PostgreSQL e RabbitMQ extraídos em `var/local-services/`, sem instalação como serviços do sistema. Essa solução permitiu validar a aplicação quando o usuário não tinha acesso ao daemon do Docker.

Essa pasta é local, ignorada pelo Git, e contém binários e dados da demonstração. Os comandos abaixo dependem de ela já existir; não são um instalador para outra máquina. Os serviços não iniciam automaticamente após reiniciar o servidor.

| Componente | Endereço no chope |
| --- | --- |
| API | `127.0.0.1:8010` |
| PostgreSQL | `127.0.0.1:55433` |
| RabbitMQ | `127.0.0.1:5673` |
| Elasticsearch existente | `http://localhost:9201` |
| OpenWebUI existente | `http://localhost:35000` |

A configuração de conexão da aplicação está no `.env` da raiz. Ela utiliza PostgreSQL neste ambiente, embora o padrão local do código seja SQLite. Esta instalação local do RabbitMQ não fornece o painel de Management descrito no guia de Docker.

## Diagnosticar antes de reiniciar

Na raiz do projeto:

```bash
.venv/bin/python -m scripts.dev_stack status
curl --silent --show-error http://127.0.0.1:8010/health/ready
.venv/bin/python -m scripts.check_services
ss -ltn '( sport = :55433 or sport = :5673 )'
```

Se o banco ou a fila estiver parado, siga a recuperação correspondente. Publicador e worker tentam se reconectar automaticamente à fila.

## Recuperar o PostgreSQL

Se o **PostgreSQL local estiver parado**, execute na raiz do projeto:

```bash
FAI_LOCAL_SERVICES="$PWD/var/local-services"
LD_LIBRARY_PATH="$FAI_LOCAL_SERVICES/root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  "$FAI_LOCAL_SERVICES/root/usr/lib/postgresql/16/bin/pg_ctl" \
  -D "$FAI_LOCAL_SERVICES/pgdata" \
  -l "$FAI_LOCAL_SERVICES/postgres.log" start
```

## Recuperar o RabbitMQ

Se o RabbitMQ local estiver parado, execute na raiz do projeto:

```bash
FAI_LOCAL_SERVICES="$PWD/var/local-services"
ERL_EPMD_ADDRESS=127.0.0.1 \
  "$FAI_LOCAL_SERVICES/root/usr/lib/erlang/erts-13.2.2.5/bin/epmd" -daemon

env \
  PATH="$FAI_LOCAL_SERVICES/bin:$PATH" \
  LD_LIBRARY_PATH="$FAI_LOCAL_SERVICES/root/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  XDG_CONFIG_HOME="$FAI_LOCAL_SERVICES/xdg" \
  ERL_EPMD_ADDRESS=127.0.0.1 \
  RABBITMQ_NODENAME=fai_demo@localhost \
  RABBITMQ_CONFIG_FILE="$FAI_LOCAL_SERVICES/rabbit" \
  RABBITMQ_MNESIA_BASE="$FAI_LOCAL_SERVICES/rabbit-data" \
  RABBITMQ_LOG_BASE="$FAI_LOCAL_SERVICES/rabbit-log" \
  RABBITMQ_PID_FILE="$FAI_LOCAL_SERVICES/rabbit.pid" \
  RABBITMQ_ENABLED_PLUGINS_FILE="$FAI_LOCAL_SERVICES/enabled_plugins" \
  RABBITMQ_CONF_ENV_FILE=/dev/null \
  RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS='+S 2:2 +SDcpu 1 +SDio 1' \
  "$FAI_LOCAL_SERVICES/root/usr/lib/rabbitmq/lib/rabbitmq_server-3.12.1/sbin/rabbitmq-server" \
  -detached
```

Aguarde alguns segundos e confira novamente `/health/ready`. Para investigar falhas, consulte `var/local-services/postgres.log` e os arquivos de `var/local-services/rabbit-log/`.

Esses comandos recuperam as dependências locais. Para iniciar API, publicador e worker, use `.venv/bin/python -m scripts.dev_stack start`.
