import logging
import signal
import threading
import time

from app.config import Settings
from app.messaging import connect, dispatch_once
from app.persistence import Repository

log = logging.getLogger(__name__)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("pika").setLevel(logging.WARNING)
    settings = Settings.from_env()
    repo = Repository(settings.database_url)
    repo.initialize()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    while not stop.is_set():
        conn = None
        try:
            conn, channel = connect(settings)
            while not stop.is_set():
                repo.heartbeat("dispatcher")
                active = dispatch_once(repo, channel, settings)
                conn.process_data_events(time_limit=0.1 if active else 1)
        except Exception:
            # Não imprime exceções de conexão, que podem conter URLs com senhas.
            log.warning("Publicador sem conexão; nova tentativa em cinco segundos.")
            stop.wait(5)
        finally:
            if conn and conn.is_open:
                conn.close()
    time.sleep(0)


if __name__ == "__main__":
    main()
