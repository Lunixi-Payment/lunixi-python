"""Lunixi address dictionary for Türkiye (province → district → neighborhood).

The codes fill an ``ADDRESS`` input field of a payment method, for example the
debtor address of a promissory-note payment:
``{"provinceCode", "districtCode", "neighborhoodCode", "line"}``.

* ``GET /api/v1/reference/tr-address/provinces``
* ``GET /api/v1/reference/tr-address/districts?provinceCode=06``
* ``GET /api/v1/reference/tr-address/neighborhoods?districtCode=...``

The answer is the gateway envelope with ``data.items: [{"code", "name"}]``. An
empty list means the data of that level is not published yet; show that state
instead of inventing codes.
"""

from __future__ import annotations

import re
from typing import Any, Dict

from ..api_client import ApiClient
from ..errors import ConfigurationError

__all__ = ["ReferenceClient"]

_BASE = "/api/v1/reference/tr-address"
_PROVINCE_CODE = re.compile(r"0[1-9]|[1-7][0-9]|8[01]")
_DISTRICT_CODE = re.compile(r"[0-9]{1,12}")


class ReferenceClient:
    """Reference data shared by the payment methods."""

    def __init__(self, api: ApiClient) -> None:
        self._api = api

    def list_provinces(self) -> Dict[str, Any]:
        """Provinces with their Lunixi code (``01``–``81``)."""
        return self._api.request("GET", _BASE + "/provinces")

    def list_districts(self, province_code: str) -> Dict[str, Any]:
        """Districts of a province (``province_code`` ``01``–``81``)."""
        if not isinstance(province_code, str) or _PROVINCE_CODE.fullmatch(province_code) is None:
            raise ConfigurationError(
                "province_code must be a two-digit province code from 01 to 81; "
                f"got {province_code!r}."
            )
        return self._api.request("GET", _BASE + "/districts", query={"provinceCode": province_code})

    def list_neighborhoods(self, district_code: str) -> Dict[str, Any]:
        """Neighborhoods of a district (``district_code`` from :meth:`list_districts`)."""
        if not isinstance(district_code, str) or _DISTRICT_CODE.fullmatch(district_code) is None:
            raise ConfigurationError(
                "district_code must be a district code (digits) from list_districts(); "
                f"got {district_code!r}."
            )
        return self._api.request(
            "GET", _BASE + "/neighborhoods", query={"districtCode": district_code}
        )
