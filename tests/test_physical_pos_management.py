"""Physical POS management: stores, registers, terminals, devices, catalog, overview.

Contract source: nest-payment-gateway apps/api-gateway/src/physical-pos/
{stores,terminals,devices,settlements,catalog,overview}/*-api.controller.ts, their DTOs,
mappers and services. Ids and values below are synthetic.
"""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlsplit

import pytest

from lunixi.errors import ConfigurationError, PhysicalPosCardDataRejectedError, ValidationError
from lunixi.physical_pos import PhysicalPosWriteResult

from .support.recording_transport import envelope, json_response

STORE_ID = "11111111-1111-4111-8111-111111111111"
REGISTER_ID = "22222222-2222-4222-8222-222222222222"
TERMINAL_ID = "33333333-3333-4333-8333-333333333333"
ACQUIRER_ID = "44444444-4444-4444-8444-444444444444"
DEVICE_ID = "55555555-5555-4555-8555-555555555555"
PROVIDER_ROW_ID = "66666666-6666-4666-8666-666666666666"
VENDOR_ACCOUNT_ID = "77777777-7777-4777-8777-777777777777"
KEY = "mgmt-test-key-0001"
UUID_V4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
BASE = "/api/v1/physical-pos"

STORE = {
    "id": STORE_ID,
    "code": "IST-01",
    "name": "Istanbul 1",
    "city": None,
    "district": None,
    "addressLine": None,
    "timezone": "Europe/Istanbul",
    "storeStatus": "ACTIVE",
    "externalRef": None,
    "rowVersion": 1,
    "createdAt": "2026-10-30T09:00:00.000Z",
    "updatedAt": "2026-10-30T09:00:00.000Z",
}


def query_of(request):
    return {k: v[0] for k, v in parse_qs(urlsplit(request.url).query).items()}


def answer(data, status=200, **extra):
    return json_response(envelope(data, statusCode=status, **extra), status_code=status)


class TestStores:
    def test_create_store_is_keyed_and_201(self, client_factory):
        transport, client = client_factory(answer({"store": STORE, "replayed": False}, 201))
        result = client.physical_pos_management().create_store(
            code="IST-01", name="Istanbul 1", address_line="Street 1", idempotency_key=KEY
        )
        assert transport.last.path == f"{BASE}/stores"
        assert transport.last.header("Idempotency-Key") == KEY
        assert transport.last.header("X-Signature")
        assert json.loads(transport.last.body) == {
            "code": "IST-01",
            "name": "Istanbul 1",
            "addressLine": "Street 1",
        }
        assert isinstance(result, PhysicalPosWriteResult)
        assert result.status_code == 201 and result.replayed is False
        assert result["store"]["id"] == STORE_ID

    def test_a_replayed_create_is_200(self, client_factory):
        _, client = client_factory(answer({"store": STORE, "replayed": True}, 200))
        result = client.physical_pos_management().create_store({"code": "IST-01", "name": "x"})
        assert result.replayed is True and result.status_code == 200
        assert UUID_V4.fullmatch(result.idempotency_key)

    def test_update_store_sends_null_to_clear(self, client_factory):
        transport, client = client_factory(answer({"store": STORE}))
        store = client.physical_pos_management().update_store(
            STORE_ID, row_version=3, city=None, name="New"
        )
        assert transport.last.method == "PATCH"
        assert transport.last.path == f"{BASE}/stores/{STORE_ID}"
        assert json.loads(transport.last.body) == {"rowVersion": 3, "name": "New", "city": None}
        assert transport.last.header("Idempotency-Key") is None
        assert store["id"] == STORE_ID

    @pytest.mark.parametrize("row_version", ["3", 0, 2147483648, None, True])
    def test_row_version_must_be_a_json_integer(self, client_factory, row_version):
        transport, client = client_factory()
        with pytest.raises(ConfigurationError):
            client.physical_pos_management().archive_store(
                STORE_ID, row_version=row_version, reason_code="STORE_CLOSED"
            )
        assert transport.requests == []

    def test_archive_restore_and_detail(self, client_factory):
        transport, client = client_factory(
            answer({"store": STORE, "archivedRegisterCount": 2}),
            answer({"store": STORE}),
            answer(
                {
                    "store": STORE,
                    "registerSummary": {"activeCount": 1, "archivedCount": 0},
                    "assignedDeviceCount": 0,
                }
            ),
        )
        mgmt = client.physical_pos_management()
        assert (
            mgmt.archive_store(STORE_ID, {"rowVersion": 1, "reasonCode": "STORE_CLOSED"})[
                "archivedRegisterCount"
            ]
            == 2
        )
        assert transport.last.path == f"{BASE}/stores/{STORE_ID}/archive"
        assert mgmt.restore_store(STORE_ID, row_version=2, reason_code="REOPENED")["id"] == STORE_ID
        assert transport.last.path == f"{BASE}/stores/{STORE_ID}/restore"
        assert mgmt.get_store(STORE_ID)["registerSummary"]["activeCount"] == 1

    def test_list_stores_with_total(self, client_factory):
        info = {"hasMore": False, "nextCursor": None, "totalCount": 1}
        transport, client = client_factory(
            answer({"items": [dict(STORE, registerCount=1)], "pageInfo": info}, pageInfo=info)
        )
        page = client.physical_pos_management().list_stores(
            include_total=True, status="ACTIVE", q="IST"
        )
        assert query_of(transport.last) == {"includeTotal": "true", "status": "ACTIVE", "q": "IST"}
        assert page.total_count == 1

    def test_audit_lists_take_no_total(self, client_factory):
        transport, client = client_factory()
        with pytest.raises(ConfigurationError):
            client.physical_pos_management().list_store_audit(STORE_ID, include_total=True)
        assert transport.requests == []


