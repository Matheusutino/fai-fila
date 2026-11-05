"""Testes opcionais em filas exclusivas; nunca removem a fila da aplicação."""

import os
import uuid
from dataclasses import replace

import pika
import pytest
from sqlalchemy import update

from app.config import Settings
from app.messaging import connect, dispatch_once
from app.persistence import outbox

pytestmark = pytest.mark.skipif(os.getenv("RUN_BROKER_TESTS") != "1", reason="Requer RabbitMQ real.")


@pytest.fixture
def broker_settings():
    settings = replace(Settings.from_env(), queue="fai.test." + uuid.uuid4().hex)
    yield settings
    conn, channel = connect(settings)
    channel.queue_delete(settings.queue)
    channel.queue_delete(settings.queue + ".dead")
    channel.exchange_delete(settings.queue + ".dead")
    conn.close()


def test_redelivery_after_result_commit_before_ack(repo, broker_settings):
    settings = broker_settings
    job, _ = repo.create(path="test.pdf", digest="a" * 64, mime="application/pdf", filename="test.pdf")
    conn, channel = connect(settings)
    assert dispatch_once(repo, channel, settings)
    method, _, body = channel.basic_get(settings.queue, auto_ack=False)
    assert method and job["id"].encode() in body
    acquired = repo.acquire(job["id"], 90, 3)
    assert repo.complete(acquired, {"decision": "inconclusive"})
    # Fecha o canal sem ACK, como uma queda logo após o commit.
    conn.close()
    conn, channel = connect(settings)
    method, _, _ = channel.basic_get(settings.queue, auto_ack=False)
    assert method and method.redelivered
    assert repo.acquire(job["id"], 90, 3) is None
    channel.basic_ack(method.delivery_tag)
    assert channel.basic_get(settings.queue)[0] is None
    conn.close()


def test_unroutable_publication_stays_pending(repo, broker_settings):
    settings = broker_settings
    job, _ = repo.create(path="test.pdf", digest="a" * 64, mime="application/pdf", filename="test.pdf")
    conn, channel = connect(settings)
    channel.queue_delete(settings.queue)
    with pytest.raises(pika.exceptions.UnroutableError):
        dispatch_once(repo, channel, settings)
    assert repo.get(job["token"])["status"] == "pending"
    conn.close()
    conn, channel = connect(settings)
    with repo.engine.begin() as db:
        db.execute(update(outbox).values(available_at=0))
    assert dispatch_once(repo, channel, settings)
    assert repo.get(job["token"])["status"] == "queued"
    conn.close()
