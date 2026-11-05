"""Diagnóstico de conexão; declara as filas e não imprime credenciais."""

import httpx

from app.config import Settings
from app.integrations import OpenWebUI, PipelineError
from app.messaging import connect


def main():
    s = Settings.from_env()
    try:
        response = httpx.get(s.elasticsearch_url + "/", timeout=5, trust_env=False)
        print("Elasticsearch:", response.status_code)
    except httpx.RequestError:
        print("Elasticsearch: indisponível")
    try:
        ids = OpenWebUI(s).models()
        print("OpenWebUI: conectado; modelo configurado disponível:", s.openwebui_model in ids)
    except PipelineError as exc:
        print("OpenWebUI:", str(exc))
    try:
        conn, _ = connect(s)
        conn.close()
        print("RabbitMQ: conectado")
    except Exception:
        print("RabbitMQ: indisponível")


if __name__ == "__main__":
    main()