class TestRegisters:
    def test_register_routes(self, client_factory):
        register = {
            "id": REGISTER_ID,
            "storeId": STORE_ID,
            "code": "K1",
            "name": "Till 1",
            "registerStatus": "ACTIVE",
            "rowVersion": 1,
        }
        info = {"hasMore": False, "nextCursor": None, "totalCount": None}
        transport, client = client_factory(
            answer({"register": register, "replayed": False}, 201),
            answer({"register": register}),
            answer({"register": register}),
            answer({"items": [register], "pageInfo": info}, pageInfo=info),
        )
        mgmt = client.physical_pos_management()
        created = mgmt.create_register(STORE_ID, code="K1", name="Till 1")
        assert transport.last.path == f"{BASE}/stores/{STORE_ID}/registers"
        assert created.status_code == 201
        assert UUID_V4.fullmatch(transport.last.header("Idempotency-Key"))
        mgmt.update_register(REGISTER_ID, row_version=1, name="Till A")
        assert (transport.last.method, transport.last.path) == (
            "PATCH",
            f"{BASE}/registers/{REGISTER_ID}",
        )
        mgmt.archive_register(REGISTER_ID, row_version=2, reason_code="REGISTER_REMOVED")
        assert transport.last.path == f"{BASE}/registers/{REGISTER_ID}/archive"
        assert mgmt.list_registers(STORE_ID, status="ACTIVE").items[0]["id"] == REGISTER_ID


