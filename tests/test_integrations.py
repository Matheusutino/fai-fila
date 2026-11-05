import json
from dataclasses import replace

import httpx
import pytest

from app.config import Settings
from app.integrations import OpenWebUI, PipelineError, ReceiptIndex


def test_file_processing_waits_for_completion_and_reads_text(tmp_path):
    path = tmp_path / "test.pdf"
    path.write_bytes(b"%PDF example")
    calls = []
    statuses = iter(["pending", "completed"])

    def handler(request):
        calls.append(request.url.path)
        if request.method == "POST":
            assert b'name="file"' in request.content
            return httpx.Response(200, json={"id": "file-123"})
        if request.url.path.endswith("/data/content"):
            return httpx.Response(200, json={"content": "Texto OCR"})
        return httpx.Response(200, json={"data": {"status": next(statuses)}})

    settings = replace(Settings(), openwebui_api_key="key", poll_seconds=0.001)
    client = OpenWebUI(settings, httpx.Client(transport=httpx.MockTransport(handler)))
    assert client.extract_text(path, "application/pdf") == ("Texto OCR", "file-123")
    assert calls[-1].endswith("/data/content")


def test_failed_ocr_never_becomes_negative_decision(tmp_path):
    path = tmp_path / "test.pdf"
    path.write_bytes(b"pdf")

    def handler(request):
        return httpx.Response(
            200,
            json={"id": "file-1"}
            if request.method == "POST"
            else {"data": {"status": "failed", "error": "secret upstream detail"}},
        )

    client = OpenWebUI(
        replace(Settings(), openwebui_api_key="key"), httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(PipelineError) as error:
        client.extract_text(path, "application/pdf")
    assert error.value.code == "ocr_failed"
    assert "secret" not in str(error.value)


def test_image_transport_uses_pdf_without_local_ocr(tmp_path):
    from PIL import Image

    path = tmp_path / "receipt.png"
    Image.new("RGB", (40, 50), "white").save(path)

    def handler(request):
        if request.method == "POST":
            assert b"application/pdf" in request.content
            assert b"%PDF-" in request.content
            return httpx.Response(200, json={"id": "image-pdf"})
        if request.url.path.endswith("/data/content"):
            return httpx.Response(200, json={"content": "OCR remoto"})
        return httpx.Response(200, json={"data": {"status": "completed"}})

    client = OpenWebUI(
        replace(Settings(), openwebui_api_key="key"), httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert client.extract_text(path, "image/png")[0] == "OCR remoto"


def test_text_ready_before_openwebui_internal_index_finishes(tmp_path):
    path = tmp_path / "copy.pdf"
    path.write_bytes(b"pdf")

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"id": "copy"})
        if request.url.path.endswith("/data/content"):
            return httpx.Response(200, json={"content": "Texto já extraído"})
        return httpx.Response(200, json={"data": {"status": "pending", "content": "Texto já extraído"}})

    client = OpenWebUI(
        replace(Settings(), openwebui_api_key="key"), httpx.Client(transport=httpx.MockTransport(handler))
    )
    assert client.extract_text(path, "application/pdf") == ("Texto já extraído", "copy")


