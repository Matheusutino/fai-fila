"""Gerencia API, publicador e worker locais; banco e RabbitMQ devem estar ativos."""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from app.config import ROOT

REGISTRY = ROOT / "var/dev-processes.json"
COMMANDS = {
    "api": ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8010"],
    "dispatcher": ["-m", "app.dispatcher"],
    "worker": ["-m", "app.worker"],
}


def alive(pid, role):
    try:
        os.kill(pid, 0)
        proc = Path(f"/proc/{pid}")
        # Em Linux, valida também o projeto e módulo antes de sinalizar um PID salvo.
        if proc.exists():
            return (
                proc.joinpath("cwd").resolve() == ROOT
                and COMMANDS[role][1].encode() in proc.joinpath("cmdline").read_bytes()
            )
        return True
    except (OSError, ProcessLookupError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status"])
    args = parser.parse_args()
    processes = json.loads(REGISTRY.read_text()) if REGISTRY.exists() else {}
    if args.action == "start":
        logs = ROOT / "var/logs"
        logs.mkdir(parents=True, exist_ok=True)
        for role, command in COMMANDS.items():
            existing = processes.get(role)
            if existing and alive(existing, role):
                continue
            with (logs / f"{role}.log").open("ab") as log:
                process = subprocess.Popen(
                    [sys.executable, *command],
                    cwd=ROOT,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            processes[role] = process.pid
        REGISTRY.write_text(json.dumps(processes))
        time.sleep(1)
    elif args.action == "stop":
        for role, pid in processes.items():
            if alive(pid, role):
                os.kill(pid, signal.SIGTERM)
        print("Parada solicitada; o worker termina o processamento atual antes de sair.")
        return
    for role in COMMANDS:
        pid = processes.get(role)
        print(f"{role}: {'ativo' if pid and alive(pid, role) else 'parado'}")


if __name__ == "__main__":
    main()