class TestTerminals:
    def test_terminal_routes(self, client_factory):
        terminal = {"id": TERMINAL_ID, "terminalCode": "T1", "rowVersion": 1}
        acquirer = {
            "id": ACQUIRER_ID,
            "terminalId": TERMINAL_ID,
            "currencies": ["TRY"],
            "rowVersion": 1,
        }
        transport, client = client_factory(
            answer({"terminal": terminal, "replayed": False}, 201),
            answer(
                {
                    "terminal": terminal,
                    "acquirers": {"items": [acquirer], "pageInfo": {"hasMore": False}},
                }
            ),
            answer({"acquirer": acquirer, "replayed": False}, 201),
            answer({"acquirer": acquirer}),
            answer({"terminal": terminal, "link": {"id": "l1", "deviceId": DEVICE_ID}}),
            answer({"terminal": terminal, "link": None}),
            answer({"terminal": terminal}),
        )
        mgmt = client.physical_pos_management()
        mgmt.create_terminal(code="T1", display_name="Front desk", vendor_code="PAVO")
        assert json.loads(transport.last.body) == {
            "code": "T1",
            "displayName": "Front desk",
            "vendorCode": "PAVO",
        }
        assert mgmt.get_terminal(TERMINAL_ID)["acquirers"]["items"][0]["id"] == ACQUIRER_ID
        added = mgmt.add_terminal_acquirer(
            TERMINAL_ID,
            vendor_acquirer_ref="62",
            merchant_number="000123",
            terminal_number="PT000001",
            currencies=["TRY"],
            idempotency_key=KEY,
        )
        assert transport.last.path == f"{BASE}/terminals/{TERMINAL_ID}/acquirers"
        assert added["acquirer"]["id"] == ACQUIRER_ID
        mgmt.update_terminal_acquirer(ACQUIRER_ID, row_version=1, label=None, status="DISABLED")
        assert transport.last.path == f"{BASE}/terminal-acquirers/{ACQUIRER_ID}"
        assert json.loads(transport.last.body) == {
            "rowVersion": 1,
            "label": None,
            "status": "DISABLED",
        }
        linked = mgmt.change_terminal_device(
            TERMINAL_ID, row_version=1, device_id=DEVICE_ID, reason_code="INITIAL_SETUP"
        )
        assert transport.last.path == f"{BASE}/terminals/{TERMINAL_ID}/device-link"
        assert transport.last.header("Idempotency-Key") is None
        assert linked["link"]["deviceId"] == DEVICE_ID
        closed = mgmt.close_terminal_device_link(
            TERMINAL_ID, row_version=2, reason_code="DEVICE_FAULT"
        )
        assert transport.last.path == f"{BASE}/terminals/{TERMINAL_ID}/device-link/close"
        assert transport.last.header("Idempotency-Key") == closed.idempotency_key
        assert closed.status_code == 200 and closed["link"] is None
        mgmt.close_terminal(TERMINAL_ID, row_version=3, reason_code="OTHER")
        assert transport.last.path == f"{BASE}/terminals/{TERMINAL_ID}/close"

    def test_currencies_must_be_a_list_of_strings(self, client_factory):
        transport, client = client_factory()
        with pytest.raises(ConfigurationError):
            client.physical_pos_management().add_terminal_acquirer(
                TERMINAL_ID,
                vendor_acquirer_ref="62",
                merchant_number="1",
                terminal_number="2",
                currencies="TRY",
            )
        assert transport.requests == []


