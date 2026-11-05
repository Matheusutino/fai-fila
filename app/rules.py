"""Política v1: suspeita explicável, sem parecer livre da LLM."""

import re
import unicodedata

from app.contracts import Receipt

RULE_VERSION = "v1"


def normalized(value: str | None) -> str:
    plain = unicodedata.normalize("NFKD", value or "")
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in plain if not unicodedata.combining(c)).lower())


def merchant(receipt: Receipt) -> str:
    return normalized(receipt.merchant_name)


def enough(receipt: Receipt) -> bool:
    return bool(
        receipt.amount_minor is not None
        and receipt.currency
        and receipt.transaction_date
        and (normalized(receipt.merchant_tax_id) or merchant(receipt))
        and not receipt.ambiguities
    )


def compare(query: Receipt, candidate: Receipt) -> dict:
    matched, conflicts, missing = [], [], []
    pairs = {
        "amount": ((query.amount_minor, query.currency), (candidate.amount_minor, candidate.currency)),
        "transaction_date": (query.transaction_date, candidate.transaction_date),
    }
    for field, (a, b) in pairs.items():
        absent = any(x is None for x in (*a, *b)) if field == "amount" else a is None or b is None
        (missing if absent else matched if a == b else conflicts).append(field)
    tax_a, tax_b = normalized(query.merchant_tax_id), normalized(candidate.merchant_tax_id)
    name_a, name_b = merchant(query), merchant(candidate)
    if tax_a and tax_b:
        (matched if tax_a == tax_b else conflicts).append("merchant")
    elif name_a and name_b:
        (matched if name_a == name_b else conflicts).append("merchant")
    else:
        missing.append("merchant")
    id_a, id_b = normalized(query.receipt_identifier), normalized(candidate.receipt_identifier)
    type_a, type_b = normalized(query.identifier_type), normalized(candidate.identifier_type)
    comparable_id = id_a and id_b and type_a and type_a == type_b
    if comparable_id:
        (matched if id_a == id_b else conflicts).append("receipt_identifier")
    else:
        missing.append("receipt_identifier")
    composite = all(k in matched for k in ("amount", "transaction_date", "merchant"))
    identifier_match = comparable_id and id_a == id_b
    ambiguous = bool(query.ambiguities or candidate.ambiguities)
    if ambiguous:
        decision, rule = "inconclusive", "ambiguous_extraction"
    elif identifier_match and conflicts or composite and "receipt_identifier" in conflicts:
        decision, rule = "inconclusive", "conflicting_fields"
    elif identifier_match and "merchant" in matched and not conflicts:
        decision, rule = "possible_duplicate", "identifier_and_issuer"
    elif composite:
        decision, rule = "possible_duplicate", "amount_date_merchant"
    elif enough(query) and enough(candidate) and conflicts:
        decision, rule = "distinct", "different_fields"
    else:
        decision, rule = "inconclusive", "insufficient_fields"
    reasons = {
        "ambiguous_extraction": "A extração contém ambiguidades que exigem revisão.",
        "conflicting_fields": "Há coincidências fortes e campos conflitantes.",
        "identifier_and_issuer": "Identificador e emissor coincidem, sem divergências disponíveis.",
        "amount_date_merchant": "Valor, moeda, data e estabelecimento coincidem.",
        "different_fields": "Os campos disponíveis diferem e não satisfazem a regra de suspeita.",
        "insufficient_fields": "Faltam campos para uma comparação suficiente.",
    }
    return dict(
        decision=decision,
        rule=rule,
        reason=reasons[rule],
        matched_fields=matched,
        conflicting_fields=conflicts,
        missing_fields=missing,
    )


def evaluate(query: Receipt, candidates: list[dict]) -> dict:
    matches = []
    for item in candidates:
        candidate = Receipt.model_validate(item["receipt"])
        matches.append({**item, **compare(query, candidate)})
    if any(m["decision"] == "possible_duplicate" for m in matches):
        decision = "possible_duplicate"
    elif not enough(query) or any(m["decision"] == "inconclusive" for m in matches):
        decision = "inconclusive"
    else:
        decision = "no_duplicate_found"
    return dict(
        decision=decision,
        rule_version=RULE_VERSION,
        receipt=query.model_dump(mode="json"),
        matches=matches,
        limitation="A análise considera apenas os candidatos recuperados no índice de recibos aceitos.",
    )
