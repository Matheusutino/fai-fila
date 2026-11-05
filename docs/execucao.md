# Executar em Python e acessar pelo SSH

Este guia cobre a execução usada na demonstração do chope e a instalação local em outra máquina. Para containers, siga [Docker](docker.md).

## Iniciar no chope

Conecte-se ao servidor:

```bash
ssh chope
cd /exp/utinomatheus/fai-fila
```

Inicie os três processos da aplicação:

```bash
.venv/bin/python -m scripts.dev_stack start
.venv/bin/python -m scripts.dev_stack status
```

A saída esperada é:

```text
api: ativo
dispatcher: ativo
worker: ativo
```

`start` preserva processos já ativos e inicia os demais em segundo plano. Eles continuam executando quando você encerra o SSH. **O comando não inicia banco, RabbitMQ, Elasticsearch ou OpenWebUI.** No chope, o `.env` e os recibos de referência já foram preparados.

Confirme a prontidão:

```bash
curl --fail --silent --show-error http://127.0.0.1:8010/health/ready
```

O resultado deve conter `"status":"ok"`. Essa rota verifica o banco e os sinais recentes de atividade do publicador e worker conectados à fila. Para verificar também os acessos ao Elasticsearch e OpenWebUI:

```bash
.venv/bin/python -m scripts.check_services
```

Esse diagnóstico consulta as dependências e declara as filas necessárias; ele não executa uma análise completa nem verifica a presença das referências no índice.

## Abrir no seu navegador

Em outro terminal, **no seu computador**, execute:

```bash
ssh -N -o ExitOnForwardFailure=yes -L 8010:127.0.0.1:8010 chope
```

Mantenha o terminal aberto e acesse:

| Endereço | Conteúdo |
| --- | --- |
| http://localhost:8010 | Página de upload e análise |
| http://localhost:8010/docs | Documentação interativa da API |

Se a porta 8010 estiver ocupada no seu computador, encaminhe outra porta local:

```bash
ssh -N -o ExitOnForwardFailure=yes -L 8080:127.0.0.1:8010 chope
```

Abra **http://localhost:8080** nesse caso. A porta da aplicação no servidor continua sendo 8010.

O túnel atende ao acesso pelo seu computador. Publicar uma URL para outras pessoas exige configurar um proxy reverso para `127.0.0.1:8010` no servidor. A aplicação usa caminhos a partir da raiz (`/api` e `/static`); uma publicação sob subpasta exige adaptação desses caminhos.

## Usar a página

Escolha um exemplo e clique em **Usar**, ou selecione um arquivo próprio. Depois, clique em **Verificar duplicidade**. O envio retorna um token; a página consulta a API até a tarefa terminar. OCR e LLM podem levar alguns minutos.

Os controles de visualização permitem abrir o arquivo selecionado, o arquivo de uma análise e os três PDFs originais da demonstração. Os candidatos correspondentes a esses originais também oferecem **Visualizar PDF original**.

**F5 limpa o formulário, o acompanhamento e o resultado.** Para voltar a uma análise, cole o token em **Retomar uma análise** e clique em **Consultar**. A tarefa continua guardada no servidor.

## Logs e parada

```bash
tail -f var/logs/api.log var/logs/dispatcher.log var/logs/worker.log
```

`Ctrl+C` encerra o acompanhamento dos logs. Para solicitar a parada da aplicação:

```bash
.venv/bin/python -m scripts.dev_stack stop
```

O worker aguarda o processamento atual terminar. Consulte `status` até todos os processos estarem parados antes de usar `start` novamente. Reinicie a aplicação depois de mudar `.env`. O gerenciador local não é um supervisor de serviços: ele não reinicia os processos automaticamente após falha ou reboot.

## Instalação em outro ambiente

Requisitos: Python 3.12, RabbitMQ acessível, Elasticsearch e OpenWebUI com OCR/Docling e modelo de extração disponíveis. O banco pode ser SQLite, padrão local, ou PostgreSQL.

Na raiz do projeto, crie a `.venv` e instale as dependências:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
.venv/bin/python -m pip install -r requirements-embeddings.txt
```

Crie `.env` **somente se ainda não existir**:

```bash
cp -n .env.example .env
```

Preencha os endereços, a chave e o modelo conforme [Configuração](configuracao.md). O exemplo de `RABBITMQ_URL` pressupõe uma fila em `localhost:5673`; ajuste ao seu broker. O código da aplicação não instala esse serviço.

Gere o corpus, confira as conexões e carregue os três originais:

```bash
.venv/bin/python -m scripts.generate_corpus
.venv/bin/python -m scripts.check_services
.venv/bin/python -m scripts.ingest_receipts
.venv/bin/python -m scripts.dev_stack start
```

A carga faz OCR, extração de campos e indexação dos originais. Ela é uma preparação da base, não um passo necessário a cada início da aplicação. O primeiro uso dos embeddings pode baixar o MiniLM.

Para depurar em primeiro plano, execute cada comando em um terminal separado, em vez de usar `dev_stack`:

```bash
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

```bash
.venv/bin/python -m app.dispatcher
```

```bash
.venv/bin/python -m app.worker
```

## Problemas comuns

| Sintoma | O que conferir |
| --- | --- |
| `Address already in use` ao abrir o túnel | Use outra porta local, como 8080 |
| Página não abre | Confira `dev_stack status`, a porta 8010 no servidor e o túnel SSH |
| Página abre, mas a tarefa não avança | Consulte `/health/ready` e os logs de worker/publicador; confira RabbitMQ e banco |
| Erro de OCR ou modelo | Execute `scripts.check_services` e confira `OPENWEBUI_API_KEY`, `OPENWEBUI_MODEL` e os logs |
| Índice ausente | Execute a carga inicial com `scripts.ingest_receipts` |
| Mapping/modelo incompatível | Confira índice e configuração de embeddings; a aplicação preserva o índice existente |
| Originais não aparecem | Confira se o corpus foi gerado; use **Tentar novamente** e recarregue a página após uma atualização |
| Dependências locais pararam no chope | Consulte [Ambiente do chope](ambiente-chope.md) |

Os arquivos JS/CSS usam URLs versionadas pelo conteúdo e o HTML é entregue sem cache. A lista de originais tem timeout de 15 segundos e opção de tentar novamente.