class TestDevices:
    def test_device_routes(self, client_factory):
        device = {"id": DEVICE_ID, "serialNumber": "PAV00012345", "rowVersion": 1}
        info = {"hasMore": False, "nextCursor": None, "totalCount": None}
        transport, client = client_factory(
            answer({"device": device, "replayed": False}, 201),
            answer({"device": device}),
            answer({"device": device, "assignment": {"id": "a1"}, "previousAssignmentId": None}),
            answer({"device": device, "closedAssignment": {"id": "a1"}, "replayed": False}),
            answer({"device": device}),
            answer({"device": device, "replayed": True}),
            answer({"items": [], "pageInfo": info}, pageInfo=info),
        )
        mgmt = client.physical_pos_management()
        created = mgmt.create_device(
            vendor_code="PAVO",
            device_model_id="m1",
            serial_number="PAV00012345",
            integration_channel="APP2APP",
            store_id=STORE_ID,
        )
        assert created.status_code == 201 and created["device"]["id"] == DEVICE_ID
        assert mgmt.update_device(DEVICE_ID, row_version=1, display_name=None)["id"] == DEVICE_ID
        assert json.loads(transport.last.body) == {"rowVersion": 1, "displayName": None}
        assigned = mgmt.assign_device(
            DEVICE_ID,
            row_version=2,
            store_id=STORE_ID,
            register_id=None,
            reason_code="INITIAL_SETUP",
        )
        assert json.loads(transport.last.body) == {
            "rowVersion": 2,
            "storeId": STORE_ID,
            "registerId": None,
            "reasonCode": "INITIAL_SETUP",
        }
        assert assigned["assignment"]["id"] == "a1"
        stored = mgmt.close_device_assignment(
            DEVICE_ID, row_version=3, reason_code="MOVED_TO_STORAGE", idempotency_key=KEY
        )
        assert transport.last.path == f"{BASE}/devices/{DEVICE_ID}/assignment/close"
        assert stored["closedAssignment"]["id"] == "a1"
        mgmt.change_device_lifecycle(
            DEVICE_ID, row_version=4, target="SUSPENDED", reason_code="DEVICE_LOST"
        )
        assert transport.last.path == f"{BASE}/devices/{DEVICE_ID}/lifecycle"
        retired = mgmt.retire_device(DEVICE_ID, row_version=5, reason_code="END_OF_LIFE")
        assert retired.replayed is True
        assert transport.last.path == f"{BASE}/devices/{DEVICE_ID}/retire"
        mgmt.list_devices(lifecycle_status="ACTIVE", include_total=False, q="PAV")
        assert query_of(transport.last) == {
            "lifecycleStatus": "ACTIVE",
            "includeTotal": "false",
            "q": "PAV",
        }

    def test_create_device_requires_the_channel(self, client_factory):
        transport, client = client_factory()
        with pytest.raises(ConfigurationError):
            client.physical_pos_management().create_device(
                vendor_code="PAVO", device_model_id="m1", serial_number="S1"
            )
        assert transport.requests == []

    def test_card_data_is_refused_on_management_bodies(self, client_factory):
        transport, client = client_factory()
        with pytest.raises(PhysicalPosCardDataRejectedError) as caught:
            client.physical_pos_management().update_device(
                DEVICE_ID, row_version=1, card_number="x"
            )
        assert caught.value.field == "card_number"
        assert transport.requests == []

    def test_activation_codes_are_not_issued_with_an_api_key(self, client_factory):
        _, client = client_factory()
        mgmt = client.physical_pos_management()
        assert not hasattr(mgmt, "issue_activation_code")
        assert callable(mgmt.revoke_device_key)


DEVICE_KEY_ID = "pdk_AAAAAAAAAAAAAAAAAAAAAAAA"
DEVICE_KEY = {
    "keyId": DEVICE_KEY_ID,
    "algorithm": "ED25519",
    "keyStatus": "ACTIVE",
    "enrolledVia": "PAIRING",
    "fingerprint": "ABCD-EF12",
    "lineageRootKeyId": DEVICE_KEY_ID,
    "rotatedFromKeyId": None,
    "activatedAt": "2026-11-01T09:00:00.000Z",
    "supersededAt": None,
    "revokedAt": None,
    "revokeReason": None,
    "rowVersion": 1,
}


