import hmac
import json
from hashlib import sha256
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.config import ROOT, Settings
from app.contracts import Approval
from app.persistence import Conflict, Repository
from app.pipeline import approved_document
from app.storage import InvalidFile, save_upload


def task_view(job):
    def iso(value):
        return datetime.fromtimestamp(value, timezone.utc).isoformat()

    return {
        "token": job["token"],
        "kind": job["kind"],
        "status": job["status"],
        "stage": job["stage"],
        "attempts": job["attempts"],
        "filename": job["filename"],
        "mime": job["mime"],
        "created_at": iso(job["created_at"]),
        "updated_at": iso(job["updated_at"]),
        "status_url": "/api/receipt-checks/" + job["token"],
        "result": job.get("result"),
        "error": job.get("error"),
    }


def create_app(settings=None, repository=None):
    settings = settings or Settings.from_env()
    repo = repository or Repository(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        repo.initialize()
        yield
        if repository is None:
            repo.engine.dispose()

    app = FastAPI(title="FAI · Análise de recibos", version="1.0.0", lifespan=lifespan)
    app.state.repo = repo
    app.state.settings = settings

    @app.exception_handler(Conflict)
    async def conflict_handler(request, exc):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(SQLAlchemyError)
    async def database_handler(request, exc):
        return JSONResponse(
            status_code=503, content={"detail": "Não foi possível persistir ou consultar a tarefa."}
        )

    @app.post("/api/receipt-checks", status_code=202)
    def submit(file: UploadFile = File(...), idempotency_key: str | None = Header(default=None)):
        if idempotency_key is not None and not 1 <= len(idempotency_key.strip()) <= 120:
            raise HTTPException(422, "Chave de idempotência inválida.")
        limit = settings.max_upload_mb * 1024 * 1024
        data = file.file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(413, f"O arquivo deve ter até {settings.max_upload_mb} MiB.")
        try:
            path, digest, mime = save_upload(data, settings.storage_dir)
        except InvalidFile as exc:
            raise HTTPException(422, str(exc)) from None
        try:
            job, created = repo.create(
                path=path,
                digest=digest,
                mime=mime,
                filename=Path((file.filename or "recibo").replace("\\", "/")).name[:200],
                key="check:" + idempotency_key.strip() if idempotency_key else None,
            )
        except Exception:
            Path(path).unlink(missing_ok=True)
            raise
        if not created:
            Path(path).unlink(missing_ok=True)
        return task_view(job)

    @app.get("/api/receipt-checks/{token}")
    def status(token: str):
        job = repo.get(token)
        if not job:
            raise HTTPException(404, "Tarefa não encontrada.")
        return task_view(job)

    @app.get("/api/receipt-checks/{token}/file")
    def uploaded_file(token: str):
        job = repo.get(token)
        if not job:
            raise HTTPException(404, "Arquivo não encontrado.")
        path = Path(job["file_path"]).resolve()
        if not path.is_relative_to(settings.storage_dir.resolve()) or not path.is_file():
            raise HTTPException(404, "Arquivo não encontrado.")
        return FileResponse(
            path,
            media_type=job["mime"],
            filename=job["filename"],
            content_disposition_type="inline",
            headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
        )

    @app.post("/api/approved-receipts", status_code=202)
    def approve(approval: Approval, x_index_key: str | None = Header(default=None)):
        if not settings.index_api_key:
            raise HTTPException(503, "A integração de aprovação não está configurada.")
        if not x_index_key or not hmac.compare_digest(x_index_key, settings.index_api_key):
            raise HTTPException(403, "Credencial de integração inválida.")
        check = repo.get(approval.check_token)
        if not check or check["kind"] != "check":
            raise HTTPException(404, "Análise de origem não encontrada.")
        if check["status"] != "succeeded":
            raise HTTPException(409, "A análise precisa estar concluída antes da indexação.")
        # Aprovação é uma decisão externa autenticada, inclusive quando houve suspeita.
        payload = {"document": approved_document(check, approval), "revision": approval.revision}
        job, _ = repo.create(
            path=check["file_path"],
            digest=check["file_hash"],
            mime=check["mime"],
            filename=check["filename"],
            kind="index",
            payload=payload,
            key=f"approval:{approval.receipt_id}:{approval.revision}",
        )
        return task_view(job)

    @app.get("/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    def ready():
        try:
            states = repo.health()
        except SQLAlchemyError:
            return JSONResponse(status_code=503, content={"status": "degraded", "database": False})
        ok = all(states.get(role, False) for role in ("worker", "dispatcher"))
        return JSONResponse(
            status_code=200 if ok else 503,
            content={
                "status": "ok" if ok else "degraded",
                "database": True,
                "processes": {role: states.get(role, False) for role in ("worker", "dispatcher")},
                "scope": "Banco e conexão recente dos processos com RabbitMQ; não certifica OCR/modelo/índice.",
            },
        )

    @app.get("/api/examples")
    def examples():
        path = ROOT / "fixtures/manifest.json"
        if not path.exists():
            return []
        manifest = json.loads(path.read_text())
        return [{"filename": Path(x["file"]).name, "label": x["label"]} for x in manifest["queries"]]

    @app.get("/api/examples/{filename}")
    def example_file(filename: str):
        allowed = {item["filename"] for item in examples()}
        path = ROOT / "fixtures/queries" / filename
        if filename not in allowed or not path.is_file():
            raise HTTPException(404, "Exemplo não encontrado.")
        return FileResponse(path, filename=filename)

    @app.get("/api/reference-receipts")
    def reference_receipts():
        manifest_path = ROOT / "fixtures/manifest.json"
        if not manifest_path.is_file():
            return []
        manifest = json.loads(manifest_path.read_text())
        items = []
        for item in manifest["references"]:
            path = (manifest_path.parent / item["file"]).resolve()
            if (
                not path.is_relative_to((ROOT / "fixtures/reference").resolve())
                or path.suffix.lower() != ".pdf"
                or not path.is_file()
            ):
                continue
            items.append(
                {
                    "receipt_id": item["logical_receipt_id"],
                    "filename": path.name,
                    "label": item["label"],
                    "sha256": item["sha256"],
                    "url": "/api/reference-receipts/" + item["logical_receipt_id"] + "/file",
                }
            )
        return items

    @app.get("/api/reference-receipts/{receipt_id}/file")
    def reference_file(receipt_id: str):
        item = next((x for x in reference_receipts() if x["receipt_id"] == receipt_id), None)
        if not item:
            raise HTTPException(404, "Recibo de referência não encontrado.")
        return FileResponse(
            ROOT / "fixtures/reference" / item["filename"],
            media_type="application/pdf",
            filename=item["filename"],
            content_disposition_type="inline",
            headers={"X-Content-Type-Options": "nosniff"},
        )

    @app.get("/", include_in_schema=False)
    def page():
        frontend = ROOT / "frontend"
        html = (frontend / "index.html").read_text()
        # Cada versão usa uma URL diferente, inclusive se o navegador guardou o JS anterior.
        for asset in ("app.js", "styles.css"):
            version = sha256((frontend / asset).read_bytes()).hexdigest()[:16]
            html = html.replace(f"/static/{asset}", f"/static/{asset}?v={version}")
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")
    return app


app = create_app()
