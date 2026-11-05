from pathlib import Path
from time import perf_counter

from app.contracts import Receipt
from app.integrations import OpenWebUI, ReceiptIndex
from app.rules import evaluate

PIPELINE_VERSION = "receipts-v1"


class Pipeline:
    def __init__(self, settings, extractor=None, index=None, text_cache=None):
        self.settings = settings
        self.extractor = extractor or OpenWebUI(settings)
        self.index = index or ReceiptIndex(settings)
        self.text_cache = text_cache

    def extract(self, job, stage=lambda value: None):
        digest = job.get("file_hash")
        cached = (
            self.text_cache.cached_text(digest, self.settings.ocr_cache_version)
            if self.text_cache and digest
            else None
        )
        if cached:
            text, remote_id = cached
        else:
            text, remote_id = self.extractor.extract_text(Path(job["file_path"]), job["mime"])
            if self.text_cache and digest:
                self.text_cache.cache_text(digest, self.settings.ocr_cache_version, text, remote_id)
        stage("structuring")
        receipt = self.extractor.extract_fields(text)
        return text, receipt, remote_id

    def process(self, job, stage):
        started = perf_counter()
        if job["kind"] == "index":
            stage("indexing")
            document = job["payload"]["document"]
            self.index.index(document, revision=job["payload"]["revision"])
            return {
                "receipt_id": document["receipt_id"],
                "indexed": True,
                "revision": job["payload"]["revision"],
            }
        stage("extracting")
        text, receipt, remote_id = self.extract(job, stage)
        stage("retrieving")
        candidates = self.index.search(text)
        stage("comparing")
        result = evaluate(receipt, candidates)
        result.update(
            text=text,
            openwebui_file_id=remote_id,
            pipeline_version=PIPELINE_VERSION,
            retrieval={
                "requested_top_k": self.settings.top_k,
                "returned_receipts": len(candidates),
                "method": "hybrid",
            },
            duration_ms=round((perf_counter() - started) * 1000),
        )
        return result


def approved_document(check, approval):
    result = check["result"]
    # Revalida o contrato antes de promover o resultado para a base aceita.
    receipt = Receipt.model_validate(result["receipt"])
    return {
        "receipt_id": approval.receipt_id,
        "approval_id": approval.approval_id,
        "project": approval.project,
        "file_hash": check["file_hash"],
        "source_file": check["filename"],
        "text": result["text"],
        "receipt": receipt.model_dump(mode="json"),
        "openwebui_file_id": result["openwebui_file_id"],
        "pipeline_version": result["pipeline_version"],
    }
