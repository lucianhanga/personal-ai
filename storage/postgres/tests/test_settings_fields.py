"""The settings store must persist every TenantSettings field -- no DB required.

Twice now a field was added to the TenantSettings contract and the UI but left out of
``_FIELDS``, so upsert never wrote it and get never read it and the value silently reverted on
reload (``default_reasoning``, then ``agent_verifier_check``). This guard fails at the moment a
new contract field is added without a matching column in the store.
"""

from __future__ import annotations

from personalai_contracts.schemas import TenantSettings
from personalai_storage_postgres.settings_store import _FIELDS


def test_store_persists_every_contract_field() -> None:
    assert set(_FIELDS) == set(TenantSettings.model_fields)


def test_field_order_matches_the_contract() -> None:
    # _COLS is built from _FIELDS and shared by SELECT / INSERT / RETURNING; keeping the order
    # aligned with the contract keeps the two readable side by side.
    contract_order = [f for f in TenantSettings.model_fields if f in set(_FIELDS)]
    assert list(_FIELDS) == contract_order
