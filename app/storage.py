import hashlib
import uuid
from pathlib import Path

import pymupdf
from PIL import Image


class InvalidFile(ValueError):
    pass


def save_upload(data: bytes, directory: Path) -> tuple[str, str, str]:
    if not data:
        raise InvalidFile("O arquivo está vazio.")
    if data.startswith(b"%PDF-"):
        try:
            with pymupdf.open(stream=data, filetype="pdf") as doc:
                if doc.is_encrypted or not 1 <= len(doc) <= 10:
                    raise InvalidFile("Use um PDF sem senha, de até dez páginas.")
        except (RuntimeError, ValueError) as exc:
            raise InvalidFile("PDF inválido ou protegido.") from exc
        suffix, mime = ".pdf", "application/pdf"
    else:
        try:
            import io

            with Image.open(io.BytesIO(data)) as img:
                if img.format not in ("JPEG", "PNG") or img.width * img.height > 25_000_000:
                    raise InvalidFile("Use JPEG/PNG de até 25 megapixels.")
                suffix, mime = (".png", "image/png") if img.format == "PNG" else (".jpg", "image/jpeg")
                img.verify()
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise InvalidFile("Envie um PDF, JPEG ou PNG legível.") from exc
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (uuid.uuid4().hex + suffix)
    path.write_bytes(data)
    return str(path), hashlib.sha256(data).hexdigest(), mime
