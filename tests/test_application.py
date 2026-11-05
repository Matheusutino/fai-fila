import json
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.pipeline import Pipeline
from app.worker import execute
from scripts.generate_corpus import generate, pdf_bytes


def test_upload_status_and_idempotency(repo, tmp_path, receipt):
    settings = replace(Settings(), storage_dir=tmp_path / "uploads")
    with TestClient(create_app(settings, repo)) as client:
        data = pdf_bytes(receipt.model_dump(mode="json"))
        first = client.post(
            "/api/receipt-checks",
            files={"file": ("../../test.pdf", data, "text/plain")},
            headers={"Idempotency-Key": "same"},
        )
        assert first.status_code == 202
        token = first.json()["token"]
        assert first.json()["status"] == "pending" and first.json()["filename"] == "test.pdf"
        again = client.post(
            "/api/receipt-checks", files={"file": ("test.pdf", data)}, headers={"Idempotency-Key": "same"}
        )
        assert again.json()["token"] == token
        assert len(list(settings.storage_dir.iterdir())) == 1
        assert client.get("/api/receipt-checks/" + token).status_code == 200
        assert client.get("/api/receipt-checks/missing").status_code == 404
        assert client.get("/.env").status_code == 404


def test_invalid_file_and_size_limit(repo, tmp_path):
    settings = replace(Settings(), storage_dir=tmp_path / "uploads", max_upload_mb=1)
    with TestClient(create_app(settings, repo)) as client:
        assert (
            client.post("/api/receipt-checks", files={"file": ("fake.png", b"not an image")}).status_code
            == 422
        )
        assert (
            client.post(
                "/api/receipt-checks", files={"file": ("big.pdf", b"x" * (1024 * 1024 + 1))}
            ).status_code
            == 413
        )


def test_original_upload_served_inline_only_from_storage(repo, tmp_path, receipt):
    settings = replace(Settings(), storage_dir=tmp_path / "uploads")
    data = pdf_bytes(receipt.model_dump(mode="json"))
    with TestClient(create_app(settings, repo)) as client:
        job = client.post(
            "/api/receipt-checks", files={"file": ("wrong-extension.jpg", data, "image/jpeg")}
        ).json()
        assert job["mime"] == "application/pdf"
        url = job["status_url"] + "/file"
        response = client.get(url)
        assert response.content == data
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"].startswith("inline;")
        assert response.headers["cache-control"] == "private, no-store"
        assert client.get("/api/receipt-checks/unknown/file").status_code == 404
        # Mesmo com um caminho local adulterado, não publica arquivos fora do storage.
        path = Path(repo.get(job["token"])["file_path"])
        secret = tmp_path / "secret.pdf"
        secret.write_bytes(b"private")
        path.unlink()
        path.symlink_to(secret)
        assert client.get(url).status_code == 404


def test_reference_pdfs_whitelist_and_inline_view(repo, tmp_path, monkeypatch):
    import app.main as main_module

    (tmp_path / "frontend").mkdir()
    manifest = generate(tmp_path / "fixtures", 42)
    monkeypatch.setattr(main_module, "ROOT", tmp_path)
    with TestClient(create_app(Settings(), repo)) as client:
        items = client.get("/api/reference-receipts").json()
        assert len(items) == 3
        assert "true_fields" not in items[0]
        response = client.get(items[0]["url"])
        assert response.content == (tmp_path / "fixtures/reference/demo-001.pdf").read_bytes()
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"].startswith("inline;")
        assert client.get("/api/reference-receipts/recibo-novo/file").status_code == 404
        # Uma entrada do manifesto não pode publicar um arquivo fora de reference/.
        manifest["references"][0]["file"] = "../secret.pdf"
        (tmp_path / "secret.pdf").write_bytes(b"private")
        (tmp_path / "fixtures/manifest.json").write_text(json.dumps(manifest))
        assert len(client.get("/api/reference-receipts").json()) == 2
        assert client.get(items[0]["url"]).status_code == 404


