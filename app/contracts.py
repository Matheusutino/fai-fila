from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Receipt(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    amount_minor: int | None = Field(default=None, ge=0, strict=True)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    transaction_date: date | None = None
    merchant_name: str | None = Field(default=None, max_length=300)
    merchant_tax_id: str | None = Field(default=None, max_length=30)
    receipt_identifier: str | None = Field(default=None, max_length=120)
    identifier_type: Literal["numero_recibo", "chave_nfe", "numero_nota", "outro"] | None = None
    evidence: dict[str, str] = Field(default_factory=dict)
    ambiguities: list[str] = Field(default_factory=list)

    @field_validator("evidence", mode="before")
    @classmethod
    def omit_absent_evidence(cls, value):
        # null em evidência de um campo ausente equivale à chave omitida.
        # Campos preenchidos continuam exigindo um trecho literal na integração.
        if isinstance(value, dict):
            return {key: text for key, text in value.items() if text is not None}
        return value


class Approval(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    check_token: str = Field(min_length=20, max_length=100)
    receipt_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    approval_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(default=1, ge=1, strict=True)
    project: str | None = Field(default=None, max_length=100)


Decision = Literal["possible_duplicate", "no_duplicate_found", "inconclusive"]
