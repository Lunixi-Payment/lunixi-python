<p align="center">
  <a href="https://lunixi.com">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/Lunixi-Payment/lunixi-python/main/.github/assets/lunixi-logo-dark.svg">
      <img src="https://raw.githubusercontent.com/Lunixi-Payment/lunixi-python/main/.github/assets/lunixi-logo.svg" alt="Lunixi" height="64">
    </picture>
  </a>
</p>

# Lunixi Python SDK

**Version 1.0.2 uses canonical minor-unit strings for money.** This is a breaking change from 0.x; update request and response handling together. See [migration](MIGRATION-1.0.md).

[![CI](https://github.com/Lunixi-Payment/lunixi-python/actions/workflows/ci.yml/badge.svg)](https://github.com/Lunixi-Payment/lunixi-python/actions/workflows/ci.yml) [![PyPI](https://img.shields.io/pypi/v/lunixi-sdk)](https://pypi.org/project/lunixi-sdk/) [![Python](https://img.shields.io/pypi/pyversions/lunixi-sdk)](https://pypi.org/project/lunixi-sdk/) [![Downloads](https://img.shields.io/pypi/dm/lunixi-sdk)](https://pypi.org/project/lunixi-sdk/) [![Typed](https://img.shields.io/badge/typing-typed-blue)](https://peps.python.org/pep-0561/) [![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE) [![Docs](https://img.shields.io/badge/docs-docs.lunixi.com-FF6B35)](https://docs.lunixi.com/sdks/python)

**[Documentation](https://docs.lunixi.com/sdks/python) · [Changelog](https://github.com/Lunixi-Payment/lunixi-python/blob/main/CHANGELOG.md) · [Issues](https://github.com/Lunixi-Payment/lunixi-python/issues) · [Security](https://github.com/Lunixi-Payment/lunixi-python/blob/main/SECURITY.md)**

Version **1.0.2** adds typed payment APIs and durable checkout orchestration while preserving the existing fraud decision/event API. The SDK is synchronous, thread-safe per client, and ships `py.typed`.

[Turkish](README.tr.md) · [Framework examples](docs/FRAMEWORKS.md) · [Django](docs/DJANGO.md) · [FastAPI](docs/FASTAPI.md) · [Flask](docs/FLASK.md)

| Component | Requirement |
|---|---|
| Core SDK | Python 3.9+; use a maintained Python runtime for deployment |
| Runtime dependencies | `cryptography>=50.0.2,<51`, `rfc8785>=0.1.4,<0.2`; stdlib HTTP/SQLite |
| Verified framework targets | Django 6.1.2 / FastAPI 0.162.0 / Flask 3.1.3 on Python 3.12.14 |
| Payment form | Official Lunixi browser bundle or hosted `pay.lunixi.com` |
| Durable example storage | SQLite on disk; Django's native ORM with IMMEDIATE transactions |

## Install

```sh
pip install lunixi-sdk==1.0.2
```

Version 1.0.2 is published on PyPI. The 0.x packages use the previous money contract.

From a source checkout, `pip install -e .` installs the SDK; `pip install -e '.[frameworks]'` installs optional runtime dependencies. Framework apps and full native tests need Python 3.12+ and the source checkout. They are runnable examples, not separately registered framework packages.

## Payment quick start

```python
import os
from lunixi import LunixiClient, CreateIntent

client = LunixiClient(
    base_url="https://api-gateway.lunixi.com",
    key_id=os.environ["LUNIXI_KEY_ID"],
    private_key=os.environ["LUNIXI_PRIVATE_KEY"],
    max_retries=0,
)
# Order details every payment requires (take them from your checkout, never a placeholder).
order = dict(
    buyer={"name": "Ada", "surname": "Yilmaz", "identityNumber": "11111111111",
           "email": "ada@example.com", "gsmNumber": "+905350000000",
           "city": "Istanbul", "country": "Turkey", "zipCode": "34000"},
    billing_address={"contactName": "Ada Yilmaz", "address": "Example Street 1",
                     "city": "Istanbul", "country": "Turkey", "zipCode": "34000"},
    basket_items=[{"id": "SKU-1", "name": "Gift card", "category1": "Digital",
                   "itemType": "VIRTUAL", "price": "1990"}],
)
intent = client.payments().create_intent(
    CreateIntent("1990", "TRY", "persisted-order-123",
                 callback_url="https://shop.example/return/123",
                 enabled_installments=[1, 2, 3],  # optional: at most 3 installments
                 **order),
    idempotency_key=persisted_attempt_key,
)
# Return only after authenticating ownership of the persisted order:
public_form_configuration = intent.browser_config()
# Or redirect to the validated backend paymentPageUrl:
hosted_url = intent.hosted_url
```

Money is canonical minor-unit strings, from 1 to 9,223,372,036,854,775,807; booleans, floats, zero and removed root amount fields fail before token exchange/network. `minor_units('19.90','TRY')` converts a plain decimal string exactly; JPY has0 decimals and KWD 3. Preauthorization is a JSON boolean; an authorization is on hold, not paid. Available methods, installments, eligible shopping credit/meal cards, insurance and multi-card options belong to the Lunixi form/panel. `enabled_installments` only narrows the installment counts the form offers for one payment (`[1]` = single payment only); the form shows only the counts your panel settings, the card and the platform maximum also allow, and `None` means no restriction. Counts are integers 1–36, distinct and include 1, otherwise `ConfigurationError` is raised before any request; the list is sent as `enabledInstallments` in ascending order. The examples never collect card numbers/CVV.

Every payment body carries the order details (`lunixi.payments.order_details`): `buyer` (`name`, `surname`, `identityNumber` — Turkish ID or passport number, `email` — ASCII, `gsmNumber`, `city`, `country`, `zipCode`, `ip` — the buyer's browser IP), `billingAddress` (`contactName`, `address`, `city`, `country`, `zipCode`) and at least one `basketItems` entry (`id`, `name`, `category1`, `itemType`, `price`; the prices add up to the amount); a `PHYSICAL` item also needs `shippingAddress`. On `CreateIntent` and the marketplace intents `ip` may be left out: the Lunixi form takes it from the buyer's browser. `create_intent`, `create_marketplace_intent`, `direct_method_payment`, `create_split_payment`, marketplace card charges, `store_card` (buyer and billing address only) and the wallet card top-up raise `ConfigurationError` naming the missing paths before sending (`missing_order_details(body)` returns the same list). The gateway answers a missing field with 400 `payment.order.field_required` and an invalid one with `payment.order.field_invalid` (`OrderFieldErrorCode`, `OrderFieldReason`).

Basket items accept the optional `productCategory` on each entry: the Lunixi product category code, used by payment methods with legal installment limits (e.g. shopping loan) and other platform features. Leaving it out keeps today's behaviour; the gateway rejects an unknown code with 400. The codes are available as `ProductCategory` constants (`from lunixi import ProductCategory`; `ProductCategory.MOBILE_PHONE`, all 40 in `ProductCategory.ALL`). The list only grows by appending, so the value stays a plain string and the SDK does not check it before sending.

| Helper | Merchant API |
|---|---|
| `payments().create_intent(CreateIntent(...), idempotency_key=...)` | POST `/api/v1/payments/intents` → canonical response `paymentId` and `token` |
| `get(payment_id)`, `list(**filters)` | GET `/api/v1/payments/{id}`, `/api/v1/payments` |
| `capture(id, amount, idempotency_key=...)` | POST `/api/v1/payments/{id}/capture` |
| `refund(id, amount, idempotency_key=..., reason=...)` | POST `/api/v1/payments/{id}/refund` |
| `void(id, idempotency_key=...)` | POST `/api/v1/payments/{id}/void` |
| `list_payment_methods(payment_method=None)`, `methods(payment_method=None)` | GET `/api/v1/payments/methods[?paymentMethod=]`, signed |
| `direct_method_payment(DirectMethodPaymentRequest(...), idempotency_key=...)` | POST `/api/v1/payments/direct/payment`, signed |
| `confirm_payment_action(payment_id, action_id, otp=..., consent_accepted=..., fields=...)`, `resend_payment_action(payment_id, action_id)` | POST `/api/v1/payments/{id}/actions/{actionId}/confirm`, `/resend`, signed |
| `get_promissory_notes(id)`, `cancel_promissory_notes(id, serial_numbers=None)`, `download_promissory_note_document(id, locale=None)` | `/api/v1/payments/{id}/promissory-notes`, `/cancel`, `/document` (PDF), signed |
| `list_bank_transfer_exceptions(environment=, status=, limit=)`, `accept_bank_transfer_exception(id)`, `mark_bank_transfer_exception_refunded(id)` | `/api/v1/payments/bank-transfer/exceptions`, `/{id}/accept`, `/{id}/refunded`, signed |
| `create_split_payment(SplitPaymentRequest(...), idempotency_key=...)` | POST `/api/v1/payments/split`, signed |
| `get_split(id)`, `list_splits(**filters)` | GET `/api/v1/payments/split/{id}`, `/api/v1/payments/split` |
| `refund_split(id, amount, idempotency_key=...)` | POST `/api/v1/payments/split/{id}/refund` |
| `create_marketplace_intent(CreateIntent(...), sellers=[...], multi_seller_policy=None, idempotency_key=None)` | POST `/api/v1/payments/marketplace/intents`, signed |
| `bin_info(bin_or_pan)`, `installment_options(InstallmentOptionsRequest(...))`, `card_taxonomy()` | POST `/api/v1/bin/info`, `/api/v1/bin/installments`, GET `/api/v1/bin/card-taxonomy` |
| `store_card(StoreCardRequest(...), idempotency_key=...)`, `deactivate_stored_card(token, idempotency_key=...)` | POST `/api/v1/payments/cards`, DELETE `/api/v1/payments/cards/{token}`, signed |
| `list_stored_cards(card_user_key)`, `get_stored_card(token)` | GET `/api/v1/payments/cards[?cardUserKey=]`, `/api/v1/payments/cards/{token}` |
| `failover_recovery_analytics(**filters)`, `provider_credential_analytics(credential_id, **filters)` | GET `/api/v1/payments/analytics/failover-recovery`, `/provider-credentials/{id}` |
| `client.reference().list_provinces()`, `list_districts(province_code)`, `list_neighborhoods(district_code)` | GET `/api/v1/reference/tr-address/*` |

Non-intent helpers return the complete response envelope, preserving `details`, `pageInfo` and request IDs. Financial helper keys are required and must come from durable application records. An HTTP 2xx mutation response does not prove settlement.

## Payment methods from your server

`list_payment_methods()` lists the methods open for your account with, per provider, the `providerCode` and the `inputFields` to send. Always read the provider code from this answer; never hard-code it. `list_payment_methods("MOBILE_BILLING")` narrows the list to one method (`QR` is sent as `QR_CODE`; a code that is not `[A-Z][A-Z0-9_]{0,31}` raises `ConfigurationError`).

```python
from lunixi import DirectMethodPaymentRequest, PaymentActionType, PaymentMethod

request = (
    DirectMethodPaymentRequest("15000", "TRY", "persisted-order-123")
    .with_method_fields(PaymentMethod.MOBILE_BILLING, provider_code, {"gsmNumber": "+905321234567"})
    .with_callback_url("https://shop.example/return/123")
)
response = client.payments().direct_method_payment(request, idempotency_key=persisted_attempt_key)
action = response["data"].get("action")
if action and action["type"] == PaymentActionType.OTP:
    client.payments().confirm_payment_action(
        response["data"]["paymentId"], action["id"], otp=code_from_buyer
    )
```

The body carries exactly one method block, named after the method (`MOBILE_BILLING` → `mobileBilling`; `METHOD_BLOCK_FIELDS` lists them). Before anything is sent the SDK refuses: an unknown field, `price`/`paidPrice`, a block of another method, a missing block, card fields (`CARD_ONLY_FIELDS`) on a non-card method, a method without a block, a shopping-loan basket outside 1–100 items, and a block with a shape the gateway would refuse (at most 32 fields with names `[A-Za-z][A-Za-z0-9]{0,63}`; values are strings of at most 1024 characters, numbers, booleans, `ADDRESS` objects of at most 16 fields, or `GROUP` lists of at most 10 objects). A raw body mapping passed instead of the builder is checked with the same rules. The `idempotency_key` is required. `with_card(card)` with `with_force3d(True)` and `with_installment(count, quote_token)` is the card variant.

`confirm_payment_action()` sends only `otp` (digits, at most 16), `consent_accepted` (boolean) and `fields`; any other keyword raises `ConfigurationError`. `resend_payment_action()` closes the action and opens a new one.

### Para Transferi (bank transfer)

`BANK_TRANSFER` takes no provider code: pass `None` and the buyer's bank as `{"bankCode": ...}`, or `BANK_TRANSFER_OTHER_BANKS_CODE` (`"9999"`) for a bank that is not listed. The answer is a `DISPLAY` action with the transfer instruction for the buyer:

```python
from lunixi import BankTransferInstruction

request = DirectMethodPaymentRequest("15000", "TRY", "persisted-order-123").with_method_fields(
    PaymentMethod.BANK_TRANSFER, None, {"bankCode": buyer_bank_code}
)
response = client.payments().direct_method_payment(request, idempotency_key=persisted_attempt_key)
instruction = BankTransferInstruction.from_response(response)  # None without a DISPLAY action
if instruction:
    show(instruction.iban, instruction.holder_name, instruction.amount_minor, instruction.payment_code)
```

The money goes to your own bank account and is matched by the payment code. Late, short and excess transfers are listed with `list_bank_transfer_exceptions(environment="LIVE", status="PENDING_DECISION", limit=50)` (`limit` 1–200) and decided with `accept_bank_transfer_exception(id)` or `mark_bank_transfer_exception_refunded(id)` (the id is a UUID). Constants: `PaymentBankTransferExceptionKind`, `PaymentBankTransferExceptionStatus` and the webhook events `PaymentBankTransferEvents` (`payment.bank_transfer.*`).

### Promissory notes

A `PROMISSORY_NOTE` payment carries a plan: `with_promissory_note_schedule([{"amount": "10000", "dueDate": "2027-01-15"}, ...])` (1–24 rows, canonical minor-unit amounts adding up to `amount`, real `YYYY-MM-DD` dates in ascending order) or `with_promissory_note_count(6)` (1–24), never both. `get_promissory_notes(payment_id)` returns the notes, `cancel_promissory_notes(payment_id, serial_numbers=None)` cancels all open notes or the listed ones, and `download_promissory_note_document(payment_id, locale="tr-TR")` returns a `BinaryResponse` whose `content` holds the PDF bytes (`PromissoryNoteDocumentLocale`: `tr-TR`, `en-GB`). Status, result and event constants: `PromissoryNoteStatus`, `PromissoryNoteCancelResult`, `PromissoryNoteCancelErrorCode`, `PromissoryNoteEvents`. Codes for an `ADDRESS` field come from `client.reference()` (provinces, districts, neighborhoods).

### Split payments

```python
from lunixi import SplitPaymentRequest

request = (
    SplitPaymentRequest("30000", "TRY", customer_ref)
    .with_order_id("persisted-order-123")
    .add_card_leg(stored_card_token, "20000")
    .add_method_leg(PaymentMethod.WALLET, provider_code, "10000", {})
)
response = client.payments().create_split_payment(request, idempotency_key=persisted_split_key)
```

The idempotency key (at most 200 characters) is the identity of the split payment: after a step, send the same request with the same key and the payment continues. While it is running the gateway answers HTTP 400 with the status as `code` (`SPLIT_PAYMENT_IN_PROGRESS_STATUSES`) and `data.splitPaymentId`; that answer is returned, not raised. A non-card leg carries only a `mobileBilling`, `wallet` or `promissoryNote` block (`SPLIT_LEG_BLOCK_FIELDS`) with its provider code; meal card, open banking, shopping loan and bank transfer cannot be legs. `list_splits()` checks its filters (`status`, `currency`, `createdFrom`, `createdTo`, `orderId`, `ownerRef`, `limit` 1–100, `after`). Webhook constants: `SplitPaymentEvents` and the leg subscription key `SPLIT_LEG_EVENTS_SUBSCRIPTION`.

### Cards, installments and marketplace intents

`bin_info("54000000")` answers the card, bank and installment eligibility of a BIN; `installment_options(InstallmentOptionsRequest("10050", "TRY", bin_or_pan=bin, installment=3, enabled_installments=[1, 2, 3]))` returns the installment table and, for a BIN with `installment` > 1, a binding `quoteToken` for `DirectMethodPaymentRequest.with_installment(count, quote_token)`. `enabled_installments` follows the same rule as `CreateIntent` (integers 1–36, distinct, 1 included). A BIN or card number is digits only and is never placed in an error message. `store_card(StoreCardRequest(card, card_user_key, callback_url), idempotency_key=...)` and `deactivate_stored_card(token, idempotency_key=...)` are signed and need the key.

```python
from lunixi import CreateIntent, MultiSellerPolicy

response = client.payments().create_marketplace_intent(
    CreateIntent("10050", "TRY", "persisted-order-123", **order),  # order details as above
    sellers=[
        {"subDealerId": "d_alice", "amountMinor": "6000"},
        {"subDealerId": "d_bob", "amountMinor": "4050"},
    ],
    multi_seller_policy=MultiSellerPolicy.ALL_OR_NOTHING,
    idempotency_key=persisted_attempt_key,
)
```

The sellers' `amountMinor` values (canonical minor-unit strings) must add up to `amount`; any other total raises `ConfigurationError` before sending.

## Payment links

`client.payment_links()` creates and manages shareable payment pages. Every call is signed with your key, reads included; the key's environment decides whether you see TEST or LIVE links.

```python
from lunixi import CreatePaymentLinkRequest, PaymentLinkDeliveryChannel, PaymentLinkUsage

links = client.payment_links()
created = links.create(
    CreatePaymentLinkRequest.fixed(PaymentLinkUsage.SINGLE_USE, "150000", "TRY", "Invoice 2026-0042")
    .with_recipient({"name": "Test Buyer", "email": "buyer@example.com"}),
    idempotency_key=persisted_link_key,
)
links.send(created["id"], channel=PaymentLinkDeliveryChannel.EMAIL, idempotency_key=persisted_send_key)
page = links.list(state=["ACTIVE", "PAUSED"], limit=20)
```

`create()` and `send()` need an idempotency key of 8–200 printable ASCII characters; repeating it returns the stored result with `replayed: True`. `update(link_id, expected_row_version, changes)` changes only the given fields (`None` clears one) and refuses `usage`, `amountMode` and `currency`; `pause()`, `resume()` and `deactivate()` change the state. `qr(link_id, format="png", size=512)` returns the image as `BinaryResponse`. `list()`, `list_attempts()` and `list_payments()` return a `Page`; `iterate…()` follows the cursors. Unknown body fields and filters raise `ConfigurationError`.

A link image is uploaded in three steps, or with one call:

```python
image = links.upload_image(file_name="cover.png", content_type="image/png", content=png_bytes)
request = CreatePaymentLinkRequest.fixed(
    PaymentLinkUsage.MULTI_USE, "25000", "TRY", "Concert ticket"
).with_image_asset_id(image["assetId"])
```

`upload_image()` runs `create_image_upload()`, a PUT of the bytes to the presigned `uploadUrl` and `confirm_image_upload(asset_id)`. The PUT goes through your configured transport directly to the storage host with only the returned `uploadHeaders`: it never carries your access token or the request signature. PNG, JPEG and WebP are accepted (SVG is not), up to 2 MiB and 4096×4096 px. A custom `HttpTransport` receives `bytes` as the body of that one request.

## Wallet

`client.wallet()` covers the closed-loop wallet: end users, wallets and accounts, deposits, corporate accounts, fees, transfers, withdrawals, top-ups, merchant payments, QR codes and bulk payouts. Every call is signed. Fields may be passed as a mapping or as keyword arguments, in camelCase or snake_case.

```python
wallet = client.wallet()
user = wallet.end_users.create(
    program_id=program_id, account_type="PERSONAL", phone="+905550000000",
    idempotency_key=persisted_user_key,
)
started = wallet.transfers.initiate_w2w(
    end_user_id=user["endUserId"], source_wallet_account_id=account_id,
    destination_wallet_no="W123456", amount="12550", currency="TRY",
    idempotency_key=persisted_transfer_key,
)
wallet.transfers.complete_w2w(
    started["operationId"], end_user_id=user["endUserId"],
    integrity_hash=started["integrityHash"], nonce=started["nonce"], otp_code=otp,
    idempotency_key=persisted_complete_key,
)
```

Every call is checked against one route table, `WALLET_ROUTES`: an unknown field or filter, a missing required field, an amount that is not a minor-unit digit string (`"12550"`, never `125.5` or `12550`), or a missing `Idempotency-Key` on a route that requires one raises `ConfigurationError` before anything is sent. The `complete_*` calls put `operationId` into the body themselves. Lists return a `Page`; `iterate()` follows the cursor. `qr.image(qr_id, format="png", scale=4)` returns the image as `BinaryResponse`. Bulk payouts are maker-checker: the approving key must differ from the creating key.

## Bank accounts, transfers and currency exchange

`client.bank_connect()` reads your connected bank accounts (connections are set up in the dashboard). Every call is signed; the key's environment decides whether TEST or LIVE accounts are read.

```python
from datetime import datetime, timezone

bank = client.bank_connect()
page = bank.list_transactions(
    account_id=[account_id], booked_from=datetime(2026, 11, 1, tzinfo=timezone.utc),
    direction="CREDIT", min_amount_minor="10000", limit=50,
)
for transaction in bank.iterate_transactions(account_id=account_id):
    ...
```

Filters are checked locally: known names only, value sets (`BankConnectionStatus`, `BankTransactionDirection`, `BankTransactionType` …), `limit` 1–100, at most 100 account ids, canonical minor-unit amount strings with `min_amount_minor` ≤ `max_amount_minor`, `booked_to` only together with `booked_from`, and a window of at most 92 days. `request_sync(account_id)` asks for a fresh read; new transactions arrive by the `bank_account.transaction.received` webhook.

Outgoing transfers and currency exchange need the `bank-connect:transfer` scope and a key with an IP allowlist:

```python
transfer = bank.transfers.create(
    account_id=account_id, receiver_iban="TR330006100519786457841326",
    receiver_name="Test Receiver", amount_minor="150075",
    idempotency_key=persisted_payout_id,
)
quote = bank.fx.create_quote(
    source_account_id=try_account_id, target_account_id=usd_account_id,
    target_amount_minor="10000",
)
order = bank.fx.create_order(quote_id=quote["id"], idempotency_key=persisted_fx_key)
```

`create()` and `create_order()` check your `idempotency_key` (8–200 printable ASCII) or generate a UUID v4 when you leave it out; a network error or a 5xx is retried with the same key and body. Keep your own key to retry safely across processes. Webhooks: `BankConnectEvents` and `BankTransferEvents` (`bank_transfer.*`, not the `payment.bank_transfer.*` events of a payment); read a verified event with `BankAccountTransactionReceived.from_event(event)` or `BankTransferWebhookData.from_event(event)`.

## Sanctions screening

`client.sanction()` screens names, wallets, accounts and transactions, runs entity intelligence and ongoing monitoring. These calls use the access token (no request signature).

```python
from lunixi import is_clear_screening

result = client.sanction().screen_name(
    name="Test Person", subject_type="person", mode="sanctions_pep",
    customer_reference="customer-42",
)
if not is_clear_screening(result):
    hold_for_review()
```

Screening returns matches, not verdicts. `is_clear_screening()` is true only when there is no match or hit, no blocking flag or decision, and — where coverage is reported — `coverageStatus` is `COMPLETE`; a `PARTIAL` or `DEGRADED` screening is never clear. A screening that could not run raises (HTTP 503, or a 2xx answer whose `status` is not `success`); it never comes back as an empty result. Bodies and filters are checked against `SANCTION_ROUTES`: unknown or missing fields, an empty "at least one of" group, nested row fields and values outside `SANCTION_VALUE_SETS` raise `ConfigurationError`.

## Insurance

`client.insurance()` offers insurance for basket items, turns a quote into an order, follows its policies and documents, and submits leads for types sold by request only. Every call is signed.

```python
from datetime import datetime, timezone

from lunixi import InsuranceClient

insurance = client.insurance()
quote = insurance.create_quote(
    insurance_type="TICKET_CANCELLATION", currency="TRY", context={"items": basket_items},
)
option = quote["options"][0]
order = insurance.create_order(
    quote_id=option["quoteId"],
    consent=InsuranceClient.consent_from_quote(option, datetime.now(timezone.utc)),
    idempotency_key=persisted_order_key,
)
premium_item = InsuranceClient.premium_basket_item(order, name="Insurance", category1="Insurance")
```

The basket of a quote is either a payment's recorded basket (`payment_intent_id`) or the items you will send in the payment (`context`), never both; send neither for a type sold without a basket item. `create_order`, `confirm_payment`, `issue_policy`, `cancel_order`, `refund_premium` and `create_lead` require an `idempotency_key` of 8–200 printable ASCII characters; `create_quote` and `bind_payment` take one optionally. The type objects (`insured`, `tickets` …) are sent as given: the gateway validates them and answers 422 `insurance.validation.invalid` with every field error at once. Policy documents, receipts and certificates come back as `BinaryResponse` (PDF); `export_reconciliation(from_=..., to=...)` returns the CSV with `truncated`, `next_cursor` and `aborted`. Read verified webhooks with `InsuranceWebhookData.from_event(event)` (order events) and `InsuranceLeadWebhookData.from_event(event)` (lead events).

## Subscriptions

`client.subscriptions()` covers `/api/v1/subscriptions/*`: subscriptions plus the sub-clients `plans`, `customers`, `cards`, `invoices`, `portal`, `products`, `features`, `addons` and `usage`. Calls carry the access token (no request signature). Fields may be passed as a mapping or as keyword arguments, in camelCase or snake_case.

```python
from lunixi import SubscriptionCollectionMethod, is_subscription_active

subscriptions = client.subscriptions()
customer = subscriptions.customers.upsert(external_id="user-42", email="ada@example.com")
plan = subscriptions.plans.create(
    product_id="prod_1", code="pro-monthly", name="Pro", price="9900", currency="TRY",
    billing={"frequency": "MONTHLY", "interval": 1}, trial_period_days=14,
)
# The card comes from the checkout SDK's token; a card number is never sent.
card = subscriptions.cards.add(
    customer_id=customer["id"], payment_method_token="pm_tok_1", is_default=True,
)
subscription = subscriptions.create(
    customer_id=customer["id"], plan_id=plan["id"], payment_card_id=card["id"],
    collection_method=SubscriptionCollectionMethod.AUTO_CHARGE,
    idempotency_key="sub-user-42-pro",  # required: reuse it when retrying
)
if is_subscription_active(subscription):  # TRIALING, ACTIVE or PAST_DUE
    ...
subscriptions.change_plan(
    subscription["id"], new_plan_id="plan_team", behavior="NEXT_PERIOD",
    idempotency_key="chg-42-team",
)
subscriptions.cancel(subscription["id"], at_period_end=True, reason="customer request")
```

- `create()` requires an `idempotency_key` (or the request's `idempotencyKey`; both given, they must agree), sent in the header and the body. `plans.create`, `customers.upsert`, `cards.add`, `change_plan` and `invoices.retry_charge` accept one.
- Amounts (`price`, `priceSnapshotAmount`, `totalAmount`, `amountMinor` …) are minor-unit strings, checked in bodies, filters and answers (`"0"` is a free plan).
- Subscription, plan, customer, card and invoice lists return a `SubscriptionPage` (`next_page_token`, `page_size`); pass the token back as `page_token`, or use `iterate()`. Catalog, feature, add-on and portal-link lists return a `Page`.
- Customer portal: `portal.create_sdk_session(customer_id, origin, sdk_mode=...)` returns `portalToken`, `sessionProof`, `proofNonce` and `proofExpiresAt` for the browser portal SDK (`origin` must be allow-listed). `portal.create_portal_link()` returns a hosted link; `subscription_portal_url(link)` is the URL the customer opens. The link routes are under `/api/panel/v1/subscriptions/portal`, the only panel paths the client accepts.
- Webhooks: `SubscriptionEvents` (`subscription.*`, `invoice.*`, `card.*`), verified with `WebhookVerifier` like payment events.
- Every call is checked against `SUBSCRIPTION_ROUTES` before sending: an unknown field or filter, a missing one or an unknown value raises `ConfigurationError`.

## KYC and identity

`client.kyc()` creates and reads KYC, KYB and evidence sessions (`/api/v1/kyc/*`); `client.identity()` reads device and account-linking signals (`/api/v1/identity/*`). Both use the access token. The browser SDKs start with your publishable key; these clients are the server side.

```python
from lunixi import KycAssuranceDomain, KycSessionType, is_identity_device_shared, kyc_assurance_meets

created = client.kyc().create_session(
    subject_id="user-42", session_type=KycSessionType.KYC,
    external_customer_id="user-42",  # echoed on every kyc.* webhook
    jurisdiction="TR", idempotency_key="kyc-user-42-1",
)
# Hand created["session"]["sessionId"] to the browser SDK; the kyc.* webhook carries the result.

result = client.kyc().get_session(created["session"]["sessionId"])
achieved = (result.get("session") or {}).get("decision", {}).get("assuranceSnapshot", {}).get("achieved", {})
if kyc_assurance_meets(achieved.get(KycAssuranceDomain.IDENTITY), "SUBSTANTIAL"):
    ...  # identity gate passed

links = client.identity().account_links(trace_id_from_browser)
if is_identity_device_shared(links):
    ...  # a second account on this device: review
```

- `kyc().list_sessions()` takes only `limit` and `cursor` (`page_size` / `page_token` are read as the same); any other filter raises instead of silently returning every session. `iterate_sessions()` follows the cursor.
- `person` / `company` are sent as `customer` with `customerType`; `metadata` is sent as `evidenceContextJson`. `ttl_minutes` is 1 to 1440. A document image given to `upload_document()` never appears in an error message.
- No personal data comes back: status, decision, risk level and the achieved assurance per domain (`KycAssuranceDomain`). `kyc_assurance_meets(achieved, required)` compares on the ladder `NONE` / `NOT_PERFORMED` < `LOW` < `SUBSTANTIAL` < `HIGH`.
- `KycEvents` lists the `kyc.*`, `kyb.*`, `screening.*` and monitoring events. A rescreen or a screening match on an approved session must revoke access.
- Identity answers are signals (`riskFlags`, `reasonCodes`, probabilities, `identitySnapshot`), not an allow / review / block verdict; that is the fraud decision.

## Marketplace (sub-dealers)

`client.marketplace()` runs split charges across sub-dealers and manages the sub-dealers, commissions, payouts and the audit log. Split charges (`/api/v1/payments/marketplace/*`) are signed per request; the other routes (`/api/v1/marketplace/*`) use the access token.

```python
from lunixi import CreateIntent, MarketplaceMultiSellerPolicy, marketplace_onboarding_url

marketplace = client.marketplace()
dealer = marketplace.create_dealer(
    legal_name="Kurgu Ltd.", tax_id="1234567890", external_ref="vendor-7",
)
link = marketplace.onboarding_token(dealer["id"])
# Send the dealer to marketplace_onboarding_url(link): KYC, IBAN and contract, then ACTIVE.

intent = marketplace.create_checkout_intent(
    CreateIntent("100000", "TRY", "ORD-7", **order),  # order details as above
    [
        {"subDealerId": "d_alice", "amountMinor": "60000"},
        {"subDealerId": "d_bob", "amountMinor": "40000"},
    ],
    MarketplaceMultiSellerPolicy.ALL_OR_NOTHING,
    idempotency_key="mp-ORD-7",
)
```

- Seller legs are aggregate per sub-dealer (`{"subDealerId", "amountMinor", "scenario"?}`, positive minor-unit strings) and must add up to `amount`; the client checks the total before sending. `create_checkout_intent()` raises `ApiError` when the answer carries no token or form (for example a seller that is not eligible under `ALL_OR_NOTHING`). It uses the same route as `payments().create_marketplace_intent()`.
- Direct split card charges (`charge_marketplace_card2d` / `charge_marketplace_card3d`) need the card, buyer, billing address and basket items; they are PCI DSS SAQ-D scope. Card data is sent as given and never logged or put in an error message.
- Only `ACTIVE` dealers receive a split (`MarketplaceDealerStatus`). Dealer lists, the payout ledger, transactions, commission rules and the audit log return a `Page`.
- `resolve_commission(sub_dealer_id, category_code=..., mtd_volume_minor=...)` and `preview_commission_rule(rule)` read the effective commission; payout amounts (`amountMinor`) are minor-unit strings, checked in bodies, filters and answers.

## Durable native checkout

`lunixi.commerce.CheckoutService` persists an immutable merchant/order/amount/currency snapshot and a stable attempt key **before** network I/O. It encrypts persisted browser tokens with a separate 32-byte server key. A native adapter supplies the transaction store and an idempotent native order callback using that **same connection/transaction**.

```python
from lunixi.commerce import CheckoutService, SqliteLedgerStore, SecretBox, OrderSnapshot

ledger = SqliteLedgerStore("/secure/state/commerce.sqlite3")
ledger.install()  # explicit schema setup, outside request handling
service = CheckoutService(client, ledger, SecretBox(server_encryption_key_bytes))
session = service.start(
    "order-123", OrderSnapshot(merchant_id, "order-123", "1990", "TRY"),
    "https://shop.example/return/order-123", hosted=False,
)
# `apply_native` validates current native totals/holds and writes using tx.connection.
decision = service.reconcile("order-123", apply_native)
```

The runnable [framework integrations](docs/FRAMEWORKS.md) implement real order, stock, inbox and native outbox writes; a no-op callback is not a fulfillment implementation. Native fraud/manual holds remain effective after capture. Changed native totals/currency cannot be completed by an older intent. Buyer installment fees require the persisted fingerprint and stay separate from the basket; split success requires complete, balanced parent evidence with no compensation/reconciliation requirement. Partial capture is on hold.

Browser query parameters/form events never mark paid. `service.webhook(raw_bytes, headers, secret, apply_native)` verifies raw-body v2 HMAC/freshness/signed id/type, then queries authenticated payment/split evidence. Payment GET's `data.id`, create result `paymentId` and webhook `data.intentId` identify the same payment. Durable row locking and unique event hashes commit with native writes; a failed callback rolls back both. Signed event-ID content collisions fail. Lost create responses recover only from a verified payment webhook plus authenticated GET echoing the original opaque reservation hash/fingerprint; an existing payment ID is never rebound.

`service.mutate(order_key, persisted_operation_id, 'capture'|'refund'|'void', amount_or_none, apply_native)` reserves a durable operation and stable gateway key. `operation_status(...)` returns `pending`, `uncertain` or `confirmed` without exposing the key. New IDs are blocked while a prior operation is unresolved. Only authenticated balances/releases confirm success; refunds cannot exceed captured funds. Retry the exact original operation ID/amount after a timeout. Unconfirmed create/mutation retries older than 23 hours are blocked before POST, since gateway key retention is finite. GET reconciliation remains available. `FAILED` without outcome certainty stays review; this version provides no automatic ambiguous-attempt reset.

## Authentication, transport and JSON

Generate Ed25519 keys with `generate_key_pair()` and register only the public key. The SDK accepts PKCS8 PEM/DER, base64/hex seeds and validated 64-byte seed/public exports. `cryptography` provides curve/AES-GCM primitives. Keep one client per origin/merchant key; token refresh coalesces concurrent threads. A custom `TokenStore` must be explicitly scoped to that origin/key. Cache lifetime respects expiration/skew; credentials do not appear in config representations.

HTTPS origins cannot contain credentials, path prefixes, query or fragment. API paths remain under `/api/v1/` without traversal or normalization escapes. Redirects are not followed, including authentication redirects. Defaults:30 seconds/request,8MiB response cap,2 extra retries; timeout is bounded to 120 seconds and retries to5. Writes retry only with a nonempty stable key, including a401 refresh. Signing uses exact compact UTF-8 JSON, JavaScript numeric-key ordering and RFC8785 ECMAScript scalar formatting; unsafe integers/non-finite numbers fail locally. An explicit numeric-loopback HTTP opt-in exists for transport tests; Commerce always requires HTTPS.

## Existing fraud API

```python
from lunixi import Channel
result = client.fraud().evaluate(
    channel=Channel.STANDALONE_API,
    transaction_ref="persisted-order-123",
    payment={"amount":"1990","currency":"TRY"},
)
if result.blocked:
    refuse_order()
elif result.requires_review or result.requires_three_d:
    hold_for_review_or_three_ds()
```

Fraud evaluate, decision-log list/get and event record/batch APIs retain their names/results. Decision/log calls remain bearer-authenticated; event ingest is signed per request. Batch ingestion supports up to 500 events and may partially succeed; inspect `result.failures()` and resend failed events with the same event IDs. `Page` preserves top-level cursor metadata; iterate using the returned cursor. No internal console route is a supported merchant API.

## Other documented services and errors

```python
response = client.api().request(
    "GET", "/api/v1/payments/methods", step_up=True,
)  # same as client.payments().list_payment_methods()
```

The generic authenticated layer can reach other documented merchant services with explicit `step_up=True` when required; `client.api().request_binary("GET", path, step_up=True)` returns a file answer as `BinaryResponse`. Browser form submission belongs to the official bundle.

Catch `LunixiError` or typed `ApiError`/`ValidationError`/`AuthenticationError`/`RateLimitError`/`ServiceUnavailableError`. Status, machine code, request ID and quota metadata remain available; raw remote error messages/bodies and transport exception text are withheld. Do not log raw successful responses either: they can carry browser tokens/customer data.

Low-level `WebhookVerifier` verifies signatures but does not claim replay IDs. Default signed id/type binding is strict. `allow_legacy_header_fields=True` preserves the old nonfinancial fallback explicitly and produces no financial replay proof; never use it for order fulfillment. `tolerance_seconds=None` is an explicit offline-fixture option, not a live setting. A secret list supports rotation; retain old endpoint secrets through the grace window.

## Verify and build

```sh
pip install -r requirements-dev.lock
pip install --no-deps -e .
ruff check src integrations tests
ruff format --check src integrations tests
mypy src/lunixi
bandit -r src/lunixi integrations -q
pip-audit
pytest -q
python -m build
```

The lock targets the verified Python 3.12 development environment. Core CI also exercises Python 3.9/3.10/3.14; framework tests run on 3.12. Native tests use real framework clients/users/CSRF/ORM/databases and synthetic external gateway transport. The HTTPS transport fixture binds only loopback. No live charge, external email or automatic shipment occurs in tests. Wheel contains the typed SDK; sdist/source also contains runnable apps, tests, original logos and EN/TR guides.

MIT · [Security](SECURITY.md) · [Contribution guide](CONTRIBUTING.md) · [Changelog](CHANGELOG.md).

## Embedded default and optional backend payment page

The framework examples default to `LUNIXI_CHECKOUT_MODE=embedded`: the existing form mounts on the merchant website using only `https://cdn.lunixi.com/lunixi-checkout.min.js` and the official object/token/mount API. Explicit `hosted` remains supported. `IntentResult.payment_page_url` reads the optional backend `paymentPageUrl`; `hosted_url` validates and returns that exact URL, whose opaque page token can differ from the embedded token. Missing/invalid URLs fail closed; no URL is built from the browser token.

The shared form owns enabled methods, multi-card, installments and insurance in either mode; none requires a redirect. Persisted tokens and page URLs are encrypted with distinct authenticated contexts. The original callback/mode/body/hash/key remain bound to an existing attempt: changing configuration does not create a replacement charge. An older hosted record without a backend URL requires reconciliation. Strict raw webhooks, owner/session/CSRF checks, authenticated settlement and informational 3DS/split returns remain required.

Historical 0.2.1 focused checks: 27 SDK/native Django/FastAPI/Flask cases passed; prior full 0.2.0 verification remains the baseline. No live merchant charge or broad new merchant acceptance was run.

Before upgrading from 0.x, follow [the money-string migration](MIGRATION-1.0.md).
