"""Tarefas e outbox transacional. SQLite local; PostgreSQL no Compose."""

import secrets
import time
import uuid
from pathlib import Path

from sqlalchemy import (
    JSON,
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    and_,
    create_engine,
    or_,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool

metadata = MetaData()
jobs = Table(
    "jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("token", String(80), unique=True, nullable=False),
    Column("kind", String(20), nullable=False),
    Column("status", String(20), nullable=False),
    Column("stage", String(30), nullable=False),
    Column("file_path", String, nullable=False),
    Column("file_hash", String(64), nullable=False),
    Column("mime", String(50), nullable=False),
    Column("filename", String, nullable=False),
    Column("idempotency_key", String(160), unique=True),
    Column("payload", JSON, nullable=False),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("lease_until", Float),
    Column("owner", String(36)),
    Column("result", JSON),
    Column("error", JSON),
)
outbox = Table(
    "outbox",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("job_id", String(36), nullable=False),
    Column("generation", Integer, nullable=False),
    Column("available_at", Float, nullable=False),
    Column("sent_at", Float),
    Column("lock_until", Float),
    Column("owner", String(36)),
    UniqueConstraint("job_id", "generation"),
)
heartbeats = Table(
    "heartbeats",
    metadata,
    Column("role", String(30), primary_key=True),
    Column("seen_at", Float, nullable=False),
)
extractions = Table(
    "extractions",
    metadata,
    Column("file_hash", String(64), primary_key=True),
    Column("version", String(100), primary_key=True),
    Column("text", String, nullable=False),
    Column("remote_id", String, nullable=False),
)


class Conflict(ValueError):
    pass


class Repository:
    def __init__(self, url: str):
        if url.startswith("sqlite:///") and ":memory:" not in url:
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        options = (
            {"connect_args": {"check_same_thread": False, "timeout": 30}} if url.startswith("sqlite") else {}
        )
        if ":memory:" in url:
            options["poolclass"] = StaticPool
        self.engine = create_engine(url, pool_pre_ping=True, **options)

    def initialize(self):
        # Schema v1, aditivo. Mudanças posteriores exigem migração explícita.
        with self.engine.begin() as conn:
            if self.engine.dialect.name == "postgresql":
                conn.exec_driver_sql("SELECT pg_advisory_xact_lock(726104892)")
            elif self.engine.dialect.name == "sqlite":
                conn.exec_driver_sql("BEGIN IMMEDIATE")
            metadata.create_all(conn)

    def get(self, token: str):
        with self.engine.connect() as conn:
            return conn.execute(select(jobs).where(jobs.c.token == token)).mappings().first()

    def by_id(self, task_id: str):
        with self.engine.connect() as conn:
            return conn.execute(select(jobs).where(jobs.c.id == task_id)).mappings().first()

    def cached_text(self, digest, version):
        with self.engine.connect() as conn:
            cached = (
                conn.execute(
                    select(extractions).where(
                        extractions.c.file_hash == digest, extractions.c.version == version
                    )
                )
                .mappings()
                .first()
            )
            if cached:
                return cached["text"], cached["remote_id"]
            # Aproveita extrações reais já concluídas antes da introdução do cache v1.
            if version == "v1":
                candidates = (
                    conn.execute(
                        select(jobs.c.result)
                        .where(
                            jobs.c.file_hash == digest, jobs.c.kind == "check", jobs.c.status == "succeeded"
                        )
                        .order_by(jobs.c.updated_at.desc())
                        .limit(1)
                    )
                    .scalars()
                    .all()
                )
                for result in candidates:
                    if (
                        result
                        and result.get("pipeline_version") == "receipts-v1"
                        and result.get("text")
                        and result.get("openwebui_file_id")
                    ):
                        return result["text"], result["openwebui_file_id"]
        return None

    def cache_text(self, digest, version, text, remote_id):
        with self.engine.begin() as conn:
            try:
                with conn.begin_nested():
                    conn.execute(
                        extractions.insert().values(
                            file_hash=digest, version=version, text=text, remote_id=remote_id
                        )
                    )
            except IntegrityError:
                pass  # O primeiro texto completo de uma versão fica preservado.

    def create(self, *, path, digest, mime, filename, key=None, kind="check", payload=None):
        payload = payload or {}
        now = time.time()
        task_id = str(uuid.uuid4())
        row = dict(
            id=task_id,
            token=secrets.token_urlsafe(32),
            kind=kind,
            status="pending",
            stage="waiting",
            file_path=path,
            file_hash=digest,
            mime=mime,
            filename=filename,
            idempotency_key=key,
            payload=payload,
            created_at=now,
            updated_at=now,
            attempts=0,
        )
        try:
            with self.engine.begin() as conn:
                conn.execute(jobs.insert().values(**row))
                self._enqueue(conn, task_id, 0, now)
        except IntegrityError:
            if not key:
                raise
            with self.engine.connect() as conn:
                existing = conn.execute(select(jobs).where(jobs.c.idempotency_key == key)).mappings().first()
            if (
                not existing
                or existing["file_hash"] != digest
                or existing["payload"] != payload
                or existing["kind"] != kind
            ):
                raise Conflict("A chave de idempotência já foi usada com outro conteúdo.") from None
            return dict(existing), False
        return row, True

    @staticmethod
    def _enqueue(conn, task_id, generation, available):
        conn.execute(
            outbox.insert().values(
                id=str(uuid.uuid4()), job_id=task_id, generation=generation, available_at=available
            )
        )

    def claim_publication(self):
        now, owner = time.time(), str(uuid.uuid4())
        ready = and_(
            outbox.c.sent_at.is_(None),
            outbox.c.available_at <= now,
            or_(outbox.c.lock_until.is_(None), outbox.c.lock_until < now),
        )
        with self.engine.begin() as conn:
            stmt = select(outbox.c.id).where(ready).order_by(outbox.c.available_at).limit(1)
            if self.engine.dialect.name == "postgresql":
                stmt = stmt.with_for_update(skip_locked=True)
            item_id = conn.execute(stmt).scalar()
            if not item_id:
                return None
            changed = conn.execute(
                update(outbox).where(outbox.c.id == item_id, ready).values(owner=owner, lock_until=now + 60)
            ).rowcount
            if not changed:
                return None
            return dict(conn.execute(select(outbox).where(outbox.c.id == item_id)).mappings().one())

    def published(self, item):
        now = time.time()
        with self.engine.begin() as conn:
            changed = conn.execute(
                update(outbox)
                .where(outbox.c.id == item["id"], outbox.c.owner == item["owner"])
                .values(sent_at=now, lock_until=None)
            ).rowcount
            if changed:
                conn.execute(
                    update(jobs)
                    .where(jobs.c.id == item["job_id"], jobs.c.status.in_(["pending", "retrying"]))
                    .values(status="queued", updated_at=now)
                )

    def publication_failed(self, item):
        with self.engine.begin() as conn:
            conn.execute(
                update(outbox)
                .where(outbox.c.id == item["id"], outbox.c.owner == item["owner"])
                .values(owner=None, lock_until=None, available_at=time.time() + 5)
            )

    def acquire(self, task_id, lease_seconds, max_attempts):
        now, owner = time.time(), str(uuid.uuid4())
        with self.engine.begin() as conn:
            changed = conn.execute(
                update(jobs)
                .where(
                    jobs.c.id == task_id,
                    jobs.c.status.in_(["pending", "queued", "retrying"]),
                    jobs.c.attempts < max_attempts,
                )
                .values(
                    status="processing",
                    stage="extracting",
                    owner=owner,
                    lease_until=now + lease_seconds,
                    attempts=jobs.c.attempts + 1,
                    updated_at=now,
                    error=None,
                )
            ).rowcount
            if not changed:
                return None
            return dict(conn.execute(select(jobs).where(jobs.c.id == task_id)).mappings().one())

    @staticmethod
    def _owned(job):
        return and_(
            jobs.c.id == job["id"],
            jobs.c.owner == job["owner"],
            jobs.c.status == "processing",
            jobs.c.lease_until > time.time(),
        )

    def renew(self, job, lease_seconds):
        with self.engine.begin() as conn:
            return bool(
                conn.execute(
                    update(jobs)
                    .where(self._owned(job))
                    .values(lease_until=time.time() + lease_seconds, updated_at=time.time())
                ).rowcount
            )

    def stage(self, job, stage):
        with self.engine.begin() as conn:
            if not conn.execute(
                update(jobs).where(self._owned(job)).values(stage=stage, updated_at=time.time())
            ).rowcount:
                raise Conflict("A execução perdeu a posse da tarefa.")

    def complete(self, job, result):
        with self.engine.begin() as conn:
            return bool(
                conn.execute(
                    update(jobs)
                    .where(self._owned(job))
                    .values(
                        status="succeeded",
                        stage="completed",
                        result=result,
                        error=None,
                        lease_until=None,
                        owner=None,
                        updated_at=time.time(),
                    )
                ).rowcount
            )

    def fail(self, job, error, *, retryable, max_attempts):
        retry = retryable and job["attempts"] < max_attempts
        now = time.time()
        with self.engine.begin() as conn:
            changed = conn.execute(
                update(jobs)
                .where(self._owned(job))
                .values(
                    status="retrying" if retry else "failed",
                    stage="waiting" if retry else "failed",
                    error=error,
                    owner=None,
                    lease_until=None,
                    updated_at=now,
                )
            ).rowcount
            if changed and retry:
                self._enqueue(conn, job["id"], job["attempts"], now + min(60, 2 ** job["attempts"]))
        return "retrying" if changed and retry else "failed" if changed else "lost"

    def recover(self, max_attempts):
        now = time.time()
        with self.engine.begin() as conn:
            stmt = select(jobs).where(jobs.c.status == "processing", jobs.c.lease_until <= now)
            if self.engine.dialect.name == "postgresql":
                stmt = stmt.with_for_update(skip_locked=True)
            for job in conn.execute(stmt).mappings():
                retry = job["attempts"] < max_attempts
                changed = conn.execute(
                    update(jobs)
                    .where(jobs.c.id == job["id"], jobs.c.status == "processing", jobs.c.lease_until <= now)
                    .values(
                        status="retrying" if retry else "failed",
                        stage="waiting" if retry else "failed",
                        owner=None,
                        lease_until=None,
                        updated_at=now,
                        error={
                            "code": "worker_interrupted",
                            "message": "Execução interrompida; prazo de posse expirado.",
                        },
                    )
                ).rowcount
                if changed and retry:
                    self._enqueue(conn, job["id"], job["attempts"], now)

    def heartbeat(self, role):
        with self.engine.begin() as conn:
            # Atualização seguida de inserção tolera reinícios e múltiplas instâncias.
            if conn.execute(
                update(heartbeats).where(heartbeats.c.role == role).values(seen_at=time.time())
            ).rowcount:
                return
            try:
                with conn.begin_nested():
                    conn.execute(heartbeats.insert().values(role=role, seen_at=time.time()))
            except IntegrityError:
                pass

    def health(self):
        with self.engine.connect() as conn:
            conn.execute(select(1))
            return {r.role: time.time() - r.seen_at < 30 for r in conn.execute(select(heartbeats))}
