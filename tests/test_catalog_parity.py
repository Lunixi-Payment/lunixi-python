"""Every required operation of the shared SDK catalog exists on the Python client.

Reads ``contracts/products/{payments,fraud,payment-links,reference,wallet,
bank-connect,sanction,insurance,subscriptions,kyc,identity,marketplace}.json`` at
the repository root (two levels above this package) and the Python names in
``contracts/sdk-names.json``. An operation ``accessor.sub.method`` is reached as
``client.accessor().sub.method`` in snake case.

For the table-driven products the wire groups are compared too: each route
table (``kind: routes``) field by field — method, path, signing (``stepUp``),
``Idempotency-Key`` rule, the body flags (``free``, ``optionalBody``,
``anyQuery``), body / query field lists — and every list, pattern and value set
the Node SDK exports. The checkout of this package on its own carries no
``contracts/`` folder, so the test is skipped there.
"""

from __future__ import annotations

import inspect
import json
import pathlib
import re
from typing import Any, Dict, List, Optional, Tuple

import pytest

from lunixi import (
    bank_connect,
    identity,
    insurance,
    kyc,
    marketplace,
    sanction,
    subscriptions,
    wallet,
)
from lunixi.client import LunixiClient

from .conftest import make_client
from .support.recording_transport import RecordingTransport

CONTRACTS = pathlib.Path(__file__).resolve().parents[2] / "contracts"
PRODUCTS = (
    "payments",
    "fraud",
    "payment-links",
    "reference",
    "wallet",
    "bank-connect",
    "sanction",
    "insurance",
    "subscriptions",
    "kyc",
    "identity",
    "marketplace",
)
SDK = "python"

#: Product → the Python package holding its route tables, lists and value sets.
WIRE_MODULES = {
    "wallet": wallet,
    "bank-connect": bank_connect,
    "sanction": sanction,
    "insurance": insurance,
    "subscriptions": subscriptions,
    "kyc": kyc,
    "identity": identity,
    "marketplace": marketplace,
}
#: Keys a route of a table may carry; the rest of a route is not compared.
ROUTE_FLAGS = (
    "method",
    "path",
    "stepUp",
    "idempotencyKey",
    "screening",
    "binary",
    "free",
    "optionalBody",
    "anyQuery",
)
ROUTE_LISTS = ("required", "optional", "query", "anyOf")

pytestmark = pytest.mark.skipif(
    not (CONTRACTS / "products").is_dir(), reason="the shared catalog is not in this checkout"
)


def snake(name: str) -> str:
    # Same rule as tools/contracts/parity-check.mjs: quoteW2W -> quote_w2w, quoteW2Iban -> quote_w2_iban.
    name = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    return re.sub(r"([A-Z0-9])([A-Z][a-z])", r"\1_\2", name).lower()


def sdk_names() -> Dict[str, Optional[str]]:
    path = CONTRACTS / "sdk-names.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get(SDK, {})


def required_operations() -> List[Tuple[str, str]]:
    if not (CONTRACTS / "products").is_dir():
        return []
    operations = []
    for product in PRODUCTS:
        path = CONTRACTS / "products" / f"{product}.json"
        if not path.is_file():
            continue
        catalog = json.loads(path.read_text(encoding="utf-8"))
        for operation, meta in sorted(catalog["operations"].items()):
            if meta.get("status") == "required":
                operations.append((product, operation))
    return operations


def resolve(client: LunixiClient, accessors: List[str]) -> Any:
    """Walks ``client.payments()`` / ``.fraud().events``: a method is called, an attribute read."""
    target: Any = client
    for accessor in accessors:
        member = getattr(target, snake(accessor), None)
        assert member is not None, f"accessor {snake(accessor)} is missing"
        target = member() if inspect.ismethod(member) else member
    return target


@pytest.fixture(scope="module")
def client(test_key_pair) -> LunixiClient:
    private_key, _ = test_key_pair
    return make_client(RecordingTransport(), private_key)


