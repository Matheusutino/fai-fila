"""Testa aprovação/indexação/reuso pela API e remove somente seu recibo temporário."""

import argparse
import time
import uuid

import httpx

from app.config import ROOT, Settings
from app.integrations import ReceiptIndex


def wait(client, task, timeout=600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(task["status_url"])
        response.raise_for_status()
        current = response.json()
        if current["status"] in ("succeeded", "failed"):
            assert current["status"] == "succeeded", current.get("error")
            return current
        time.sleep(2)
    raise TimeoutError("Prazo de acompanhamento excedido.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    args = parser.parse_args()
    settings = Settings.from_env()
    if not settings.index_api_key:
        raise SystemExit("Configure INDEX_API_KEY para validar a integração de aprovação.")
    rid = "smoke-approval-" + uuid.uuid4().hex
    path = ROOT / "fixtures/queries/recibo-novo.pdf"
    try:
        with httpx.Client(base_url=args.base_url, timeout=30, trust_env=False) as client:

            def upload():
                with path.open("rb") as handle:
                    response = client.post(
                        "/api/receipt-checks", files={"file": (path.name, handle, "application/pdf")}
                    )
                response.raise_for_status()
                return wait(client, response.json())

            original = upload()
            assert original["result"]["decision"] == "no_duplicate_found"
            body = {
                "check_token": original["token"],
                "receipt_id": rid,
                "approval_id": "synthetic-smoke",
                "revision": 1,
                "project": "DEMO",
            }
            headers = {"X-Index-Key": settings.index_api_key}
            response = client.post("/api/approved-receipts", json=body, headers=headers)
            response.raise_for_status()
            accepted = response.json()
            assert wait(client, accepted)["result"]["indexed"]
            repeated = client.post("/api/approved-receipts", json=body, headers=headers)
            repeated.raise_for_status()
            assert repeated.json()["token"] == accepted["token"]
            duplicate = upload()
            assert duplicate["result"]["decision"] == "possible_duplicate"
            assert any(m["receipt_id"] == rid for m in duplicate["result"]["matches"])
            print("Aprovação, indexação idempotente e detecção de reuso passaram.", flush=True)
    finally:
        # ID aleatório reservado a este teste: preserva todos os originais e outros recibos.
        ReceiptIndex(settings).request(
            "DELETE",
            "/" + settings.receipt_index + "/_doc/" + rid,
            params={"refresh": "wait_for"},
            allow_missing=True,
        )


if __name__ == "__main__":
    main()
