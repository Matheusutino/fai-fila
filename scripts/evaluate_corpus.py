"""Avalia consultas pelo fluxo HTTP/fila real contra o gabarito do corpus."""

import argparse
import json
import mimetypes
import time
from pathlib import Path

import httpx

from app.config import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--manifest", type=Path, default=ROOT / "fixtures/manifest.json")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--filename", help="Avalia apenas este nome de arquivo de consulta.")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--report", type=Path, default=ROOT / "var/evaluation.json")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    queries = manifest["queries"]
    if args.filename:
        queries = [item for item in queries if Path(item["file"]).name == args.filename]
        if not queries:
            raise SystemExit("Arquivo de consulta não encontrado no manifesto.")
    results = []
    with httpx.Client(base_url=args.base_url, timeout=30, trust_env=False) as client:
        for item in queries[: args.limit]:
            path = args.manifest.parent / item["file"]
            with path.open("rb") as handle:
                response = client.post(
                    "/api/receipt-checks", files={"file": (path.name, handle, mimetypes.guess_type(path)[0])}
                )
            response.raise_for_status()
            accepted = response.json()
            deadline = time.monotonic() + args.timeout
            while True:
                response = client.get(accepted["status_url"])
                response.raise_for_status()
                task = response.json()
                if task["status"] in ("succeeded", "failed") or time.monotonic() >= deadline:
                    break
                time.sleep(2)
            result = task.get("result") or {}
            matches = result.get("matches", [])
            origin = item.get("source_receipt_id")
            retrieved = any(m["receipt_id"] == origin for m in matches) if origin else None
            passed = result.get("decision") == item["expected_policy_decision"]
            results.append(
                {
                    "file": item["file"],
                    "token": accepted["token"],
                    "status": task["status"],
                    "expected": item["expected_policy_decision"],
                    "actual": result.get("decision"),
                    "origin_in_top_k": retrieved,
                    "passed": passed,
                    "error": task.get("error"),
                    "extracted_fields": result.get("receipt"),
                    "true_fields": item["true_fields"],
                }
            )
            print(
                f"{path.name}: {task['status']} / {result.get('decision')} / esperado={item['expected_policy_decision']} / top-k={retrieved}",
                flush=True,
            )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(
            {"results": results, "passed": sum(r["passed"] for r in results), "total": len(results)},
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(f"Relatório salvo em {args.report}")
    raise SystemExit(0 if all(r["passed"] for r in results) else 1)


if __name__ == "__main__":
    main()
