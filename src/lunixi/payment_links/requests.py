"""Builders for payment-link bodies: the link, its lines and its custom fields.

Amounts are canonical strings in the currency's minor unit (kuruş for TRY):
``"150000"`` is 1,500.00 TRY. The builders check types and value sets; the
business rules (title length, amount ranges, which fields a mode allows) are the
gateway's, which answers 422 ``payment_link.validation.invalid`` with
``details.errors``. Keys are emitted in the order the methods are called, after
``usage``, ``amountMode``, ``currency`` and ``title``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..errors import ConfigurationError
from ..payments.enabled_installments import validate_enabled_installments
from ..validation import SAFE_INTEGER, amount_minor
from .values import (
    ASSET_ID_PATTERN,
    BuyerFieldRequirement,
    CustomFieldType,
    PaymentLinkAmountMode,
    PaymentLinkButtonLabel,
    PaymentLinkDeliveryChannel,
    PaymentLinkEnvironment,
    PaymentLinkLocale,
    PaymentLinkUsage,
)

__all__ = [
    "CreatePaymentLinkRequest",
    "PaymentLinkItem",
    "PaymentLinkCustomField",
    "BUYER_FIELD_KEYS",
    "RECIPIENT_KEYS",
    "PREFILL_KEYS",
    "iso_or_null",
    "plain",
]

#: Keys of ``buyerFields``; each is ``HIDDEN`` | ``OPTIONAL`` | ``REQUIRED``.
BUYER_FIELD_KEYS = ("name", "email", "phone", "address", "identityNumber")
#: Keys of ``recipient``.
RECIPIENT_KEYS = ("name", "email", "phone")
#: Keys of ``prefill``.
PREFILL_KEYS = (
    "name",
    "surname",
    "email",
    "phone",
    "identityNumber",
    "address",
    "city",
    "country",
    "zipCode",
)


def plain(value: Any) -> Any:
    """A builder's body (``to_dict()``), or the value itself."""
    to_dict = getattr(value, "to_dict", None)
    return to_dict() if callable(to_dict) else value


def _one_of(value: Any, allowed: Tuple[str, ...], name: str) -> str:
    if value not in allowed:
        raise ConfigurationError(f"{name} must be one of {', '.join(allowed)}; got {value!r}.")
    return value


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ConfigurationError(f"{name} must be a non-empty string.")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ConfigurationError(f"{name} must be a string.")
    return value


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or abs(value) > SAFE_INTEGER:
        raise ConfigurationError(f"{name} must be an integer; got {value!r}.")
    return value


def _nullable_integer(value: Any, name: str) -> Optional[int]:
    return None if value is None else _integer(value, name)


def _minor(value: Any, name: str) -> str:
    try:
        return amount_minor(value, positive=False)
    except ConfigurationError:
        raise ConfigurationError(
            f"{name} must be a canonical string in minor units; got {value!r}."
        ) from None


def _nullable_asset_id(value: Any, name: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or ASSET_ID_PATTERN.fullmatch(value) is None:
        raise ConfigurationError(f"{name} must be an asset id (uuid) or None; got {value!r}.")
    return value


def _string_list(values: Any, name: str) -> List[str]:
    if not isinstance(values, (list, tuple)) or any(not isinstance(v, str) for v in values):
        raise ConfigurationError(f"{name} must be a list of strings.")
    return list(values)


def _object(value: Any, name: str) -> Optional[Dict[str, Any]]:
    value = plain(value)
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ConfigurationError(f"{name} must be an object.")
    return dict(value)


def _assert_keys(value: Mapping[str, Any], allowed: Tuple[str, ...], name: str) -> None:
    unknown = [str(key) for key in value if key not in allowed]
    if unknown:
        raise ConfigurationError(
            f"Unknown {name} field(s): {', '.join(unknown)}. Allowed: {', '.join(allowed)}."
        )


def _string_object(value: Any, allowed: Tuple[str, ...], name: str) -> Optional[Dict[str, str]]:
    """An object of string values with a closed key set; ``None`` clears it."""
    result = _object(value, name)
    if result is None:
        return None
    _assert_keys(result, allowed, name)
    for key, entry in result.items():
        if not isinstance(entry, str):
            raise ConfigurationError(f"{name}.{key} must be a string.")
    return result


def _string_record(value: Any, name: str) -> Optional[Dict[str, str]]:
    if value is None:
        return None
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) or not isinstance(entry, str) for key, entry in value.items()
    ):
        raise ConfigurationError(f"{name} must be an object whose values are strings.")
    return dict(value)


