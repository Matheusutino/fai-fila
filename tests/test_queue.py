import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from sqlalchemy import select, update

from app.config import Settings
from app.integrations import PipelineError
from app.messaging import dispatch_once
from app.persistence import Conflict, jobs, outbox
from app.worker import execute


def new(repo, **kw):
    return repo.create(
        path="/tmp/example.pdf", digest="a" * 64, mime="application/pdf", filename="example.pdf", **kw
    )[0]


class Channel:
    def __init__(self, fail=False):
        self.messages = []
        self.fail = fail

    def basic_publish(self, **message):
        if self.fail:
            raise ConnectionError("broker unavailable")
        self.messages.append(message)


def test_transactional_acceptance_and_publisher_recovery(repo):
    job = new(repo)
    with pytest.raises(ConnectionError):
        dispatch_once(repo, Channel(fail=True), Settings())
    assert repo.get(job["token"])["status"] == "pending"
    with repo.engine.begin() as conn:
        conn.execute(update(outbox).values(available_at=0))
    channel = Channel()
    assert dispatch_once(repo, channel, Settings())
    assert repo.get(job["token"])["status"] == "queued"
    assert len(channel.messages) == 1
    assert channel.messages[0]["mandatory"] is True
    assert channel.messages[0]["properties"].delivery_mode == 2


def test_idempotency_and_payload_conflict(repo):
    job = new(repo, key="one")
    again, created = repo.create(
        path="other", digest="a" * 64, mime="application/pdf", filename="new", key="one"
    )
    assert again["token"] == job["token"] and not created
    with pytest.raises(Conflict):
        repo.create(path="other", digest="b" * 64, mime="application/pdf", filename="new", key="one")


def test_two_workers_only_one_acquires(repo):
    job = new(repo)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: repo.acquire(job["id"], 90, 3), range(2)))
    assert sum(r is not None for r in results) == 1


def test_publication_cannot_regress_processing_status(repo):
    job = new(repo)
    item = repo.claim_publication()
    acquired = repo.acquire(job["id"], 90, 3)
    repo.published(item)
    assert repo.get(job["token"])["status"] == "processing"
    assert repo.complete(acquired, {"decision": "inconclusive"})
    assert repo.acquire(job["id"], 90, 3) is None


def test_crash_before_ack_preserves_completed_result(repo):
    job = new(repo)
    acquired = repo.acquire(job["id"], 90, 3)
    assert repo.complete(acquired, {"decision": "no_duplicate_found"})
    assert repo.acquire(job["id"], 90, 3) is None
    assert repo.get(job["token"])["result"]["decision"] == "no_duplicate_found"


def test_expired_owner_cannot_overwrite_recovered_task(repo):
    job = new(repo)
    old = repo.acquire(job["id"], 90, 3)
    with repo.engine.begin() as conn:
        conn.execute(update(jobs).where(jobs.c.id == job["id"]).values(lease_until=time.time() - 1))
    repo.recover(3)
    current = repo.acquire(job["id"], 90, 3)
    assert current["owner"] != old["owner"]
    assert repo.complete(old, {"bad": "old"}) is False
    assert repo.complete(current, {"good": "new"})


def test_retry_limit_and_non_retryable_failure(repo):
    job = new(repo)
    settings = replace(Settings(), max_attempts=2)

    class Broken:
        def process(self, job, stage):
            raise PipelineError("offline", "Elasticsearch indisponível.")

    first = repo.acquire(job["id"], 90, 2)
    assert execute(repo, Broken(), first, settings) == "retrying"
    second = repo.acquire(job["id"], 90, 2)
    assert execute(repo, Broken(), second, settings) == "failed"
    assert repo.get(job["token"])["result"] is None
    with repo.engine.connect() as conn:
        assert len(conn.execute(select(outbox)).all()) == 2


def test_unknown_exception_does_not_leak_credentials(repo):
    job = new(repo)
    acquired = repo.acquire(job["id"], 90, 1)

    class Broken:
        def process(self, *args):
            raise RuntimeError("secret-api-key")

    execute(repo, Broken(), acquired, replace(Settings(), max_attempts=1))
    assert "secret" not in str(repo.get(job["token"])["error"])
