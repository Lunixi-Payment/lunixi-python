"""Physical POS management: overview, catalog, stores, registers, terminals, devices.

Reads need the ``physical_pos:view`` scope, writes ``physical_pos:manage``.
Every call is signed per request. A TEST key reads only.

Updates and state changes take the record's last read ``row_version``; a stale
one is refused with ``409 physical_pos.version_conflict`` — read again and
retry. Reason codes are closed sets checked by the gateway
(``400 physical_pos.input.reason_code_invalid``).

The routes marked "keyed" below require an ``Idempotency-Key``: the SDK
generates a UUID when you pass none and returns it in
:class:`~lunixi.physical_pos.results.PhysicalPosWriteResult`. The same key
with the same body returns the first result (``replayed``); with another body
it is ``409 physical_pos.idempotency_mismatch``. Use a new key per operation.

Device identity routes (activation codes, device keys) are not part of this
client.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Mapping, Optional

from ..api_client import ApiClient
from ..http.envelope import Page, data_of
from . import _support as s
from .client import PhysicalPosClient, _merge
from .results import PhysicalPosWriteResult

__all__ = ["PhysicalPosManagementClient"]

_STATUS_CHANGE: s.Schema = {
    "rowVersion": ("row_version", True, False),
    "reasonCode": ("str", True, False),
}
_CREATE_STORE: s.Schema = {
    "code": ("str", True, False),
    "name": ("str", True, False),
    "city": ("str", False, False),
    "district": ("str", False, False),
    "addressLine": ("str", False, False),
    "timezone": ("str", False, False),
    "externalRef": ("str", False, False),
}
_UPDATE_STORE: s.Schema = {
    "rowVersion": ("row_version", True, False),
    "name": ("str", False, False),
    "city": ("str", False, True),
    "district": ("str", False, True),
    "addressLine": ("str", False, True),
    "timezone": ("str", False, False),
    "externalRef": ("str", False, True),
}
_CREATE_REGISTER: s.Schema = {"code": ("str", True, False), "name": ("str", True, False)}
_UPDATE_REGISTER: s.Schema = {
    "rowVersion": ("row_version", True, False),
    "name": ("str", False, False),
}
_CREATE_TERMINAL: s.Schema = {
    "code": ("str", True, False),
    "displayName": ("str", True, False),
    "vendorCode": ("str", False, False),
    "virtualSerial": ("str", False, False),
    "vendorTerminalRef": ("str", False, False),
}
_UPDATE_TERMINAL: s.Schema = {
    "rowVersion": ("row_version", True, False),
    "displayName": ("str", False, False),
    "vendorCode": ("str", False, False),
}
_ADD_ACQUIRER: s.Schema = {
    "vendorAcquirerRef": ("str", True, False),
    "merchantNumber": ("str", True, False),
    "terminalNumber": ("str", True, False),
    "label": ("str", False, False),
    "currencies": ("str_list", True, False),
}
_UPDATE_ACQUIRER: s.Schema = {
    "rowVersion": ("row_version", True, False),
    "label": ("str", False, True),
    "currencies": ("str_list", False, False),
    "status": ("str", False, False),
}
_CHANGE_TERMINAL_DEVICE: s.Schema = {
    "rowVersion": ("row_version", True, False),
    "deviceId": ("str", True, False),
    "reasonCode": ("str", True, False),
}
_CREATE_DEVICE: s.Schema = {
    "vendorCode": ("str", True, False),
    "deviceModelId": ("str", True, False),
    "serialNumber": ("str", True, False),
    "displayName": ("str", False, False),
    "externalRef": ("str", False, False),
    "storeId": ("str", False, False),
    "registerId": ("str", False, False),
    "integrationChannel": ("str", True, False),
    "channelVariant": ("str", False, False),
    "appMode": ("str", False, False),
}
_UPDATE_DEVICE: s.Schema = {
    "rowVersion": ("row_version", True, False),
    "displayName": ("str", False, True),
    "externalRef": ("str", False, True),
    "integrationChannel": ("str", False, False),
    "channelVariant": ("str", False, True),
    "appMode": ("str", False, True),
}
_ASSIGN_DEVICE: s.Schema = {
    "rowVersion": ("row_version", True, False),
    "storeId": ("str", True, False),
    "registerId": ("str", False, True),
    "reasonCode": ("str", True, False),
}
_DEVICE_LIFECYCLE: s.Schema = {
    "rowVersion": ("row_version", True, False),
    "target": ("str", True, False),
    "reasonCode": ("str", True, False),
}


class PhysicalPosManagementClient:
    """Stores, registers, logical terminals, devices and the catalog behind them."""

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    # ── Overview and catalog ────────────────────────────────────────────────

    def get_overview(self) -> Dict[str, Any]:
        """Counts of stores, registers, terminals and devices for the key's environment."""
        return s.member(self._get("/overview"), "overview")

    def list_vendors(self) -> List[Dict[str, Any]]:
        """Device vendors (every status)."""
        return self._array(self._get("/catalog/vendors"))

    def list_device_models(self, **filters: Any) -> List[Dict[str, Any]]:
        """Device models. Filters: ``vendor_code``, ``device_type``, ``status``."""
        return self._array(
            self._get("/catalog/device-models", s.query(filters, "list_device_models"))
        )

    def list_acquirers(self) -> List[Dict[str, Any]]:
        """Active acquirer banks (``acquirerCode``, ``displayName``)."""
        return self._array(self._get("/catalog/acquirers"))

    # ── Stores ──────────────────────────────────────────────────────────────

    def list_stores(self, **filters: Any) -> Page:
        """Filters: ``limit``, ``cursor``, ``include_total``, ``status``, ``q`` (code or name prefix)."""
        return Page(self._get("/stores", s.query(filters, "list_stores")))

    def iterate_stores(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        return PhysicalPosClient._iterate(self.list_stores, filters)

    def create_store(
        self,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> PhysicalPosWriteResult:
        """Creates a store (keyed, 201): ``code``, ``name``, optional ``city``, ``district``, ``address_line``, ``timezone``, ``external_ref``."""
        return self._keyed("/stores", _merge(request, fields), _CREATE_STORE, idempotency_key, 201)

    def get_store(self, store_id: str) -> Dict[str, Any]:
        """``{store, registerSummary, assignedDeviceCount}``."""
        return s.data(self._get(f"/stores/{s.path_id(store_id, 'store_id')}"))

    def update_store(
        self, store_id: str, request: Optional[Mapping[str, Any]] = None, **fields: Any
    ) -> Dict[str, Any]:
        """``row_version`` plus the fields to change; an explicit ``None`` clears ``city``, ``district``, ``address_line`` or ``external_ref``."""
        path = f"/stores/{s.path_id(store_id, 'store_id')}"
        return s.member(self._send("PATCH", path, _merge(request, fields), _UPDATE_STORE), "store")

    def archive_store(
        self, store_id: str, request: Optional[Mapping[str, Any]] = None, **fields: Any
    ) -> Dict[str, Any]:
        """``row_version``, ``reason_code``; archives the active registers too. ``{store, archivedRegisterCount}``."""
        path = f"/stores/{s.path_id(store_id, 'store_id')}/archive"
        return s.data(self._send("POST", path, _merge(request, fields), _STATUS_CHANGE))

    def restore_store(
        self, store_id: str, request: Optional[Mapping[str, Any]] = None, **fields: Any
    ) -> Dict[str, Any]:
        """``row_version``, ``reason_code``; registers stay archived."""
        path = f"/stores/{s.path_id(store_id, 'store_id')}/restore"
        return s.member(self._send("POST", path, _merge(request, fields), _STATUS_CHANGE), "store")

    def list_store_audit(self, store_id: str, **filters: Any) -> Page:
        path = f"/stores/{s.path_id(store_id, 'store_id')}/audit"
        return Page(self._get(path, s.query(filters, "list_store_audit")))

    def iterate_store_audit(self, store_id: str, **filters: Any) -> Iterator[Dict[str, Any]]:
        return PhysicalPosClient._iterate(lambda **f: self.list_store_audit(store_id, **f), filters)

    # ── Registers ───────────────────────────────────────────────────────────

    def list_registers(self, store_id: str, **filters: Any) -> Page:
        """Filters: ``limit``, ``cursor``, ``include_total``, ``status``."""
        path = f"/stores/{s.path_id(store_id, 'store_id')}/registers"
        return Page(self._get(path, s.query(filters, "list_registers")))

    def iterate_registers(self, store_id: str, **filters: Any) -> Iterator[Dict[str, Any]]:
        return PhysicalPosClient._iterate(lambda **f: self.list_registers(store_id, **f), filters)

    def create_register(
        self,
        store_id: str,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> PhysicalPosWriteResult:
        """Creates a register in a store (keyed, 201): ``code``, ``name``."""
        path = f"/stores/{s.path_id(store_id, 'store_id')}/registers"
        return self._keyed(path, _merge(request, fields), _CREATE_REGISTER, idempotency_key, 201)

    def update_register(
        self, register_id: str, request: Optional[Mapping[str, Any]] = None, **fields: Any
    ) -> Dict[str, Any]:
        path = f"/registers/{s.path_id(register_id, 'register_id')}"
        return s.member(
            self._send("PATCH", path, _merge(request, fields), _UPDATE_REGISTER), "register"
        )

    def archive_register(
        self, register_id: str, request: Optional[Mapping[str, Any]] = None, **fields: Any
    ) -> Dict[str, Any]:
        path = f"/registers/{s.path_id(register_id, 'register_id')}/archive"
        return s.member(
            self._send("POST", path, _merge(request, fields), _STATUS_CHANGE), "register"
        )

    def restore_register(
        self, register_id: str, request: Optional[Mapping[str, Any]] = None, **fields: Any
    ) -> Dict[str, Any]:
        path = f"/registers/{s.path_id(register_id, 'register_id')}/restore"
        return s.member(
            self._send("POST", path, _merge(request, fields), _STATUS_CHANGE), "register"
        )

    def list_register_audit(self, register_id: str, **filters: Any) -> Page:
        path = f"/registers/{s.path_id(register_id, 'register_id')}/audit"
        return Page(self._get(path, s.query(filters, "list_register_audit")))

    def iterate_register_audit(self, register_id: str, **filters: Any) -> Iterator[Dict[str, Any]]:
        return PhysicalPosClient._iterate(
            lambda **f: self.list_register_audit(register_id, **f), filters
        )

    # ── Logical terminals ───────────────────────────────────────────────────

    def list_terminals(self, **filters: Any) -> Page:
        """Filters: ``limit``, ``cursor``, ``include_total``, ``status``, ``q``."""
        return Page(self._get("/terminals", s.query(filters, "list_terminals")))

    def iterate_terminals(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        return PhysicalPosClient._iterate(self.list_terminals, filters)

    def create_terminal(
        self,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> PhysicalPosWriteResult:
        """Creates a logical terminal (keyed, 201): ``code``, ``display_name``, optional ``vendor_code``, ``virtual_serial``, ``vendor_terminal_ref``."""
        return self._keyed(
            "/terminals", _merge(request, fields), _CREATE_TERMINAL, idempotency_key, 201
        )

    def get_terminal(self, terminal_id: str) -> Dict[str, Any]:
        """``{terminal, acquirers: {items, pageInfo}}``."""
        return s.data(self._get(f"/terminals/{s.path_id(terminal_id, 'terminal_id')}"))

    def update_terminal(
        self, terminal_id: str, request: Optional[Mapping[str, Any]] = None, **fields: Any
    ) -> Dict[str, Any]:
        path = f"/terminals/{s.path_id(terminal_id, 'terminal_id')}"
        return s.member(
            self._send("PATCH", path, _merge(request, fields), _UPDATE_TERMINAL), "terminal"
        )

    def close_terminal(
        self, terminal_id: str, request: Optional[Mapping[str, Any]] = None, **fields: Any
    ) -> Dict[str, Any]:
        path = f"/terminals/{s.path_id(terminal_id, 'terminal_id')}/close"
        return s.member(
            self._send("POST", path, _merge(request, fields), _STATUS_CHANGE), "terminal"
        )

    def list_terminal_acquirers(self, terminal_id: str, **filters: Any) -> Page:
        """The terminal's bank rows; ``id`` is what ``create_payment(terminal_acquirer_id=...)`` takes."""
        path = f"/terminals/{s.path_id(terminal_id, 'terminal_id')}/acquirers"
        return Page(self._get(path, s.query(filters, "list_terminal_acquirers")))

    def iterate_terminal_acquirers(
        self, terminal_id: str, **filters: Any
    ) -> Iterator[Dict[str, Any]]:
        return PhysicalPosClient._iterate(
            lambda **f: self.list_terminal_acquirers(terminal_id, **f), filters
        )

    def add_terminal_acquirer(
        self,
        terminal_id: str,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> PhysicalPosWriteResult:
        """Adds a bank row (keyed, 201): ``vendor_acquirer_ref``, ``merchant_number``, ``terminal_number``, ``currencies``, optional ``label``."""
        path = f"/terminals/{s.path_id(terminal_id, 'terminal_id')}/acquirers"
        return self._keyed(path, _merge(request, fields), _ADD_ACQUIRER, idempotency_key, 201)

    def update_terminal_acquirer(
        self, terminal_acquirer_id: str, request: Optional[Mapping[str, Any]] = None, **fields: Any
    ) -> Dict[str, Any]:
        """``row_version`` plus ``label`` (``None`` clears), ``currencies``, ``status``."""
        path = f"/terminal-acquirers/{s.path_id(terminal_acquirer_id, 'terminal_acquirer_id')}"
        return s.member(
            self._send("PATCH", path, _merge(request, fields), _UPDATE_ACQUIRER), "acquirer"
        )

    def change_terminal_device(
        self, terminal_id: str, request: Optional[Mapping[str, Any]] = None, **fields: Any
    ) -> Dict[str, Any]:
        """Links the terminal to a device: ``row_version``, ``device_id``, ``reason_code``. ``{terminal, link}``."""
        path = f"/terminals/{s.path_id(terminal_id, 'terminal_id')}/device-link"
        return s.data(self._send("POST", path, _merge(request, fields), _CHANGE_TERMINAL_DEVICE))

    def close_terminal_device_link(
        self,
        terminal_id: str,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> PhysicalPosWriteResult:
        """Unlinks the device (keyed): ``row_version``, ``reason_code``. ``{terminal, link}``."""
        path = f"/terminals/{s.path_id(terminal_id, 'terminal_id')}/device-link/close"
        return self._keyed(path, _merge(request, fields), _STATUS_CHANGE, idempotency_key)

    def list_terminal_links(self, terminal_id: str, **filters: Any) -> Page:
        path = f"/terminals/{s.path_id(terminal_id, 'terminal_id')}/links"
        return Page(self._get(path, s.query(filters, "list_terminal_links")))

    def iterate_terminal_links(self, terminal_id: str, **filters: Any) -> Iterator[Dict[str, Any]]:
        return PhysicalPosClient._iterate(
            lambda **f: self.list_terminal_links(terminal_id, **f), filters
        )

    def list_terminal_audit(self, terminal_id: str, **filters: Any) -> Page:
        path = f"/terminals/{s.path_id(terminal_id, 'terminal_id')}/audit"
        return Page(self._get(path, s.query(filters, "list_terminal_audit")))

    def iterate_terminal_audit(self, terminal_id: str, **filters: Any) -> Iterator[Dict[str, Any]]:
        return PhysicalPosClient._iterate(
            lambda **f: self.list_terminal_audit(terminal_id, **f), filters
        )

    # ── Devices ─────────────────────────────────────────────────────────────

    def list_devices(self, **filters: Any) -> Page:
        """Filters: ``limit``, ``cursor``, ``include_total``, ``store_id``, ``register_id``,
        ``vendor_code``, ``device_model_id``, ``device_type``, ``lifecycle_status``,
        ``ownership_status``, ``integration_channel``, ``q``."""
        return Page(self._get("/devices", s.query(filters, "list_devices")))

    def iterate_devices(self, **filters: Any) -> Iterator[Dict[str, Any]]:
        return PhysicalPosClient._iterate(self.list_devices, filters)

    def create_device(
        self,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> PhysicalPosWriteResult:
        """Registers a device (keyed, 201): ``vendor_code``, ``device_model_id``, ``serial_number``,
        ``integration_channel``, optional ``display_name``, ``external_ref``, ``store_id``,
        ``register_id``, ``channel_variant``, ``app_mode``."""
        return self._keyed(
            "/devices", _merge(request, fields), _CREATE_DEVICE, idempotency_key, 201
        )

    def get_device(self, device_id: str) -> Dict[str, Any]:
        """The device detail. Only this read fills ``presence``.

        ``presence``: ``connectionState`` (``ONLINE`` | ``OFFLINE`` |
        ``UNKNOWN``), ``lastSeenAt``, ``stateChangedAt``, ``offlineReason``,
        ``appVersion``, ``appHealthy``, ``paymentAppReachable``,
        ``readyForPayment``, ``notReadyReason``, ``source``, ``wakePaths``,
        ``busy``. A payment on a device that is not ready gets 409
        ``physical_pos.payment.device_offline`` (device-side reason) or 503
        ``physical_pos.presence.unavailable``; write results carry
        ``presence: None``.
        """
        return s.member(self._get(f"/devices/{s.path_id(device_id, 'device_id')}"), "device")

    def update_device(
        self, device_id: str, request: Optional[Mapping[str, Any]] = None, **fields: Any
    ) -> Dict[str, Any]:
        path = f"/devices/{s.path_id(device_id, 'device_id')}"
        return s.member(
            self._send("PATCH", path, _merge(request, fields), _UPDATE_DEVICE), "device"
        )

    def assign_device(
        self, device_id: str, request: Optional[Mapping[str, Any]] = None, **fields: Any
    ) -> Dict[str, Any]:
        """``row_version``, ``store_id``, ``register_id`` (optional), ``reason_code``.
        ``{device, assignment, previousAssignmentId}``."""
        path = f"/devices/{s.path_id(device_id, 'device_id')}/assignment"
        return s.data(self._send("POST", path, _merge(request, fields), _ASSIGN_DEVICE))

    def close_device_assignment(
        self,
        device_id: str,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> PhysicalPosWriteResult:
        """Moves the device to storage (keyed): ``row_version``, ``reason_code``. ``{device, closedAssignment, replayed}``."""
        path = f"/devices/{s.path_id(device_id, 'device_id')}/assignment/close"
        return self._keyed(path, _merge(request, fields), _STATUS_CHANGE, idempotency_key)

    def change_device_lifecycle(
        self, device_id: str, request: Optional[Mapping[str, Any]] = None, **fields: Any
    ) -> Dict[str, Any]:
        """``row_version``, ``target`` (``ACTIVE`` | ``SUSPENDED`` | ``MAINTENANCE``), ``reason_code``."""
        path = f"/devices/{s.path_id(device_id, 'device_id')}/lifecycle"
        return s.member(
            self._send("POST", path, _merge(request, fields), _DEVICE_LIFECYCLE), "device"
        )

    def retire_device(
        self,
        device_id: str,
        request: Optional[Mapping[str, Any]] = None,
        *,
        idempotency_key: Optional[str] = None,
        **fields: Any,
    ) -> PhysicalPosWriteResult:
        """Retires a device for good (keyed): ``row_version``, ``reason_code``. ``{device, replayed}``."""
        path = f"/devices/{s.path_id(device_id, 'device_id')}/retire"
        return self._keyed(path, _merge(request, fields), _STATUS_CHANGE, idempotency_key)

    def list_device_assignments(self, device_id: str, **filters: Any) -> Page:
        path = f"/devices/{s.path_id(device_id, 'device_id')}/assignments"
        return Page(self._get(path, s.query(filters, "list_device_assignments")))

    def iterate_device_assignments(
        self, device_id: str, **filters: Any
    ) -> Iterator[Dict[str, Any]]:
        return PhysicalPosClient._iterate(
            lambda **f: self.list_device_assignments(device_id, **f), filters
        )

    def list_device_audit(self, device_id: str, **filters: Any) -> Page:
        path = f"/devices/{s.path_id(device_id, 'device_id')}/audit"
        return Page(self._get(path, s.query(filters, "list_device_audit")))

    def iterate_device_audit(self, device_id: str, **filters: Any) -> Iterator[Dict[str, Any]]:
        return PhysicalPosClient._iterate(
            lambda **f: self.list_device_audit(device_id, **f), filters
        )

    # ── Internals ───────────────────────────────────────────────────────────

    def _get(self, path: str, query: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
        return s.call(
            lambda: self._api.request("GET", s.BASE + path, None, query=query, step_up=True)
        )

    def _send(self, method: str, path: str, request: Any, schema: s.Schema) -> Dict[str, Any]:
        payload = s.body(request, schema)
        return s.call(lambda: self._api.request(method, s.BASE + path, payload, step_up=True))

    def _keyed(
        self, path: str, request: Any, schema: s.Schema, key: Optional[str], fresh: int = 200
    ) -> PhysicalPosWriteResult:
        payload = s.body(request, schema)
        sent_key = s.idempotency_key(key)
        response = s.call(
            lambda: self._api.request(
                "POST", s.BASE + path, payload, step_up=True, idempotency_key=sent_key
            ),
            sent_key,
        )
        payload_data = s.data(response)
        replayed = payload_data.get("replayed") is True
        return PhysicalPosWriteResult(
            data=payload_data,
            replayed=replayed,
            status_code=s.status_code(response, 200 if replayed else fresh),
            idempotency_key=sent_key,
        )

    @staticmethod
    def _array(response: Any) -> List[Dict[str, Any]]:
        payload = data_of(response)
        return (
            [dict(item) for item in payload if isinstance(item, Mapping)]
            if isinstance(payload, list)
            else []
        )
