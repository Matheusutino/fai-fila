"""Carga explícita dos originais sintéticos como recibos aceitos na demo."""

import argparse
import hashlib
import json
import mimetypes
from pathlib import Path

from app.config import ROOT, Settings
from app.integrations import PipelineError
from app.pipeline import PIPELINE_VERSION, Pipeline


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "fixtures/manifest.json")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    pipeline = Pipeline(Settings.from_env())
    manifest = json.loads(args.manifest.read_text())
    for item in manifest["references"][: args.limit]:
        path = (args.manifest.parent / item["file"]).resolve()
        if not path.is_relative_to(args.manifest.parent.resolve() / "reference"):
            raise SystemExit("O manifesto deve indexar apenas arquivos da pasta reference/.")
        rid = item["logical_receipt_id"]
        print(f"Extraindo {rid} pelo OpenWebUI…", flush=True)
        try:
            text, receipt, remote_id = pipeline.extract(
                {"file_path": str(path), "mime": mimetypes.guess_type(path)[0]},
                lambda value: print(f"{rid}: texto obtido; estruturando campos…", flush=True),
            )
            document = {
                "receipt_id": rid,
                "approval_id": "demo-initial-load",
                "project": "DEMO",
                "file_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
                "source_file": path.name,
                "text": text,
                "receipt": receipt.model_dump(mode="json"),
                "openwebui_file_id": remote_id,
                "pipeline_version": PIPELINE_VERSION,
            }
            pipeline.index.index(document, revision=1)
        except PipelineError as exc:
            raise SystemExit(f"{exc.code}: {exc}") from None
        print(f"{rid} indexado (campos extraídos, sem usar o gabarito).", flush=True)


if __name__ == "__main__":
    main()