@pytest.mark.parametrize("grounded", [True, False])
def test_fields_require_literal_evidence(grounded):
    response = {
        "amount_minor": 12590,
        "evidence": {"amount_minor": "TOTAL R$ 125,90" if grounded else "invented"},
    }

    def handler(request):
        body = json.loads(request.content)
        assert "document" in json.loads(body["messages"][1]["content"])
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(response)}}]})

    client = OpenWebUI(
        replace(Settings(), openwebui_api_key="key", openwebui_model="model"),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    if grounded:
        assert client.extract_fields("TOTAL R$ 125,90").amount_minor == 12590
    else:
        with pytest.raises(PipelineError):
            client.extract_fields("TOTAL R$ 125,90")


def test_json_mode_rejection_falls_back_to_validated_text_json():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if "response_format" in body:
            return httpx.Response(400, json={"detail": "provider refuses json mode"})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"amount_minor":12590,"evidence":{"amount_minor":"R$ 125,90"}}'}}
                ]
            },
        )

    client = OpenWebUI(
        replace(Settings(), openwebui_api_key="key", openwebui_model="model"),
        httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.extract_fields("TOTAL R$ 125,90").amount_minor == 12590
    assert len(calls) == 2 and "response_format" not in calls[1]


def test_absent_field_null_evidence_is_not_an_extraction_error():
    payload = {"amount_minor": None, "evidence": {"amount_minor": None}, "ambiguities": ["Valor ilegível"]}
    client = OpenWebUI(
        replace(Settings(), openwebui_api_key="key", openwebui_model="model"),
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
                )
            )
        ),
    )
    receipt = client.extract_fields("TOTAL: Ilegível")
    assert receipt.amount_minor is None and receipt.evidence == {}


def test_truncated_llm_response_does_not_become_valid_fields():
    client = OpenWebUI(
        replace(Settings(), openwebui_api_key="key", openwebui_model="model"),
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"choices": [{"finish_reason": "length", "message": {"content": None}}]}
                )
            )
        ),
    )
    with pytest.raises(PipelineError) as exc:
        client.extract_fields("receipt")
    assert exc.value.code == "llm_output_limit"


@pytest.mark.parametrize(
    ("detail", "retryable"), [("Provider returned error", True), ("Invalid input", False)]
)
def test_generic_upstream_provider_failure_has_bounded_retry(detail, retryable):
    client = OpenWebUI(
        replace(Settings(), openwebui_api_key="key"),
        httpx.Client(
            transport=httpx.MockTransport(lambda request: httpx.Response(400, json={"detail": detail}))
        ),
    )
    with pytest.raises(PipelineError) as exc:
        client.request("POST", "/api/chat/completions")
    assert exc.value.retryable is retryable


class Embedder:
    def encode(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


def test_hybrid_rrf_preserves_receipt_evidence_and_does_not_write(receipt):
    calls = []
    index = ReceiptIndex(Settings(), Embedder())

    def hit(rid):
        return {
            "_id": rid,
            "_score": 1,
            "_source": {"receipt_id": rid, "receipt": receipt.model_dump(mode="json"), "text": "evidence"},
        }

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/_mapping"):
            return httpx.Response(200, json={"fai-recibos": index.definition(3)})
        body = json.loads(request.content)
        hits = [hit("a"), hit("b")] if "query" in body else [hit("b"), hit("a")]
        return httpx.Response(200, json={"hits": {"hits": hits}})

    index.client = httpx.Client(transport=httpx.MockTransport(handler))
    results = index.search("text")
    assert len(results) == 2 and results[0]["text"] == "evidence"
    assert all(r.method == "GET" or r.url.path.endswith("/_search") for r in calls)


def test_partial_search_and_mapping_mismatch_are_errors():
    index = ReceiptIndex(Settings(), Embedder())

    def handler(request):
        return httpx.Response(
            200, json={"fai-recibos": {"mappings": {"_meta": {"embedding_model": "other"}}}}
        )

    index.client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(PipelineError) as exc:
        index.search("test")
    assert exc.value.code == "index_incompatible"


def test_indexing_requires_compatible_mapping_and_external_revision(receipt):
    index = ReceiptIndex(Settings(), Embedder())
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith("/_mapping"):
            return httpx.Response(200, json={"fai-recibos": index.definition(3)})
        return httpx.Response(200, json={"result": "updated"})

    index.client = httpx.Client(transport=httpx.MockTransport(handler))
    index.index({"receipt_id": "a", "text": "test", "receipt": receipt.model_dump(mode="json")}, revision=7)
    assert calls[-1].url.params["version"] == "7"
    assert calls[-1].url.params["version_type"] == "external_gte"