class TestDeviceIdentity:
    def test_device_identity_routes(self, client_factory):
        info = {"hasMore": True, "nextCursor": "k1", "totalCount": None}
        revoked = dict(DEVICE_KEY, keyStatus="REVOKED", revokeReason="DEVICE_LOST", rowVersion=2)
        transport, client = client_factory(
            answer({"items": [DEVICE_KEY], "pageInfo": info}, pageInfo=info),
            answer({"key": revoked, "lifecycleStatus": "SUSPENDED", "replayed": False}),
            answer({"key": revoked, "lifecycleStatus": "SUSPENDED", "replayed": True}),
            answer(
                {
                    "deviceId": DEVICE_ID,
                    "revokedAt": "2026-11-02T09:00:00.000Z",
                    "revokeReason": "MERCHANT_REVOKED",
                }
            ),
        )
        mgmt = client.physical_pos_management()
        page = mgmt.list_device_keys(DEVICE_ID, limit=10)
        assert transport.last.path == f"{BASE}/devices/{DEVICE_ID}/keys?limit=10"
        assert query_of(transport.last) == {"limit": "10"}
        assert page.items[0]["keyId"] == DEVICE_KEY_ID
        assert page.has_more is True and page.next_cursor == "k1"

        result = mgmt.revoke_device_key(
            DEVICE_ID, DEVICE_KEY_ID, row_version=1, reason_code="DEVICE_LOST"
        )
        assert transport.last.method == "POST"
        assert transport.last.path == f"{BASE}/devices/{DEVICE_ID}/keys/{DEVICE_KEY_ID}/revoke"
        assert json.loads(transport.last.body) == {"rowVersion": 1, "reasonCode": "DEVICE_LOST"}
        assert transport.last.header("Idempotency-Key") is None
        assert result["key"]["keyStatus"] == "REVOKED"
        assert result["lifecycleStatus"] == "SUSPENDED"
        assert result["replayed"] is False

        reverted = mgmt.revert_device_enrollment(
            DEVICE_ID, DEVICE_KEY_ID, {"reasonCode": "NOT_MY_DEVICE"}
        )
        assert (
            transport.last.path
            == f"{BASE}/devices/{DEVICE_ID}/keys/{DEVICE_KEY_ID}/revert-enrollment"
        )
        assert json.loads(transport.last.body) == {"reasonCode": "NOT_MY_DEVICE"}
        assert transport.last.header("Idempotency-Key") is None
        assert reverted["replayed"] is True

        code = mgmt.revoke_activation_code(DEVICE_ID, reason_code="MERCHANT_REVOKED")
        assert transport.last.path == f"{BASE}/devices/{DEVICE_ID}/activation-code/revoke"
        assert json.loads(transport.last.body) == {"reasonCode": "MERCHANT_REVOKED"}
        assert transport.last.header("Idempotency-Key") is None
        assert code["revokeReason"] == "MERCHANT_REVOKED"

    def test_iterate_device_keys_follows_the_cursor(self, client_factory):
        first = {"hasMore": True, "nextCursor": "k1", "totalCount": None}
        last = {"hasMore": False, "nextCursor": None, "totalCount": None}
        other = dict(DEVICE_KEY, keyId="pdk_BBBBBBBBBBBBBBBBBBBBBBBB")
        transport, client = client_factory(
            answer({"items": [DEVICE_KEY], "pageInfo": first}, pageInfo=first),
            answer({"items": [other], "pageInfo": last}, pageInfo=last),
        )
        keys = [k["keyId"] for k in client.physical_pos_management().iterate_device_keys(DEVICE_ID)]
        assert keys == [DEVICE_KEY_ID, "pdk_BBBBBBBBBBBBBBBBBBBBBBBB"]
        assert query_of(transport.requests[-1]) == {"cursor": "k1"}

    @pytest.mark.parametrize(
        "call",
        [
            lambda m: m.revoke_device_key(DEVICE_ID, "", row_version=1, reason_code="OTHER"),
            lambda m: m.revoke_device_key(
                DEVICE_ID, DEVICE_KEY_ID, row_version="1", reason_code="OTHER"
            ),
            lambda m: m.revoke_device_key(DEVICE_ID, DEVICE_KEY_ID, reason_code="OTHER"),
            lambda m: m.revert_device_enrollment(
                DEVICE_ID, DEVICE_KEY_ID, reason_code="OTHER", row_version=1
            ),
            lambda m: m.revoke_activation_code(DEVICE_ID),
            lambda m: m.list_device_keys(DEVICE_ID, include_total=True),
        ],
    )
    def test_malformed_identity_requests_are_refused_before_sending(self, client_factory, call):
        transport, client = client_factory()
        with pytest.raises(ConfigurationError):
            call(client.physical_pos_management())
        assert transport.requests == []


