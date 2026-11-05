import json
import logging
import signal
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.config import Settings
from app.integrations import PipelineError
from app.messaging import connect
from app.persistence import Conflict, Repository
from app.pipeline import Pipeline

log = logging.getLogger(__name__)


def execute(repo, pipeline, job, settings):
    try:
        result = pipeline.process(job, lambda value: repo.stage(job, value))
        return "succeeded" if repo.complete(job, result) else "lost"
    except PipelineError as exc:
        return repo.fail(
            job,
            {"code": exc.code, "message": str(exc)},
            retryable=exc.retryable,
            max_attempts=settings.max_attempts,
        )
    except Conflict:
        return "lost"
    except Exception:
        log.error("task_id=%s falha interna no processamento.", job["id"])
        return repo.fail(
            job,
            {"code": "processing_error", "message": "Falha interna no processamento."},
            retryable=True,
            max_attempts=settings.max_attempts,
        )


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("pika").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings.from_env()
    repo = Repository(settings.database_url)
    repo.initialize()
    pipeline = Pipeline(settings, text_cache=repo)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    with ThreadPoolExecutor(max_workers=1) as pool:
        while not stop.is_set():
            conn = None
            try:
                conn, channel = connect(settings)
                last_heartbeat = 0
                while not stop.is_set():
                    if time.monotonic() - last_heartbeat > 5:
                        repo.heartbeat("worker")
                        last_heartbeat = time.monotonic()
                    method, _, body = channel.basic_get(settings.queue, auto_ack=False)
                    if not method:
                        conn.process_data_events(time_limit=0.5)
                        continue
                    try:
                        task_id = json.loads(body)["task_id"]
                        if not isinstance(task_id, str):
                            raise ValueError()
                    except (ValueError, TypeError, KeyError):
                        channel.basic_nack(method.delivery_tag, requeue=False)
                        continue
                    job = repo.acquire(task_id, settings.lease_seconds, settings.max_attempts)
                    if not job:
                        channel.basic_ack(method.delivery_tag)
                        continue
                    log.info("task_id=%s início tentativa=%s tipo=%s", task_id, job["attempts"], job["kind"])
                    future = pool.submit(execute, repo, pipeline, job, settings)
                    renewed = time.monotonic()
                    while not future.done():
                        # Mantém a conexão AMQP viva enquanto OCR/LLM executam em outra thread.
                        conn.process_data_events(time_limit=0.5)
                        if time.monotonic() - renewed >= min(5, settings.lease_seconds / 3):
                            repo.renew(job, settings.lease_seconds)
                            repo.heartbeat("worker")
                            renewed = time.monotonic()
                    outcome = future.result()
                    if outcome == "failed":
                        channel.basic_nack(method.delivery_tag, requeue=False)
                    else:
                        channel.basic_ack(method.delivery_tag)
                    log.info("task_id=%s estado=%s", task_id, outcome)
            except Exception:
                log.warning("Worker sem conexão; nova tentativa em cinco segundos.")
                stop.wait(5)
            finally:
                if conn and conn.is_open:
                    conn.close()


if __name__ == "__main__":
    main()