@pytest.mark.parametrize(
    "product,operation", required_operations(), ids=[op for _, op in required_operations()]
)
def test_required_operation_exists(client, product, operation):
    names = sdk_names()
    if operation in names and names[operation] is None:
        pytest.skip(f"{operation} is not offered in the Python SDK on purpose")
    parts = operation.split(".")
    target = resolve(client, parts[:-1])
    method = names.get(operation) or snake(parts[-1])
    assert callable(getattr(target, method, None)), f"{product}: {operation} -> {method}"


def test_every_python_name_points_to_a_catalog_operation():
    known = {operation for _, operation in required_operations()}
    accessors = (
        "payments",
        "fraud",
        "paymentLinks",
        "reference",
        "wallet",
        "bankConnect",
        "sanction",
        "insurance",
        "subscriptions",
        "kyc",
        "identity",
        "marketplace",
    )
    for operation in sdk_names():
        product = operation.split(".", 1)[0]
        if product in accessors:
            assert operation in known, operation


def test_the_catalog_was_read():
    assert len(required_operations()) > 0


def catalog_groups(product: str) -> Dict[str, Any]:
    path = CONTRACTS / "products" / f"{product}.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))["groups"]


def node_groups(kind: str) -> List[Tuple[str, str, Any]]:
    """``(product, group, values)`` of every group the Node SDK exports, of one kind."""
    groups = []
    for product in WIRE_MODULES:
        for name, group in sorted(catalog_groups(product).items()):
            if "node" not in group.get("sources", ()):
                continue
            values = group["values"]
            is_pattern = isinstance(values, dict) and "$pattern" in values
            group_kind = "pattern" if is_pattern else group["kind"]
            if group_kind == kind:
                groups.append((product, name, values))
    return groups


def python_value(product: str, name: str) -> Any:
    """``X`` → the module's ``X``; ``X.y.z`` → ``X["y.z"]`` (a mapping of lists)."""
    module = WIRE_MODULES[product]
    head, _, member = name.partition(".")
    value = getattr(module, head, None)
    assert value is not None, f"{product}: {head} is missing"
    if member:
        assert member in value, f"{product}: {name} is missing"
        value = value[member]
    return value


@pytest.mark.parametrize(
    "product,group,routes",
    node_groups("routes"),
    ids=[f"{product}:{group}" for product, group, _ in node_groups("routes")],
)
def test_route_table_matches_the_catalog(product, group, routes):
    table = python_value(product, group)
    assert sorted(table) == sorted(routes), f"{group}: route names differ"
    for name, route in routes.items():
        mine = table[name]
        assert sorted(mine) == sorted(route), f"{group}.{name}: keys differ"
        for key in ROUTE_FLAGS:
            assert mine.get(key) == route.get(key), f"{group}.{name}.{key}"
        for key in ROUTE_LISTS:
            assert list(mine.get(key, ())) == list(route.get(key, [])), f"{group}.{name}.{key}"


@pytest.mark.parametrize(
    "product,group,values",
    node_groups("list"),
    ids=[f"{product}:{group}" for product, group, _ in node_groups("list")],
)
def test_field_list_matches_the_catalog(product, group, values):
    assert list(python_value(product, group)) == values


@pytest.mark.parametrize(
    "product,group,values",
    node_groups("pattern"),
    ids=[f"{product}:{group}" for product, group, _ in node_groups("pattern")],
)
def test_pattern_matches_the_catalog(product, group, values):
    assert python_value(product, group) == values["$pattern"]


@pytest.mark.parametrize(
    "product,group,values",
    node_groups("enum"),
    ids=[f"{product}:{group}" for product, group, _ in node_groups("enum")],
)
def test_value_set_matches_the_catalog(product, group, values):
    value_set = python_value(product, group)
    for constant, wire in values.items():
        assert getattr(value_set, constant, None) == wire, f"{group}.{constant}"


def test_the_route_tables_were_read():
    assert {group for _, group, _ in node_groups("routes")} == {
        "WALLET_ROUTES",
        "BANK_TRANSFER_ROUTES",
        "SANCTION_ROUTES",
        "SUBSCRIPTION_ROUTES",
        "KYC_ROUTES",
        "IDENTITY_ROUTES",
        "MARKETPLACE_ROUTES",
    }


def test_the_wave_five_products_were_read():
    products = {product for product, _ in required_operations()}
    assert {"subscriptions", "kyc", "identity", "marketplace"} <= products