class TestCatalogAndOverview:
    def test_catalog_returns_bare_arrays(self, client_factory):
        transport, client = client_factory(
            answer(
                [{"code": "PAVO", "displayName": "Pavo", "status": "ACTIVE", "fallbackImage": None}]
            ),
            answer([{"id": "m1", "vendorCode": "PAVO"}]),
            answer([{"acquirerCode": "AKBANK", "displayName": "Akbank"}]),
            answer({"overview": {"stores": {"active": 1, "archived": 0}, "transactions": None}}),
        )
        mgmt = client.physical_pos_management()
        assert mgmt.list_vendors()[0]["code"] == "PAVO"
        assert transport.last.path == f"{BASE}/catalog/vendors"
        assert mgmt.list_device_models(vendor_code="PAVO")[0]["id"] == "m1"
        assert transport.last.path == f"{BASE}/catalog/device-models?vendorCode=PAVO"
        assert mgmt.list_acquirers()[0]["acquirerCode"] == "AKBANK"
        assert mgmt.get_overview()["stores"]["active"] == 1
        assert transport.last.path == f"{BASE}/overview"

    def test_a_conflict_keeps_its_class_and_gets_the_key(self, client_factory):
        body = {
            "status": "failure",
            "code": "physical_pos.store.code_taken",
            "statusCode": 409,
            "message": "x",
        }
        _, client = client_factory(json_response(body, status_code=409))
        with pytest.raises(Exception) as caught:
            client.physical_pos_management().create_store(
                code="IST-01", name="x", idempotency_key=KEY
            )
        assert caught.value.code == "physical_pos.store.code_taken"
        assert caught.value.idempotency_key == KEY
        assert not isinstance(caught.value, ValidationError)


PROVIDER = {
    "id": PROVIDER_ROW_ID,
    "terminalId": TERMINAL_ID,
    "environment": "LIVE",
    "providerCode": "METROPOL",
    "vendorAccountId": VENDOR_ACCOUNT_ID,
    "merchantCode": "1000000001",
    "terminalCode": "2000000002",
    "productCode": "3",
    "label": None,
    "providerStatus": "ACTIVE",
    "rowVersion": 1,
    "createdAt": "2026-11-01T09:00:00.000Z",
    "updatedAt": "2026-11-01T09:00:00.000Z",
}


