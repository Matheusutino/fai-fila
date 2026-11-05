import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///var/tasks.db"
    rabbitmq_url: str = field(default="amqp://fai:fai-local@localhost:5673/%2F", repr=False)
    storage_dir: Path = ROOT / "var/uploads"
    elasticsearch_url: str = "http://localhost:9201"
    openwebui_base_url: str = "http://localhost:35000"
    openwebui_api_key: str = field(default="", repr=False)
    openwebui_model: str = ""
    index_api_key: str = field(default="", repr=False)
    receipt_index: str = "fai-recibos"
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    top_k: int = 5
    max_upload_mb: int = 10
    extraction_timeout: float = 300
    request_timeout: float = 120
    extraction_max_tokens: int = 4096
    extraction_reasoning_effort: str = ""
    ocr_cache_version: str = "v1"
    lease_seconds: int = 90
    max_attempts: int = 3
    poll_seconds: float = 2
    queue: str = "fai.receipts"

    def __post_init__(self):
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,80}", self.receipt_index):
            raise ValueError("RECEIPT_INDEX inválido.")
        if (
            min(
                self.top_k,
                self.max_upload_mb,
                self.extraction_timeout,
                self.request_timeout,
                self.extraction_max_tokens,
                self.lease_seconds,
                self.max_attempts,
                self.poll_seconds,
            )
            <= 0
        ):
            raise ValueError("Limites e prazos devem ser positivos.")
        if self.extraction_reasoning_effort not in ("", "none", "minimal", "low", "medium", "high"):
            raise ValueError("EXTRACTION_REASONING_EFFORT inválido.")

    @classmethod
    def from_env(cls):
        # O arquivo novo tem prioridade; a referência fornece apenas valores ausentes.
        load_dotenv(ROOT / ".env", override=False)
        load_dotenv(ROOT / "fai-elasticsearch/.env", override=False)
        return cls(
            database_url=os.getenv("DATABASE_URL", cls.database_url),
            rabbitmq_url=os.getenv("RABBITMQ_URL", cls.rabbitmq_url),
            storage_dir=Path(os.getenv("STORAGE_DIR", str(cls.storage_dir))).resolve(),
            elasticsearch_url=os.getenv("ELASTICSEARCH_URL", cls.elasticsearch_url).rstrip("/"),
            openwebui_base_url=os.getenv("OPENWEBUI_BASE_URL", cls.openwebui_base_url).rstrip("/"),
            openwebui_api_key=os.getenv("OPENWEBUI_API_KEY", ""),
            openwebui_model=os.getenv("OPENWEBUI_MODEL", ""),
            index_api_key=os.getenv("INDEX_API_KEY", ""),
            receipt_index=os.getenv("RECEIPT_INDEX", cls.receipt_index),
            embedding_model=os.getenv("EMBEDDING_MODEL", cls.embedding_model),
            top_k=int(os.getenv("TOP_K", "5")),
            max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "10")),
            extraction_timeout=float(os.getenv("EXTRACTION_TIMEOUT_SECONDS", "300")),
            request_timeout=float(os.getenv("REQUEST_TIMEOUT_SECONDS", "120")),
            extraction_max_tokens=int(os.getenv("EXTRACTION_MAX_TOKENS", "4096")),
            extraction_reasoning_effort=os.getenv("EXTRACTION_REASONING_EFFORT", ""),
            ocr_cache_version=os.getenv("OCR_CACHE_VERSION", "v1"),
            lease_seconds=int(os.getenv("LEASE_SECONDS", "90")),
            max_attempts=int(os.getenv("MAX_ATTEMPTS", "3")),
        )
