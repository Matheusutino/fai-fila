# Exemplos e testes

Os documentos de teste são sintéticos, sem valor fiscal. Eles demonstram a recuperação de candidatos e as regras; não medem a qualidade em uma base de produção.

## Gerar os arquivos

```bash
.venv/bin/python -m scripts.generate_corpus
```

O gerador usa seed fixa e cria:

| Caminho | Conteúdo |
| --- | --- |
| `fixtures/reference/` | 3 PDFs originais, usados como recibos previamente aceitos |
| `fixtures/queries/` | 16 arquivos para upload e avaliação |
| `fixtures/manifest.json` | Hashes, origem de cada versão, campos verdadeiros e decisão esperada |

Esses arquivos são gerados localmente e ignorados pelo Git. No Docker, a geração ocorre durante o build.

| Consultas | Quantidade | Expectativa |
| --- | --- | --- |
| Cópias idênticas dos originais | 3 | Possível duplicidade |
| Originais convertidos em PNG | 3 | Possível duplicidade |
| Imagens rotacionadas e comprimidas | 3 | Possível duplicidade |
| Imagens com ruído e resolução alterada | 3 | Possível duplicidade |
| Mesmo valor/data/local, identificador diferente | 1 | Inconclusivo por conflito |
| Data e identificador diferentes | 1 | Nenhuma duplicidade encontrada |
| Valor e identificador ausentes | 1 | Inconclusivo por insuficiência de dados |
| Recibo novo, sem original na base | 1 | Nenhuma duplicidade encontrada |

O gabarito é usado pelo avaliador. Ele não fornece os campos ao extrator, ao índice ou ao comparador.

## Carregar as referências

Com Elasticsearch e OpenWebUI configurados:

```bash
.venv/bin/python -m scripts.ingest_receipts
```

O script carrega somente `fixtures/reference/`. Os campos são obtidos pelo OCR e pela LLM, e os vetores são calculados com o mesmo modelo usado na consulta. A ingestão usa IDs estáveis e revisão 1.

Na demonstração preparada, essa carga já foi feita. Não a repita a cada inicialização e não ingira os arquivos de `queries/` como referências da avaliação.

## Suíte sem serviços externos

Instale as dependências de desenvolvimento na `.venv` existente:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/ruff check app scripts tests
node --check frontend/app.js
```

Por padrão, a suíte usa SQLite temporário e simula Elasticsearch/OpenWebUI. Os dois testes opcionais de RabbitMQ são ignorados sem a flag de integração.

Para testar também com um RabbitMQ real configurado em `RABBITMQ_URL`:

```bash
RUN_BROKER_TESTS=1 .venv/bin/python -m pytest -q
```

Os testes do broker usam filas aleatórias próprias e as removem ao terminar. Para substituir SQLite por PostgreSQL na suíte, exporte `TEST_DATABASE_URL` para um banco de teste acessível; cada teste cria e remove um schema aleatório. A conexão precisa permitir criar schemas.

## Avaliar a pipeline real

Com API, publicador, worker e dependências disponíveis, e os três originais carregados:

```bash
.venv/bin/python -m scripts.evaluate_corpus
```

O avaliador envia os 16 arquivos pela API e consulta cada token até terminar ou atingir o prazo. Ele grava `var/evaluation.json` com decisões, presença do original no top-k e campos extraídos contra o gabarito.

Para uma consulta específica:

```bash
.venv/bin/python -m scripts.evaluate_corpus \
  --filename demo-001-copia.pdf \
  --report var/evaluation-single.json
```

O prazo padrão é de 600 segundos por consulta, ajustável por `--timeout`. `--base-url` permite apontar para outra instância. OCR e LLM são serviços reais nesse teste; um modelo lento ou indisponível pode levar a falhas.

## Testar a página

Com Chrome instalado:

```bash
.venv/bin/python -m scripts.browser_smoke --chrome /usr/bin/google-chrome
```

Como alternativa, instale o Chromium do Playwright e execute sem `--chrome`:

```bash
.venv/bin/python -m playwright install chromium
.venv/bin/python -m scripts.browser_smoke
```

O teste verifica upload real, resultado de duplicidade, reset com F5, consulta manual pelo token, PDFs, prévia de imagem, tratamento de falha ao listar originais e layout mobile. As capturas ficam em `artifacts/`.

## Testar aprovação e reuso

Após a avaliação do corpus, com `INDEX_API_KEY` configurada:

```bash
.venv/bin/python -m scripts.approval_smoke
```

O teste envia o recibo novo, confirma ausência de duplicidade, chama a aprovação autenticada, aguarda a indexação e reenvia o arquivo para verificar a suspeita. Também confere a idempotência da aprovação. Ao terminar, remove somente o documento temporário criado por esse teste no Elasticsearch.

Relatórios e evidências já obtidos estão em [Validação](VALIDACAO.md).