class TestTerminalProviders:
    def test_terminal_provider_routes(self, client_factory):
        info = {"hasMore": False, "nextCursor": None, "totalCount": 1}
        transport, client = client_factory(
            answer({"items": [PROVIDER], "pageInfo": info}, pageInfo=info),
            answer({"provider": PROVIDER, "replayed": False}, 201),
            answer({"provider": PROVIDER, "replayed": True}, 200),
            answer({"provider": dict(PROVIDER, providerStatus="DISABLED", rowVersion=2)}),
        )
        mgmt = client.physical_pos_management()
        page = mgmt.list_terminal_providers(TERMINAL_ID, limit=10, include_total=True)
        assert transport.last.path.startswith(f"{BASE}/terminals/{TERMINAL_ID}/providers?")
        assert query_of(transport.last) == {"limit": "10", "includeTotal": "true"}
        assert page.items[0]["providerCode"] == "METROPOL"

        added = mgmt.add_terminal_provider(
            TERMINAL_ID,
            vendor_account_id=VENDOR_ACCOUNT_ID,
            merchant_code="1000000001",
            terminal_code="2000000002",
            product_code="3",
            label="Meal",
            idempotency_key=KEY,
        )
        assert transport.last.method == "POST"
        assert transport.last.path == f"{BASE}/terminals/{TERMINAL_ID}/providers"
        assert json.loads(transport.last.body) == {
            "vendorAccountId": VENDOR_ACCOUNT_ID,
            "merchantCode": "1000000001",
            "terminalCode": "2000000002",
            "productCode": "3",
            "label": "Meal",
        }
        assert transport.last.header("Idempotency-Key") == KEY
        assert added.status_code == 201 and added["provider"]["id"] == PROVIDER_ROW_ID

        replay = mgmt.add_terminal_provider(
            TERMINAL_ID,
            {
                "vendorAccountId": VENDOR_ACCOUNT_ID,
                "merchantCode": "1000000001",
                "terminalCode": "2000000002",
            },
        )
        assert UUID_V4.fullmatch(transport.last.header("Idempotency-Key"))
        assert replay.replayed is True and replay.status_code == 200

        updated = mgmt.update_terminal_provider(
            PROVIDER_ROW_ID, row_version=1, label=None, status="DISABLED"
        )
        assert transport.last.method == "PATCH"
        assert transport.last.path == f"{BASE}/terminal-providers/{PROVIDER_ROW_ID}"
        assert json.loads(transport.last.body) == {
            "rowVersion": 1,
            "label": None,
            "status": "DISABLED",
        }
        assert transport.last.header("Idempotency-Key") is None
        assert updated["providerStatus"] == "DISABLED"

    def test_iterate_terminal_providers_follows_the_cursor(self, client_factory):
        first = {"hasMore": True, "nextCursor": "p1", "totalCount": None}
        last = {"hasMore": False, "nextCursor": None, "totalCount": None}
        transport, client = client_factory(
            answer({"items": [PROVIDER], "pageInfo": first}, pageInfo=first),
            answer({"items": [dict(PROVIDER, id="p2")], "pageInfo": last}, pageInfo=last),
        )
        mgmt = client.physical_pos_management()
        ids = [row["id"] for row in mgmt.iterate_terminal_providers(TERMINAL_ID)]
        assert ids == [PROVIDER_ROW_ID, "p2"]
        assert query_of(transport.requests[-1]) == {"cursor": "p1"}


POLICY = {
    "scopeType": "ACCOUNT",
    "storeId": None,
    "deviceId": None,
    "active": True,
    "mode": "SCHEDULED",
    "scheduleTime": "23:30",
    "timeZone": "Europe/Istanbul",
    "scheduleDays": [],
    "retryWindowMinutes": 120,
    "retryIntervalMinutes": 15,
    "offlineBehavior": "RETRY_IN_WINDOW",
    "overdueAlertHours": 26,
    "rowVersion": 2,
    "updatedAt": "2026-11-03T09:00:00.000Z",
}