def test_check_approval_index_and_reuse_cycle(repo, tmp_path, receipt):
    settings = replace(Settings(), storage_dir=tmp_path / "uploads", index_api_key="integration-key")

    class Extractor:
        def extract_text(self, *args):
            return "OCR text", "remote-file"

        def extract_fields(self, text):
            return receipt

    class Index:
        def __init__(self):
            self.documents = {}

        def search(self, text):
            return list(self.documents.values())

        def index(self, document, revision):
            self.documents[document["receipt_id"]] = document

    index = Index()
    pipeline = Pipeline(settings, Extractor(), index)
    data = pdf_bytes(receipt.model_dump(mode="json"))
    with TestClient(create_app(settings, repo)) as client:
        check = client.post("/api/receipt-checks", files={"file": ("test.pdf", data)}).json()
        job = repo.acquire(repo.get(check["token"])["id"], 90, 3)
        assert execute(repo, pipeline, job, settings) == "succeeded"
        result = client.get(check["status_url"]).json()
        assert result["result"]["decision"] == "no_duplicate_found"
        assert index.documents == {}  # A checagem não indexa o upload.
        body = {
            "check_token": check["token"],
            "receipt_id": "accepted-1",
            "approval_id": "faiweb-approval",
            "revision": 1,
        }
        assert client.post("/api/approved-receipts", json=body).status_code == 403
        response = client.post(
            "/api/approved-receipts", json=body, headers={"X-Index-Key": "integration-key"}
        )
        assert response.status_code == 202
        accepted = response.json()
        assert (
            execute(repo, pipeline, repo.acquire(repo.get(accepted["token"])["id"], 90, 3), settings)
            == "succeeded"
        )
        repeated = client.post(
            "/api/approved-receipts", json=body, headers={"X-Index-Key": "integration-key"}
        )
        assert repeated.json()["token"] == accepted["token"]
        check2 = client.post("/api/receipt-checks", files={"file": ("same.pdf", data)}).json()
        execute(repo, pipeline, repo.acquire(repo.get(check2["token"])["id"], 90, 3), settings)
        assert client.get(check2["status_url"]).json()["result"]["decision"] == "possible_duplicate"
        assert len(index.documents) == 1


def test_corpus_reproducible_and_queries_not_in_reference(tmp_path):
    first = generate(tmp_path / "one", 42)
    second = generate(tmp_path / "two", 42)
    assert first == second
    assert len(first["references"]) == 3 and len(first["queries"]) == 16
    assert any(x["is_duplicate"] and x["transformation"] == "rotation_compression" for x in first["queries"])
    reference = {x["logical_receipt_id"] for x in first["references"]}
    for item in first["queries"]:
        if item["is_duplicate"]:
            assert item["source_receipt_id"] in reference


def test_ocr_cache_reuses_text_but_always_retrieves_again(repo, receipt):
    class Extractor:
        def __init__(self):
            self.ocr_calls = self.field_calls = 0

        def extract_text(self, *args):
            self.ocr_calls += 1
            return "OCR real preservado", "remote-id"

        def extract_fields(self, text):
            self.field_calls += 1
            return receipt

    class Index:
        def __init__(self):
            self.calls = 0
            self.candidates = []

        def search(self, text):
            self.calls += 1
            return self.candidates

    extractor, index = Extractor(), Index()
    pipeline = Pipeline(Settings(), extractor, index, text_cache=repo)
    job = {"kind": "check", "file_path": "receipt.pdf", "mime": "application/pdf", "file_hash": "a" * 64}
    assert pipeline.process(job, lambda stage: None)["decision"] == "no_duplicate_found"
    index.candidates = [{"receipt_id": "accepted", "receipt": receipt.model_dump(mode="json")}]
    assert pipeline.process(job, lambda stage: None)["decision"] == "possible_duplicate"
    assert extractor.ocr_calls == 1 and extractor.field_calls == 2 and index.calls == 2


def test_ocr_cache_version_change_requires_fresh_extraction(repo):
    repo.cache_text("a" * 64, "v1", "text", "remote")
    assert repo.cached_text("a" * 64, "v1") == ("text", "remote")
    assert repo.cached_text("a" * 64, "v2") is None
