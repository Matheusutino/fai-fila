import json

import pika


def connect(settings):
    params = pika.URLParameters(settings.rabbitmq_url)
    params.heartbeat = 30
    params.blocked_connection_timeout = 15
    params.socket_timeout = 5
    params.connection_attempts = 1
    conn = pika.BlockingConnection(params)
    channel = conn.channel()
    dead = settings.queue + ".dead"
    channel.exchange_declare(exchange=dead, exchange_type="fanout", durable=True)
    channel.queue_declare(queue=dead, durable=True)
    channel.queue_bind(queue=dead, exchange=dead)
    channel.queue_declare(queue=settings.queue, durable=True, arguments={"x-dead-letter-exchange": dead})
    channel.basic_qos(prefetch_count=1)
    channel.confirm_delivery()
    return conn, channel


def dispatch_once(repo, channel, settings):
    repo.recover(settings.max_attempts)
    item = repo.claim_publication()
    if not item:
        return False
    try:
        channel.basic_publish(
            exchange="",
            routing_key=settings.queue,
            body=json.dumps({"task_id": item["job_id"]}).encode(),
            mandatory=True,
            properties=pika.BasicProperties(
                delivery_mode=2, content_type="application/json", message_id=item["id"]
            ),
        )
        repo.published(item)
    except Exception:
        repo.publication_failed(item)
        raise
    return True