class TestSettlementPolicy:
    def test_policy_routes_for_every_level(self, client_factory):
        effective = {
            "deviceId": DEVICE_ID,
            "sourceScopeType": "STORE",
            "policy": dict(POLICY, scopeType="STORE", storeId=STORE_ID),
            "serverSettlementSupported": True,
            "deviceAutoSupported": False,
            "nextScheduledAt": "2026-11-03T20:30:00.000Z",
            "lastSettlementAt": None,
            "overdue": False,
            "scheduleWarning": None,
        }
        transport, client = client_factory(
            *[answer({"policy": POLICY}) for _ in range(9)],
            answer({"effective": effective}),
        )
        mgmt = client.physical_pos_management()
        scheduled = {
            "mode": "SCHEDULED",
            "scheduleTime": "23:30",
            "timeZone": "Europe/Istanbul",
            "scheduleDays": ["MON", "FRI"],
            "retryWindowMinutes": 120,
            "retryIntervalMinutes": 15,
            "offlineBehavior": "ALERT_IMMEDIATELY",
            "overdueAlertHours": 26,
            "expectedRowVersion": 1,
        }

        assert mgmt.get_account_settlement_policy()["mode"] == "SCHEDULED"
        mgmt.set_account_settlement_policy(scheduled)
        mgmt.clear_account_settlement_policy()
        mgmt.get_store_settlement_policy(STORE_ID)
        mgmt.set_store_settlement_policy(STORE_ID, mode="MANUAL")
        mgmt.clear_store_settlement_policy(STORE_ID, expected_row_version=3)
        mgmt.get_device_settlement_policy(DEVICE_ID)
        mgmt.set_device_settlement_policy(DEVICE_ID, mode="DEVICE_AUTO", overdue_alert_hours=30)
        cleared = mgmt.clear_device_settlement_policy(DEVICE_ID, expected_row_version=4)
        assert cleared["rowVersion"] == 2
        preview = mgmt.get_effective_settlement_policy(DEVICE_ID)
        assert preview["sourceScopeType"] == "STORE"
        assert preview["policy"]["storeId"] == STORE_ID

        calls = transport.requests[1:]
        assert [(call.method, call.path) for call in calls] == [
            ("GET", f"{BASE}/settlement-policy"),
            ("PUT", f"{BASE}/settlement-policy"),
            ("DELETE", f"{BASE}/settlement-policy"),
            ("GET", f"{BASE}/stores/{STORE_ID}/settlement-policy"),
            ("PUT", f"{BASE}/stores/{STORE_ID}/settlement-policy"),
            ("DELETE", f"{BASE}/stores/{STORE_ID}/settlement-policy?expectedRowVersion=3"),
            ("GET", f"{BASE}/devices/{DEVICE_ID}/settlement-policy"),
            ("PUT", f"{BASE}/devices/{DEVICE_ID}/settlement-policy"),
            ("DELETE", f"{BASE}/devices/{DEVICE_ID}/settlement-policy?expectedRowVersion=4"),
            ("GET", f"{BASE}/devices/{DEVICE_ID}/settlement-policy/effective"),
        ]
        assert json.loads(calls[1].body) == scheduled
        assert json.loads(calls[4].body) == {"mode": "MANUAL"}
        assert json.loads(calls[7].body) == {"mode": "DEVICE_AUTO", "overdueAlertHours": 30}
        assert calls[2].body is None
        assert all(call.header("Idempotency-Key") is None for call in calls)

    @pytest.mark.parametrize(
        "call",
        [
            lambda m: m.set_account_settlement_policy({}),
            lambda m: m.set_account_settlement_policy(mode="MANUAL", environment="LIVE"),
            lambda m: m.set_store_settlement_policy(
                STORE_ID, mode="SCHEDULED", retry_window_minutes="120"
            ),
            lambda m: m.set_device_settlement_policy(
                DEVICE_ID, mode="SCHEDULED", schedule_days="MON"
            ),
            lambda m: m.set_device_settlement_policy(
                DEVICE_ID, mode="MANUAL", expected_row_version=0
            ),
            lambda m: m.clear_account_settlement_policy(expected_row_version="2"),
            lambda m: m.clear_store_settlement_policy(STORE_ID, expected_row_version=0),
            lambda m: m.clear_device_settlement_policy("", expected_row_version=1),
            lambda m: m.get_effective_settlement_policy(".."),
            lambda m: m.add_terminal_provider(
                TERMINAL_ID, vendor_account_id=VENDOR_ACCOUNT_ID, merchant_code="1"
            ),
            lambda m: m.add_terminal_provider(
                TERMINAL_ID,
                vendor_account_id=VENDOR_ACCOUNT_ID,
                merchant_code="1",
                terminal_code="2",
                provider_code="METROPOL",
            ),
            lambda m: m.update_terminal_provider(PROVIDER_ROW_ID, label="x"),
            lambda m: m.update_terminal_provider("", row_version=1),
            lambda m: m.list_terminal_providers(TERMINAL_ID, status="ACTIVE"),
        ],
    )
    def test_malformed_requests_are_refused_before_sending(self, client_factory, call):
        transport, client = client_factory()
        with pytest.raises(ConfigurationError):
            call(client.physical_pos_management())
        assert transport.requests == []