def iso_or_null(value: Any, name: str) -> Optional[str]:
    """An aware ``datetime`` (sent as UTC ISO-8601) or an ISO-8601 string; ``None`` clears."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ConfigurationError(f"{name} must be a timezone-aware datetime.")
        utc = value.astimezone(timezone.utc)
        return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"
    return _text(value, name)


class PaymentLinkItem:
    """One line of an ``ITEMIZED`` payment link.

    ``item_key`` is the line's permanent identity: stock counters hang off it,
    so it cannot change once the link exists. Without it the gateway assigns
    one (``it_…``).
    """

    def __init__(self, name: str, unit_price_minor: str) -> None:
        self._payload: Dict[str, Any] = {
            "name": _text(name, "PaymentLinkItem name"),
            "unitPriceMinor": _minor(unit_price_minor, "unitPriceMinor"),
        }

    def with_item_key(self, value: str) -> PaymentLinkItem:
        self._payload["itemKey"] = _text(value, "itemKey")
        return self

    def with_description(self, value: str) -> PaymentLinkItem:
        self._payload["description"] = _string(value, "description")
        return self

    def with_quantity_range(self, min_quantity: int, max_quantity: int) -> PaymentLinkItem:
        """Buyer-selectable quantity range; ``0`` as the minimum makes the line optional."""
        self._payload["minQuantity"] = _integer(min_quantity, "minQuantity")
        self._payload["maxQuantity"] = _integer(max_quantity, "maxQuantity")
        return self

    def with_capacity(self, value: Optional[int]) -> PaymentLinkItem:
        """Units available for this line across all payments; ``None`` = unlimited."""
        self._payload["capacity"] = _nullable_integer(value, "capacity")
        return self

    def with_image_asset_id(self, value: Optional[str]) -> PaymentLinkItem:
        """A published link image of your organisation (uuid); ``None`` = none."""
        self._payload["imageAssetId"] = _nullable_asset_id(value, "imageAssetId")
        return self

    def with_product_category(self, value: str) -> PaymentLinkItem:
        """A :class:`~lunixi.ProductCategory` code; sent as given (the list only grows)."""
        self._payload["productCategory"] = _text(value, "productCategory")
        return self

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._payload)


class PaymentLinkCustomField:
    """A typed question the buyer answers on the payment page (no file uploads)."""

    def __init__(self, key: str, label: str, field_type: str) -> None:
        self._payload: Dict[str, Any] = {
            "key": _text(key, "custom field key"),
            "label": _text(label, "custom field label"),
            "fieldType": _one_of(field_type, CustomFieldType.ALL, "fieldType"),
        }

    def with_required(self, value: bool = True) -> PaymentLinkCustomField:
        self._payload["required"] = bool(value)
        return self

    def with_options(self, values: Sequence[str]) -> PaymentLinkCustomField:
        """Choices of a ``SELECT`` field."""
        self._payload["options"] = _string_list(values, "options")
        return self

    def with_max_length(self, value: int) -> PaymentLinkCustomField:
        self._payload["maxLength"] = _integer(value, "maxLength")
        return self

    def with_help_text(self, value: str) -> PaymentLinkCustomField:
        self._payload["helpText"] = _string(value, "helpText")
        return self

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._payload)


class CreatePaymentLinkRequest:
    """Body of ``POST /api/v1/payments/links`` (``payment_links().create()``).

    .. code-block:: python

        request = (
            CreatePaymentLinkRequest.fixed(PaymentLinkUsage.SINGLE_USE, "150000", "TRY",
                                           "Invoice 2026-0042")
            .with_recipient({"name": "Ayşe Yılmaz", "email": "ayse@example.com"})
            .with_expires_at(datetime(2026, 12, 31, tzinfo=timezone.utc))
        )

    ``usage``, ``amount_mode`` and ``currency`` are fixed at creation.
    """

    @classmethod
    def fixed(
        cls, usage: str, amount_minor: str, currency: str, title: str
    ) -> CreatePaymentLinkRequest:
        """A link for a set amount."""
        return cls(usage, PaymentLinkAmountMode.FIXED, currency, title).with_amount_minor(
            amount_minor
        )

    @classmethod
    def open(
        cls,
        usage: str,
        currency: str,
        title: str,
        *,
        min_amount_minor: str,
        max_amount_minor: Optional[str] = None,
        suggested_amounts_minor: Optional[Sequence[str]] = None,
    ) -> CreatePaymentLinkRequest:
        """A link where the buyer enters the amount (donations, deposits).

        ``min_amount_minor`` is required; ``max_amount_minor`` and up to six
        ascending ``suggested_amounts_minor`` are optional.
        """
        request = cls(usage, PaymentLinkAmountMode.OPEN, currency, title).with_min_amount_minor(
            min_amount_minor
        )
        if max_amount_minor is not None:
            request.with_max_amount_minor(max_amount_minor)
        if suggested_amounts_minor:
            request.with_suggested_amounts_minor(suggested_amounts_minor)
        return request

    @classmethod
    def itemized(
        cls, usage: str, currency: str, title: str, items: Sequence[Any]
    ) -> CreatePaymentLinkRequest:
        """A link where the buyer picks quantities of the given lines (1–50 items)."""
        return cls(usage, PaymentLinkAmountMode.ITEMIZED, currency, title).with_items(items)

    def __init__(self, usage: str, amount_mode: str, currency: str, title: str) -> None:
        self._payload: Dict[str, Any] = {
            "usage": _one_of(usage, PaymentLinkUsage.ALL, "usage"),
            "amountMode": _one_of(amount_mode, PaymentLinkAmountMode.ALL, "amountMode"),
            "currency": _text(currency, "currency").upper(),
            "title": _text(title, "title"),
        }

    def with_environment(self, value: str) -> CreatePaymentLinkRequest:
        """Optional: the API key decides the environment; a different value is 403."""
        self._payload["environment"] = _one_of(value, PaymentLinkEnvironment.ALL, "environment")
        return self

    def with_amount_minor(self, value: str) -> CreatePaymentLinkRequest:
        self._payload["amountMinor"] = _minor(value, "amountMinor")
        return self

    def with_min_amount_minor(self, value: str) -> CreatePaymentLinkRequest:
        self._payload["minAmountMinor"] = _minor(value, "minAmountMinor")
        return self

    def with_max_amount_minor(self, value: str) -> CreatePaymentLinkRequest:
        self._payload["maxAmountMinor"] = _minor(value, "maxAmountMinor")
        return self

    def with_suggested_amounts_minor(self, values: Sequence[str]) -> CreatePaymentLinkRequest:
        if not isinstance(values, (list, tuple)):
            raise ConfigurationError(
                "suggestedAmountsMinor must be a list of canonical minor-unit strings."
            )
        self._payload["suggestedAmountsMinor"] = [
            _minor(value, "suggestedAmountsMinor[]") for value in values
        ]
        return self

    def with_quantity(self, min_quantity: int, max_quantity: int) -> CreatePaymentLinkRequest:
        """Lets the buyer choose a quantity (FIXED + MULTI_USE only), 1–999."""
        self._payload["quantityEnabled"] = True
        self._payload["minQuantity"] = _integer(min_quantity, "minQuantity")
        self._payload["maxQuantity"] = _integer(max_quantity, "maxQuantity")
        return self

    def with_items(self, items: Sequence[Any]) -> CreatePaymentLinkRequest:
        if not isinstance(items, (list, tuple)) or len(items) == 0:
            raise ConfigurationError("An ITEMIZED payment link needs at least one item.")
        self._payload["items"] = [plain(item) for item in items]
        return self

    def add_item(self, item: Any) -> CreatePaymentLinkRequest:
        self._payload["items"] = [*self._payload.get("items", []), plain(item)]
        return self

    def with_capacity(self, value: Optional[int]) -> CreatePaymentLinkRequest:
        """Total units the link can sell (MULTI_USE only); ``None`` = unlimited."""
        self._payload["capacity"] = _nullable_integer(value, "capacity")
        return self

    def with_description(self, value: str) -> CreatePaymentLinkRequest:
        """Plain text, shown as text (no HTML or Markdown)."""
        self._payload["description"] = _string(value, "description")
        return self

    def with_image_asset_id(self, value: Optional[str]) -> CreatePaymentLinkRequest:
        """A published link image of your organisation (uuid); ``None`` = none."""
        self._payload["imageAssetId"] = _nullable_asset_id(value, "imageAssetId")
        return self

    def with_success_message(self, value: str) -> CreatePaymentLinkRequest:
        self._payload["successMessage"] = _string(value, "successMessage")
        return self

    def with_success_redirect_url(self, value: Optional[str]) -> CreatePaymentLinkRequest:
        """``https://`` only; ``None`` clears it."""
        self._payload["successRedirectUrl"] = (
            None if value is None else _text(value, "successRedirectUrl")
        )
        return self

    def with_tax_note(self, value: str) -> CreatePaymentLinkRequest:
        self._payload["taxNote"] = _string(value, "taxNote")
        return self

    def with_locale(self, value: str) -> CreatePaymentLinkRequest:
        """Language of the payment page: ``tr`` or ``en`` (:class:`PaymentLinkLocale`)."""
        self._payload["locale"] = _one_of(value, PaymentLinkLocale.ALL, "locale")
        return self

    def with_starts_at(self, value: Any) -> CreatePaymentLinkRequest:
        self._payload["startsAt"] = iso_or_null(value, "startsAt")
        return self

    def with_expires_at(self, value: Any) -> CreatePaymentLinkRequest:
        self._payload["expiresAt"] = iso_or_null(value, "expiresAt")
        return self

    def with_event_at(self, value: Any) -> CreatePaymentLinkRequest:
        """Display only (e.g. the event date of a ticket)."""
        self._payload["eventAt"] = iso_or_null(value, "eventAt")
        return self

    def with_button_label_key(self, value: Optional[str]) -> CreatePaymentLinkRequest:
        """``PAY``, ``DONATE``, ``BUY`` or ``BOOK``; ``None`` = your organisation's default."""
        self._payload["buttonLabelKey"] = (
            None if value is None else _one_of(value, PaymentLinkButtonLabel.ALL, "buttonLabelKey")
        )
        return self

    def with_terms_acceptance_required(self, value: bool = True) -> CreatePaymentLinkRequest:
        self._payload["requireTermsAcceptance"] = bool(value)
        return self

    def with_buyer_fields(self, value: Optional[Mapping[str, str]]) -> CreatePaymentLinkRequest:
        """Each of ``name``, ``email``, ``phone``, ``address``, ``identityNumber``:
        ``HIDDEN`` | ``OPTIONAL`` | ``REQUIRED`` (:class:`BuyerFieldRequirement`)."""
        fields = _object(value, "buyerFields")
        if fields is not None:
            _assert_keys(fields, BUYER_FIELD_KEYS, "buyerFields")
            for key, requirement in fields.items():
                _one_of(requirement, BuyerFieldRequirement.ALL, f"buyerFields.{key}")
        self._payload["buyerFields"] = fields
        return self

    def with_custom_fields(self, fields: Sequence[Any]) -> CreatePaymentLinkRequest:
        if not isinstance(fields, (list, tuple)):
            raise ConfigurationError("customFields must be a list.")
        self._payload["customFields"] = [plain(entry) for entry in fields]
        return self

    def add_custom_field(self, entry: Any) -> CreatePaymentLinkRequest:
        self._payload["customFields"] = [*self._payload.get("customFields", []), plain(entry)]
        return self

    def with_recipient(self, value: Optional[Mapping[str, str]]) -> CreatePaymentLinkRequest:
        """Who the link is for (``name``, ``email``, ``phone`` in E.164). Stored encrypted."""
        self._payload["recipient"] = _string_object(value, RECIPIENT_KEYS, "recipient")
        return self

    def with_prefill(self, value: Optional[Mapping[str, str]]) -> CreatePaymentLinkRequest:
        """Buyer details filled in on the server side; never sent to the browser.

        Keys: ``name``, ``surname``, ``email``, ``phone``, ``identityNumber``,
        ``address``, ``city``, ``country`` (ISO 3166-1 alpha-2), ``zipCode``.
        """
        self._payload["prefill"] = _string_object(value, PREFILL_KEYS, "prefill")
        return self

    def with_verification(
        self, required: bool = True, channel: str = PaymentLinkDeliveryChannel.EMAIL
    ) -> CreatePaymentLinkRequest:
        """A one-time code to ``recipient.email`` before paying. Only ``EMAIL`` is available."""
        self._payload["verification"] = {
            "required": bool(required),
            "channel": _one_of(channel, PaymentLinkDeliveryChannel.ALL, "verification channel"),
        }
        return self

    def with_reminders(self, interval_hours: int, max_count: int) -> CreatePaymentLinkRequest:
        """Reminder e-mails (SINGLE_USE with a recipient): every 24–168 hours, 1–3 times."""
        self._payload["reminders"] = {
            "enabled": True,
            "intervalHours": _integer(interval_hours, "intervalHours"),
            "maxCount": _integer(max_count, "maxCount"),
        }
        return self

    def with_checkout(
        self,
        *,
        require_three_ds: bool = False,
        payment_methods: Sequence[str] = (),
        enabled_installments: Sequence[int] = (),
    ) -> CreatePaymentLinkRequest:
        """Narrows the checkout.

        ``require_three_ds`` can only tighten; ``payment_methods`` is a subset
        of your form settings (empty = your form settings);
        ``enabled_installments`` lists the installment counts the form may
        offer (empty = no restriction; otherwise integers 1–36, no duplicates,
        1 included).
        """
        checkout: Dict[str, Any] = {
            "requireThreeDs": bool(require_three_ds),
            "paymentMethods": _string_list(payment_methods, "paymentMethods"),
        }
        if not isinstance(enabled_installments, (list, tuple)) or len(enabled_installments) > 0:
            checkout["enabledInstallments"] = validate_enabled_installments(
                enabled_installments, "checkout.enabledInstallments"
            )
        self._payload["checkout"] = checkout
        return self

    def with_reference(self, value: str) -> CreatePaymentLinkRequest:
        self._payload["reference"] = _string(value, "reference")
        return self

    def with_tags(self, values: Sequence[str]) -> CreatePaymentLinkRequest:
        self._payload["tags"] = _string_list(values, "tags")
        return self

    def with_branch_code(self, value: str) -> CreatePaymentLinkRequest:
        self._payload["branchCode"] = _string(value, "branchCode")
        return self

    def with_sales_channel(self, value: str) -> CreatePaymentLinkRequest:
        self._payload["salesChannel"] = _string(value, "salesChannel")
        return self

    def with_campaign(self, value: str) -> CreatePaymentLinkRequest:
        self._payload["campaign"] = _string(value, "campaign")
        return self

    def with_agent_code(self, value: str) -> CreatePaymentLinkRequest:
        self._payload["agentCode"] = _string(value, "agentCode")
        return self

    def with_merchant_notify_emails(self, values: Sequence[str]) -> CreatePaymentLinkRequest:
        self._payload["merchantNotifyEmails"] = _string_list(values, "merchantNotifyEmails")
        return self

    def with_metadata(self, value: Optional[Mapping[str, str]]) -> CreatePaymentLinkRequest:
        """Up to 20 string key/value pairs returned to you in webhooks."""
        self._payload["metadata"] = _string_record(value, "metadata")
        return self

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._payload)
