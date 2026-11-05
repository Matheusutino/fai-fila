import pytest

from app.contracts import Receipt
from app.rules import compare, evaluate


@pytest.mark.parametrize(
    ("changes", "expected", "rule"),
    [
        ({}, "possible_duplicate", "identifier_and_issuer"),
        ({"receipt_identifier": None}, "possible_duplicate", "amount_date_merchant"),
        ({"receipt_identifier": "DEMO-OUTRO"}, "inconclusive", "conflicting_fields"),
        ({"amount_minor": 12000}, "inconclusive", "conflicting_fields"),
        ({"transaction_date": "2026-09-01", "receipt_identifier": "OUTRO"}, "distinct", "different_fields"),
        ({"merchant_tax_id": "22.222.222/2222-22"}, "inconclusive", "conflicting_fields"),
        ({"amount_minor": None, "receipt_identifier": None}, "inconclusive", "insufficient_fields"),
        ({"ambiguities": ["Data ambígua"]}, "inconclusive", "ambiguous_extraction"),
    ],
)
def test_comparison_policy(receipt, changes, expected, rule):
    candidate = Receipt.model_validate({**receipt.model_dump(), **changes})
    result = compare(receipt, candidate)
    assert result["decision"] == expected
    assert result["rule"] == rule


def test_tax_conflict_not_hidden_by_same_name(receipt):
    candidate = receipt.model_copy(update={"merchant_tax_id": "22.222.222/2222-22"})
    assert "merchant" in compare(receipt, candidate)["conflicting_fields"]


def test_currency_mismatch_is_not_amount_match(receipt):
    candidate = receipt.model_copy(update={"currency": "USD"})
    assert "amount" in compare(receipt, candidate)["conflicting_fields"]


def test_empty_index_and_insufficient_extraction_differ(receipt):
    assert evaluate(receipt, [])["decision"] == "no_duplicate_found"
    assert evaluate(Receipt(), [])["decision"] == "inconclusive"


def test_generic_identifier_without_issuer_not_enough():
    a = Receipt(receipt_identifier="001", identifier_type="numero_recibo")
    assert compare(a, a)["decision"] == "inconclusive"


def test_normalized_names_when_tax_id_missing(receipt):
    a = receipt.model_copy(update={"merchant_tax_id": None})
    b = a.model_copy(update={"merchant_name": "RESTAURANTE DEMO, AURORA!"})
    assert compare(a, b)["decision"] == "possible_duplicate"
