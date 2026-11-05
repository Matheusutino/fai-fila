import os
import uuid

import pytest

from app.persistence import Repository


@pytest.fixture
def repo(tmp_path):
    postgres = os.getenv("TEST_DATABASE_URL")
    schema = "test_" + uuid.uuid4().hex
    if postgres:
        from sqlalchemy import create_engine

        admin = create_engine(postgres)
        with admin.begin() as conn:
            conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        separator = "&" if "?" in postgres else "?"
        repository = Repository(postgres + separator + "options=-csearch_path%3D" + schema)
    else:
        repository = Repository("sqlite:///" + str(tmp_path / "tasks.db"))
    repository.initialize()
    yield repository
    repository.engine.dispose()
    if postgres:
        with admin.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


@pytest.fixture
def receipt():
    from app.contracts import Receipt

    return Receipt(
        amount_minor=12590,
        currency="BRL",
        transaction_date="2026-10-29",
        merchant_name="Restaurante Demo Aurora",
        merchant_tax_id="11.111.111/1111-11",
        receipt_identifier="DEMO-001",
        identifier_type="numero_recibo",
    )
