"""Gera originais, duplicadas visuais e negativos, com gabarito independente."""

import argparse
import hashlib
import io
import json
import random
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

from app.config import ROOT


def pdf_bytes(receipt):
    doc = pymupdf.open()
    page = doc.new_page(width=390, height=510)
    page.draw_rect((20, 20, 370, 490), color=(0.15, 0.35, 0.27), width=1)
    lines = [
        ("DOCUMENTO SINTETICO - SEM VALOR FISCAL", 10),
        ("RECIBO DE DESPESA", 20),
        (receipt.get("merchant_name") or "Estabelecimento nao identificado", 16),
        ("CNPJ ficticio: " + (receipt.get("merchant_tax_id") or "Nao informado"), 11),
        ("Numero do recibo: " + (receipt.get("receipt_identifier") or "Nao informado"), 12),
        (
            "Data da transacao: "
            + (
                "/".join(reversed(receipt["transaction_date"].split("-")))
                if receipt.get("transaction_date")
                else "Nao informada"
            ),
            12,
        ),
        ("Servico: refeicao durante viagem de trabalho", 11),
        (
            "TOTAL PAGO: "
            + (
                f"R$ {receipt['amount_minor'] / 100:.2f}".replace(".", ",")
                if receipt.get("amount_minor") is not None
                else "Ilegivel"
            ),
            18,
        ),
        ("Moeda: " + (receipt.get("currency") or "Nao informada"), 11),
        ("Pagamento recebido. Exemplo para demonstracao.", 10),
        ("Nao corresponde a uma transacao real.", 10),
    ]
    y = 55
    for text, size in lines:
        page.insert_text((35, y), text, fontsize=size, color=(0.1, 0.2, 0.15))
        y += 35
    data = doc.tobytes(deflate=True, no_new_id=True)
    doc.close()
    return data


def render(data):
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
        return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")


def generate(output: Path, seed=42):
    rng = random.Random(seed)
    for directory in ("reference", "queries"):
        (output / directory).mkdir(parents=True, exist_ok=True)
    manifest = {"schema_version": 1, "seed": seed, "references": [], "queries": []}

    def record(
        group,
        name,
        data,
        receipt,
        logical_id,
        label,
        origin=None,
        transformation="original",
        duplicate=False,
        expected="no_duplicate_found",
    ):
        path = output / group / name
        path.write_bytes(data)
        item = {
            "file": f"{group}/{name}",
            "sha256": hashlib.sha256(data).hexdigest(),
            "logical_receipt_id": logical_id,
            "source_receipt_id": origin,
            "label": label,
            "transformation": transformation,
            "seed": seed,
            "true_fields": receipt,
            "is_duplicate": duplicate,
            "expected_policy_decision": expected,
        }
        manifest["references" if group == "reference" else "queries"].append(item)

    originals = []
    for i, (name, amount) in enumerate(
        [
            ("Restaurante Demo Aurora", 12590),
            ("Hotel Demo das Palmeiras", 38000),
            ("Transporte Demo Central", 7890),
        ],
        1,
    ):
        receipt = dict(
            amount_minor=amount,
            currency="BRL",
            transaction_date=f"2026-10-{28 + i:02}",
            merchant_name=name,
            merchant_tax_id=f"{i}{i}.{str(i) * 3}.{str(i) * 3}/{str(i) * 4}-{i}{i}",
            receipt_identifier=f"DEMO-{i:03}",
            identifier_type="numero_recibo",
        )
        data = pdf_bytes(receipt)
        rid = f"demo-{i:03}"
        originals.append((rid, receipt, data))
        record("reference", f"{rid}.pdf", data, receipt, rid, f"Original {i}")

    for rid, receipt, data in originals:
        record(
            "queries",
            f"{rid}-copia.pdf",
            data,
            receipt,
            rid,
            f"{rid}: cópia idêntica",
            rid,
            "exact_copy",
            True,
            "possible_duplicate",
        )
        img = render(data)
        variants = [
            ("imagem", img, "PNG", "pdf_to_image"),
            ("rotacionado", img.rotate(2, expand=True, fillcolor="white"), "JPEG", "rotation_compression"),
        ]
        noise = img.resize((624, 816)).copy()
        draw = ImageDraw.Draw(noise)
        for _ in range(1800):
            x, y = rng.randrange(noise.width), rng.randrange(noise.height)
            draw.point((x, y), fill=(rng.randrange(180, 255),) * 3)
        variants.append(("ruido", noise, "JPEG", "resize_noise_compression"))
        for suffix, image, fmt, transformation in variants:
            stream = io.BytesIO()
            image.save(stream, format=fmt, **({"quality": 65} if fmt == "JPEG" else {}))
            ext = "png" if fmt == "PNG" else "jpg"
            record(
                "queries",
                f"{rid}-{suffix}.{ext}",
                stream.getvalue(),
                receipt,
                rid,
                f"{rid}: {suffix}",
                rid,
                transformation,
                True,
                "possible_duplicate",
            )

    rid, receipt, _ = originals[0]
    changed = {**receipt, "receipt_identifier": "DEMO-OUTRO"}
    record(
        "queries",
        "distinto-identificador.pdf",
        pdf_bytes(changed),
        changed,
        "negative-id",
        "Outro recibo: mesmo valor/data/local, identificador diferente",
        transformation="different_receipt",
        expected="inconclusive",
    )
    changed = {**receipt, "receipt_identifier": "DEMO-OUTRA-DATA", "transaction_date": "2026-09-05"}
    record(
        "queries",
        "distinto-data.pdf",
        pdf_bytes(changed),
        changed,
        "negative-date",
        "Outro recibo: data e identificador diferentes",
        transformation="different_receipt",
    )
    missing = {**receipt, "amount_minor": None, "receipt_identifier": None, "identifier_type": None}
    record(
        "queries",
        "campos-insuficientes.pdf",
        pdf_bytes(missing),
        missing,
        rid,
        "Recibo com valor e identificador ausentes",
        rid,
        "missing_fields",
        True,
        "inconclusive",
    )
    new = dict(
        amount_minor=9500,
        currency="BRL",
        transaction_date="2026-08-02",
        merchant_name="Pousada Demo Horizonte",
        merchant_tax_id="99.999.999/9999-99",
        receipt_identifier="NOVO-001",
        identifier_type="numero_recibo",
    )
    record("queries", "recibo-novo.pdf", pdf_bytes(new), new, "new-001", "Recibo novo: sem original na base")
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "fixtures")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    manifest = generate(args.output, args.seed)
    print(
        f"Gerados {len(manifest['references'])} originais e {len(manifest['queries'])} consultas em {args.output}."
    )


if __name__ == "__main__":
    main()
