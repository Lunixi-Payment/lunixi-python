# Changelog

## 1.5.1 — 2026-11-15

- Formatting (`ruff format`) and type annotations (`mypy`) of the 1.5.0 sources; no behaviour change.

## 1.5.0 — 2026-11-15

- Payment method constants: `PaymentMethod` (15 codes, `QR` accepted as `QR_CODE`), `PaymentActionType`, `ProviderSelection`, `ProviderSelectionMode`, `MethodInputFieldType`, and the field lists `DIRECT_METHOD_PAYMENT_FIELDS`, `METHOD_BLOCK_FIELDS`, `CARD_ONLY_FIELDS`, `PAYMENT_ACTION_CONFIRM_FIELDS`, `SHOPPING_LOAN_MAX_BASKET_ITEMS` (100); helpers `normalize_payment_method()` and `block_name_of()`.
- `payments().list_payment_methods(payment_method=None)` (`GET /payments/methods`, signed): optional `?paymentMethod=` filter, `QR` sent as `QR_CODE`, an invalid code raises `ConfigurationError`. `methods()` accepts the same optional argument and keeps working without it.
- `payments().direct_method_payment(request, *, idempotency_key)` (`POST /payments/direct/payment`, signed, key required) with the `DirectMethodPaymentRequest` builder (`with_method_fields`, `with_card`, `with_force3d`, `with_installment`, `with_promissory_note_schedule`, `with_promissory_note_count`, `with_preauth`, `with_callback_url`, `with_locale`, `with_description`, `with_customer_id`, `with_payment_channel`, `with_payment_group`, `with_buyer`, `with_billing_address`, `with_shipping_address`, `with_basket_items`, `with_metadata`). The builder and a raw body mapping are checked before sending: known fields only, no `price`/`paidPrice`, exactly the chosen method's block, card fields only with `CARD`, block shape (≤ 32 fields, `ADDRESS` ≤ 16 fields, `GROUP` ≤ 10 objects, strings ≤ 1024 characters, provider code pattern), shopping-loan basket of 1–100 items, promissory-note plan, boolean `preauth`/`force3D`.
- Para Transferi (`BANK_TRANSFER`): `bankTransfer: {"bankCode"}` block without a provider code (refused locally in the builder and in a raw body), `BANK_TRANSFER_OTHER_BANKS_CODE` (`"9999"`), `BankTransferInstruction.from_response()` reads the `DISPLAY` instruction (`data.action.bankTransfer`; `None` without one). Exceptions: `list_bank_transfer_exceptions(environment=, status=, limit=)` (`TEST`/`LIVE`, `PaymentBankTransferExceptionStatus`, 1–200; unset filters are not sent), `accept_bank_transfer_exception(id)` and `mark_bank_transfer_exception_refunded(id)` (UUID checked locally), all signed. Constants `PaymentBankTransferExceptionKind`, `PaymentBankTransferExceptionStatus`, `BANK_TRANSFER_EXCEPTION_LIMIT_MAX` and the webhook events `PaymentBankTransferEvents` (`payment.bank_transfer.partially_received|underpaid|overpaid|late_arrival`).
- Payment actions: `confirm_payment_action(payment_id, action_id, *, otp=None, consent_accepted=None, fields=None)` and `resend_payment_action(payment_id, action_id)` (signed). Only `otp` (digits, 1–16), `consent_accepted` (boolean) and `fields` (block shape rules) are sent; any other keyword, such as a checkout token, raises `ConfigurationError`.
- Promissory notes: plan rules (`schedule` of 1–24 `{amount, dueDate}` rows adding up to `amount`, calendar dates in ascending order, or `noteCount` 1–24 sent as a string; never both), `get_promissory_notes()`, `cancel_promissory_notes(payment_id, serial_numbers=None)` (1–24 serial numbers) and `download_promissory_note_document(payment_id, locale=None)` (`tr-TR`/`en-GB`) returning the PDF as `BinaryResponse`, all signed. Constants `PromissoryNoteStatus`, `PromissoryNoteDocumentType`, `PromissoryNoteCancelResult`, `PromissoryNoteCancelErrorCode`, `PromissoryNoteDocumentLocale`, `PromissoryNoteEvents` (`payment.promissory_note.paid|protested|cancelled`).
- Split payments: `create_split_payment(request, *, idempotency_key)` (`POST /payments/split`, signed, key of at most 200 characters) with the `SplitPaymentRequest` builder (`add_card_leg`, `add_method_leg`). A running split payment (HTTP 400 with a running status as `code` and `data.splitPaymentId`) is returned as the result. Legs are checked locally: a non-card leg carries only `mobileBilling`, `wallet` or `promissoryNote` (`SPLIT_LEG_BLOCK_FIELDS`) with its provider code; meal card, open banking, shopping loan and bank transfer cannot be legs. `list_splits()` now checks its filters (`LIST_SPLIT_PAYMENTS_FILTERS`; `status`/`currency` lists are sent as repeated parameters). Constants `SplitPaymentStatus`, `SPLIT_PAYMENT_IN_PROGRESS_STATUSES`, `SplitPendingStep`, `SplitPaymentEvents` (`payment.split.*`) and `SPLIT_LEG_EVENTS_SUBSCRIPTION` (`payment.split.leg_events`).
- `client.reference()`: Türkiye address dictionary for `ADDRESS` fields — `list_provinces()`, `list_districts(province_code)` (`01`–`81`), `list_neighborhoods(district_code)` (digits).
- Card lookups on `client.payments()`: `bin_info(bin_or_pan)` (`POST /bin/info`), `installment_options(InstallmentOptionsRequest(...) | mapping)` (`POST /bin/installments`; `enabled_installments` / a raw `enabledInstallments` follow the intent rule and are sent in ascending order) and `card_taxonomy()` (`GET /bin/card-taxonomy`), all with the access token. A BIN or card number is digits only (6–19) and never appears in an error message or a `repr`.
- Stored cards: `store_card(StoreCardRequest(card, card_user_key, callback_url), idempotency_key=...)` (`POST /payments/cards`, signed) and `deactivate_stored_card(stored_card_token, idempotency_key=...)` (`DELETE /payments/cards/{token}`, signed); both refuse a missing key before sending. `list_stored_cards(card_user_key)` and `get_stored_card(stored_card_token)` read with the access token.
- `create_marketplace_intent(CreateIntent(...) | mapping, sellers=[...], multi_seller_policy=None, idempotency_key=None)` (`POST /payments/marketplace/intents`, signed). Each seller is `{"subDealerId", "amountMinor", "scenario"?}` with `amountMinor` a canonical minor-unit string; the sellers must add up to `amount`, otherwise `ConfigurationError` is raised and nothing is sent. Constants `MultiSellerPolicy` (`ALL_OR_NOTHING`, `PARTIAL_ALLOWED`).
- Analytics: `failover_recovery_analytics(**filters)` and `provider_credential_analytics(credential_id, **filters)` (`GET /payments/analytics/...`).
- `client.payment_links()` (`/api/v1/payments/links`, every call signed): `create(request, idempotency_key=...)` (key of 8–200 printable ASCII characters, required), `list(**filters)` / `iterate()`, `get()`, `update(link_id, expected_row_version, changes)` (`usage`, `amountMode`, `currency` cannot change), `pause()`, `resume()`, `deactivate()`, `action()`, `send(link_id, channel=..., idempotency_key=...)` (key required), `qr(link_id, format="svg"|"png", size=None)` (image bytes as `BinaryResponse`), `list_attempts()` / `iterate_attempts()` and `list_payments()` / `iterate_payments()` (`Page`). Builders `CreatePaymentLinkRequest` (`fixed()`, `open()`, `itemized()`), `PaymentLinkItem`, `PaymentLinkCustomField`; constants `PaymentLinkUsage`, `PaymentLinkAmountMode`, `PaymentLinkState`, `PaymentLinkAttemptState`, `PaymentLinkEnvironment`, `BuyerFieldRequirement`, `CustomFieldType`, `PaymentLinkButtonLabel`, `PaymentLinkDeliveryChannel`, `PaymentLinkQrFormat`, `PaymentLinkLocale`, `PaymentLinkImageContentType` and the field list `PAYMENT_LINK_SPEC_FIELDS`. Unknown body fields and list filters raise `ConfigurationError`.
- Link images: `create_image_upload(file_name=, content_type=, size_bytes=)`, `confirm_image_upload(asset_id)` and `upload_image(file_name=, content_type=, content=)`, which runs both plus the PUT of the bytes to the presigned `uploadUrl`. The PUT goes through the configured transport straight to the storage host with only the returned `uploadHeaders`: no access token, no signature headers. `HttpTransport.send()` receives `bytes` as `body` for that request only; a custom transport must send them as they are.
- `validate_enabled_installments()` moved to `lunixi.payments.enabled_installments`; `lunixi.payments.validate_enabled_installments` keeps working.
- `ApiClient.request_binary()` returns a 2xx file answer as `BinaryResponse` (`content_type`, `content`) with the same signing, retries, size limit and JSON error mapping; `ApiClient.request()` takes an optional `result_on_error` predicate for a route whose documented non-2xx answer is a result.
- `client.wallet()` (`/api/v1/wallet/*`, every call signed): sub-clients `programs`, `end_users`, `wallets`, `deposits`, `corporate`, `fees`, `transfers` (`quote_w2w`, `initiate_w2w`, `complete_w2w`, `quote_w2_iban`, `initiate_w2_iban`, `complete_w2_iban`), `withdrawals`, `operations`, `topups`, `payments`, `qr` and `bulk_payouts`, plus `ping()`. Every call is checked against one route table, `WALLET_ROUTES` (method, path, `Idempotency-Key` rule, body and query fields, nested rows): an unknown field or filter, a missing required field, an amount that is not a minor-unit digit string, or a missing `Idempotency-Key` on a keyed route raises `ConfigurationError` before sending. Complete calls put `operationId` into the body themselves. `qr.image()` returns the SVG/PNG as `BinaryResponse`; lists return a `Page` and `iterate()` follows the cursor. Value sets `WalletAccountType`, `WalletEndUserStatus`, `WalletKycLevel`, `WalletOtpChannel`, `WalletQrType`, `WalletQrImageFormat`, `WalletBulkTargetType`, `WalletCorporateAccountStatus`.
- `client.bank_connect()` (`/api/v1/bank-connect`, every call signed): `list_banks()`, `list_connections()` / `get_connection()`, `list_accounts()` / `get_account()`, `request_sync()`, `list_balances()`, `list_transactions()` / `get_transaction()` and an `iterate_…()` for every list. Filters follow `BANK_CONNECT_FILTERS` and are checked locally: value sets, `limit` 1–100, at most 100 account ids, canonical minor-unit amounts with `minAmountMinor` ≤ `maxAmountMinor`, `bookedTo` only with `bookedFrom`, at most 92 days.
- Bank transfers and currency exchange: `bank_connect().transfers` (`list_purposes`, `create`, `list` / `iterate`, `get`) and `bank_connect().fx` (`list_rates`, `create_quote`, `create_order`, `list_orders` / `iterate_orders`, `get_order`), checked against `BANK_TRANSFER_ROUTES`. `create()` and `create_order()` check a given `idempotency_key` (8–200 printable ASCII) or generate a UUID v4, and a network error or 5xx is retried with the same key and body. A quote takes exactly one of `sourceAmountMinor` / `targetAmountMinor` and two different accounts.
- Bank-connect webhooks: `BankConnectEvents` (`bank_account.transaction.received`) and `BankTransferEvents` (`bank_transfer.created|completed|failed|returned`, not the `payment.bank_transfer.*` events of a payment), with the readers `BankAccountTransactionReceived.from_event()` and `BankTransferWebhookData.from_event()` for a verified `WebhookEvent`.
- `client.sanction()` (`/api/v1/sanction/*`, access token, no request signature): `screen_name`, `screen_wallet`, `screen_account`, `screen_transaction`, `screen_public_procurement_ban`, `screen_adverse_media`, `evaluate_behavioral_alert`, `list_screening_history`, `register_monitoring` (a `profile` mapping is sent as `profileJson`), `list_monitoring_alerts`, `list_monitored_entities`, `list_monitoring_matches`, `get_dataset_freshness`, `search_entities`, `get_entity_profile`, `get_entity_graph`, `get_indirect_exposure`, `get_ownership_aggregation`, `list_blacklist_entries`, and `iterate_…()` for the lists. Bodies and filters are checked against `SANCTION_ROUTES`, `SANCTION_NESTED_FIELDS` and `SANCTION_VALUE_SETS` (unknown or missing field, empty `anyOf` group, nested row fields, risk domain / mode outside its set). A 2xx answer whose `status` is not `success` raises `ApiError`. `is_clear_screening(result)` is the clean-read rule: no match or hit, no blocking flag or decision, and `coverageStatus` `COMPLETE` where coverage is reported.
- `client.insurance()` (`/api/v1/insurance`, every call signed): `list_products`, `search_products`, `list_reference_values`, `create_quote` / `get_quote`, `create_order` / `list_orders` / `get_order`, `bind_payment`, `confirm_payment`, `issue_policy`, `cancel_order`, `refund_premium`, `create_lead` / `list_leads` / `get_lead`, `get_policy_document`, `get_policy_receipt`, `get_policy_certificate` (PDF as `BinaryResponse`), `get_reconciliation_summary`, `list_reconciliation_orders`, `export_reconciliation` (CSV as `InsuranceReconciliationExport` with `truncated`, `next_cursor`, `aborted`) and `iterate_…()` for the lists. `create_order`, `confirm_payment`, `issue_policy`, `cancel_order`, `refund_premium` and `create_lead` require an `idempotency_key` matching `^[\x21-\x7E]{8,200}$`; `create_quote` and `bind_payment` take one optionally. A quote with both `paymentIntentId` and `context.items` raises `ConfigurationError`. The type objects are sent as given (their rules live on the gateway). Helpers `InsuranceClient.consent_from_quote()` and `InsuranceClient.premium_basket_item()`; value sets and field lists as in the shared catalog; webhooks `InsuranceEvents` with the readers `InsuranceWebhookData.from_event()` and `InsuranceLeadWebhookData.from_event()`.
- Request fields and filters of these four clients may be given as a mapping or as keyword arguments, in camelCase or snake_case (`from_` for the reconciliation `from` filter).
- `client.subscriptions()` (`/api/v1/subscriptions/*`, access token, no request signature): `create` (`idempotency_key` required, also sent in the body; a request `idempotencyKey` that differs raises), `get`, `list` / `iterate`, `cancel`, `pause`, `resume`, `change_plan`, `audit_logs` / `iterate_audit_logs`, and the sub-clients `plans`, `customers`, `cards`, `invoices`, `portal` (`create_sdk_session` reads the proof at the envelope root; `create_portal_link`, `list_links`, `get_link`, `update_link`, `revoke_link`, `link_activity`, `send_invite`, `get_settings`, `update_settings`), `products`, `features`, `addons` and `usage`. Subscription, plan, customer, card and invoice lists return `SubscriptionPage` (`next_page_token`, `page_size`) and their `iterate()` follows `pageToken`. Plan bodies are checked locally (supported currency, billing rule fields and frequency, counts); `cards.add` refuses card numbers by field name. Constants `SubscriptionStatus`, `SubscriptionInvoiceStatus`, `SubscriptionCollectionMethod`, `SubscriptionBillingFrequency`, `SubscriptionCardVerificationMode`, `SubscriptionPlanChangeBehavior`, `SubscriptionPortalSdkMode`, `SubscriptionEvents`, `SUBSCRIPTION_ACTIVE_STATES`, `SUBSCRIPTION_TERMINAL_STATES`, `SUBSCRIPTION_BILLING_RULE_FIELDS`, the route table `SUBSCRIPTION_ROUTES`; helpers `is_subscription_active()`, `is_subscription_terminal()`, `subscription_portal_url()`.
- The portal-link routes live under `/api/panel/v1/subscriptions/portal/`; that prefix is now accepted as a gateway path (with the same traversal checks). Every other `/api/panel/` path is still refused before anything is sent.
- `client.kyc()` (`/api/v1/kyc/*`, access token): `create_session`, `get_session`, `list_sessions` (only `limit` / `cursor`; `page_size` / `page_token` read as the same; any other filter raises) / `iterate_sessions`, `set_jurisdiction`, `set_primary_document`, `upload_document` (the image never appears in an error message), `timeline`, `submit`, `manual_review`, `evidence_request`, `merchant_policy`, `update_merchant_policy`, `rotate_webhook_secret`, `webhook_outbox`, `retry_webhook_event`, `erasure_requests`. `person` / `company` are sent as `customer` with `customerType`, `metadata` as `evidenceContextJson`; `ttlMinutes` is 1–1440. Constants `KycSessionType`, `KycSessionStatus`, `KycEvidencePurpose`, `KycAssuranceLevel`, `KycAssuranceDomain`, `KycEvents`, `KYC_SESSION_TERMINAL_STATES`, `KYC_ROUTES`; helpers `is_kyc_session_terminal()`, `kyc_assurance_rank()`, `kyc_assurance_meets()`.
- `client.identity()` (`/api/v1/identity/*`, access token): `analyze_sync`, `analyze`, `account_links`, `get_session`, `related_sessions`, `timeline`, `top_sources`, `list_sessions`; `IDENTITY_ANALYZE_FIELDS`, `IDENTITY_ROUTES`; helpers `is_identity_device_shared()`, `identity_link_reasons()`.
- `client.marketplace()`: signed split charges `create_checkout_intent` (raises `ApiError` when the answer has no token or form), `charge_marketplace_card`, `charge_marketplace_card2d`, `charge_marketplace_card3d` (seller legs checked and their total compared with `amount` before sending; card data never in an error message), and the bearer-only routes `create_dealer`, `bulk_create_dealers`, `list_dealers`, `get_dealer`, `update_dealer_status`, `onboarding_token`, `dealer_application`, `submit_dealer_application`, `set_dealer_terms`, `sign_dealer_contract`, `activate_dealer`, `record_dealer_kyc_result`, `payout_ledger`, `transactions`, `commission_rules`, `upsert_commission_rule`, `preview_commission_rule`, `resolve_commission`, `create_payout`, `mark_payout_paid`, `bulk_mark_payouts_paid`, `audit_log`, `verify_audit_log`. Constants `MarketplaceDealerStatus`, `MarketplaceDealerType`, `MarketplaceMultiSellerPolicy`, `MARKETPLACE_SELLER_FIELDS`, `MARKETPLACE_CHARGE_REQUIRED_FIELDS`, `MARKETPLACE_ROUTES`; helper `marketplace_onboarding_url()`.
- Subscription and marketplace bodies, filters and answers are checked with `lunixi.validation.validate_wire_money()`: every money member of those contracts is a canonical minor-unit string (`"0"` allowed; signed only for balances); the error names the member, never its value.
- The four route tables share one caller, `lunixi._routes.send_route()` (method, path, signing, `Idempotency-Key` rule `required` / `optional` / `none`, body field lists or free bodies, query lists); fields and filters may be given as a mapping or as keyword arguments, in camelCase or snake_case. `paginate()` takes the cursor parameter name.

## 1.4.0 — 2026-11-12

- `lunixi.ProductCategory` (also `lunixi.payments.ProductCategory`): the 40 Lunixi product category codes for the optional `basketItems[].productCategory` field as string constants (e.g. `ProductCategory.MOBILE_PHONE`) and the `ProductCategory.ALL` tuple in dictionary order. Used by payment methods with legal installment limits (e.g. shopping loan) and other platform features; the gateway answers an unknown code with 400. The list only grows by appending; values are not checked against it before sending. `CreateIntent` is unchanged (it does not build basket items).

## 1.3.1 — 2026-11-04

- Packaging-only release of 1.3.0 (test formatting). No API change.

## 1.3.0 — 2026-11-04

- `CreateIntent(enabled_installments=[...])` sends `enabledInstallments`: the installment counts the hosted form may offer for one payment (`[1]` = single payment only). It only narrows your panel settings, the card and the platform maximum; `None` means no restriction. The list is checked before any request (integers 1–36, no duplicates, 1 included; `ConfigurationError` otherwise) and sent in ascending order. Helper: `lunixi.payments.validate_enabled_installments()`.

## 1.2.0 — 2026-11-03

- Physical POS end-of-day webhooks: `PhysicalPosEvents.SETTLEMENT_COMPLETED`, `SETTLEMENT_FAILED`, `SETTLEMENT_OVERDUE`, `SETTLEMENT_SKIPPED` are in `PHYSICAL_POS_EVENT_TYPES`; `parse_webhook_event()` reads them with `category == "settlement"` (no `history_seq`; deduplicate by `id`). New helper `webhook_category()`.
- Physical POS payment webhooks: `PhysicalPosWebhookEvent.cashier` is the optional `{"cashierId", "cashierCode"}` of a payment started from a device cashier session (`None` otherwise; the key is absent then). New helper `webhook_cashier()`.
- Physical POS end-of-day on `client.physical_pos()`: `start_settlement(device_id, *, idempotency_key=None)` (`POST /devices/{deviceId}/settlement`, `physical_pos:payments`; empty JSON body, `Idempotency-Key` sent — generated when `None`; `PhysicalPosWriteResult` with `result["run"]`, 202 new / 200 replay), `list_settlement_runs()` / `iterate_settlement_runs()` (`GET /settlement-runs`; filters `device_id`, `source`, `run_status`, `created_from`, `created_to`, `include_total`) and `get_settlement_run(run_id)`.
- Physical POS end-of-day policy on `client.physical_pos_management()`: `get_…`, `set_…` and `clear_…_settlement_policy()` for the account, a store and a device (`GET` / `PUT` / `DELETE …/settlement-policy`; `clear_…` takes an optional keyword `expected_row_version`, sent as a query parameter) and `get_effective_settlement_policy(device_id)`.
- Physical POS terminal payment-provider rows on `client.physical_pos_management()`: `list_terminal_providers()` / `iterate_terminal_providers()`, `add_terminal_provider()` (`Idempotency-Key`; 201 / 200) and `update_terminal_provider()` (`PATCH /terminal-providers/{terminalProviderId}`).
- `create_payment()` accepts `interaction` (`INSTRUMENT_READ` | `CODE_DISPLAY`) and `terminal_provider_id` for provider-collected cards such as `instrument="MEAL_CARD"`.

## 1.1.0 — 2026-11-03

- Physical POS device identity on `client.physical_pos_management()`: `list_device_keys()` / `iterate_device_keys()` (`GET /devices/{deviceId}/keys`, `physical_pos:view`), `revoke_device_key()`, `revert_device_enrollment()` and `revoke_activation_code()` (`physical_pos:identity`; no `Idempotency-Key`). Key ids are `pdk_…`, not UUIDs. Activation codes are not issued with an API key (panel only).

## 1.0.2 — 2026-11-01

- Preserve an unknown physical POS payment outcome and its original operation key when deeply nested post-send responses exceed recursive validation limits.
- Add parser-independent decoded-response regressions; retain the existing deeply nested wire-response case and strict numeric-money rejection.
- Require successful CI for the exact tagged commit before a PyPI publication; use concise diagnostic tracebacks without suppressing failures.

## 1.0.1 — 2026-11-01

- Remove unused imports, normalize import ordering and format the money/Physical POS changes for release CI without changing strict numeric/null rejection.
- Keep the Physical POS outcome invariant enforced when Python assertions are disabled, and include the 1.0 migration guide in the source distribution.
- Update installation and exact-tag publishing guidance for the correction release.

## 1.0.0 — 2026-11-01

- Physical POS payment/item/filter/report money uses canonical signed64 strings; raw numeric/null amounts are rejected before HTTP, malformed monetary 2xx payment replies retain UNKNOWN semantics, and signed webhooks are checked after signature verification.

- Reject explicit null capture/refund amounts; full remaining operations use omission or the dedicated API described in MIGRATION-1.0.md.

- Breaking: public money request/response fields require canonical minor-unit strings; JSON numbers are rejected.
- Exact signed 64-bit fiat arithmetic and currency-aware decimal text conversion preserve values above JavaScript’s safe-integer limit.
- See [MIGRATION-1.0.md](MIGRATION-1.0.md) before upgrading.


### Physical POS additions

- Physical POS (`client.physical_pos()`): start, read, list, cancel and reverse in-store device payments (void, refund by amount or by item, pre-authorisation close/cancel); transaction trees and the ambiguous-outcome queue; sales and tax summaries; end-of-day settlement lines. Cursor iterators for every list.
- Physical POS management (`client.physical_pos_management()`): overview, catalog (vendors, device models, acquirers), stores and registers, logical terminals with bank rows and device links, devices with assignment, lifecycle and retirement, audit lists.
- `create_payment` and `create_reversal` require `idempotency_key` (keyword-only; `None` is refused before sending). Create it with `PhysicalPosClient.new_idempotency_key()`, store it with your order, then call; after an unknown outcome call again with the SAME key. `cancel_payment` and the keyed management writes generate a UUID v4 when the key is `None`. A given key is sent exactly as given: empty, blank or padded keys are refused, never trimmed or replaced.
- Payment writes run one attempt loop with the same key and body (the transport's own retries are off for these calls): only a 2xx with a usable `payment` is a success; no answer, a body that cannot be read, a non-JSON or payment-less 2xx and a 5xx without a "not started" code (`PHYSICAL_POS_NOT_STARTED_CODES`) are uncertain. Once an attempt was uncertain the call ends with `PhysicalPosOutcomeUnknownError` (with the key and the last error as cause), whatever the last answer was — a later 429 or 409 included. Payment writes report `status_code` 202 (accepted) or 200 (replay / cancel).
- Card numbers in values are refused before sending (`contains_pan_like_value`, the gateway rule: standalone 13–19 digits, plain or space/dash separated, Luhn valid): `merchant_reference`, item `name` (a 13/14 digit barcode is allowed) and `tax_group_code`, and the `merchant_reference` / `q` filters. Only the field path is reported.
- Filters: `date_from` / `date_to` take a `datetime.date` (sent as that calendar day, `YYYY-MM-DD`, not converted to Europe/Istanbul); `created_from` / `created_to` take an aware `datetime` (sent as ISO-8601 UTC). `None` and `""` are not sent, in bodies and filters; an empty required field is refused.
- `ApiClient.request()` gains an optional per-call `max_retries` (default unchanged) and `ApiClient.max_retries`.
- Typed errors: `PhysicalPosCardDataRejectedError` (also raised before sending when a request or filter key looks like card data — the API takes no card data), `PhysicalPosRateLimitError` (`retry_after` from `Retry-After` or `details.retryAfterSeconds`), `PhysicalPosOutcomeUnknownError` (no definite answer to a payment write — retry with the same key). `ApiError` gains `details` (field path, reason and retry hints only) and `idempotency_key`.
- Webhooks: `PhysicalPosEvents`, `PHYSICAL_POS_EVENT_TYPES`, `parse_webhook_event(raw_body, headers, secret_or_verifier)` verifies the signature with `WebhookVerifier` itself and then reads the `physical_pos.*` event from `data` or `payloadJson`; there is no path for an unverified or pre-decoded envelope. A too deeply nested `payloadJson` is a `WebhookVerificationError`.
- Sales made directly on the device: `PhysicalPosEvents.PAYMENT_DEVICE_SALE` (`physical_pos.payment.device_sale`, in `PHYSICAL_POS_EVENT_TYPES`). The parsed event gains `is_device_sale` and `original` (the reversal's original payment `{"paymentId", "origin"}`, `None` on a root; `origin` `API` or `DEVICE_DIRECT`).
- `PhysicalPosVoidAfterSettlementError` (409 `physical_pos.payment.void_after_settlement`, `allowed_operation`): a payment in a device end-of-day can no longer be voided; refund it instead. `ApiError.details` also keeps `allowedOperation`.
- `get_device()` documents `presence` (connection state, readiness for payment, `notReadyReason`); `list_settlements()` documents `settlementRef`, `acquirerRefRaw`, `acquirerName`, `deviceName` (`commandId` is `None` for an end-of-day started on the device). The acquirer catalog no longer lists `providerCode`.

## 0.2.1 — 2026-10-31

- Default Django, FastAPI and Flask examples to the existing on-site Lunixi form; retain explicit hosted mode.
- Read and strictly validate the backend `paymentPageUrl` independently of the embedded browser token; never derive a hosted URL from the token.
- Persist the optional URL encrypted with a field-specific context, validate it on cache reads, and preserve legacy request hashes/keys without unsafe retries or token-URL fallbacks.
- Preserve nonce CSP while allowing exact operator-approved HTTPS form-action origins for provider/legacy POSTs; reject unsafe origin configuration before use.


## 0.2.0 —2026-10-31

- Typed payment intents/read/list/capture/refund/void/methods and split read/list/refund helpers; existing fraud API preserved.
- JS-compatible numeric-key/scalar JSON, safe integer/header/path validation, HTTPS-only verified transport, bounded responses and redacted errors.
- Strict signed webhook id/type binding, raw-body proof and rotating secrets; legacy nonfinancial fallback requires explicit opt-in.
- Durable encrypted checkout reservations, authenticated fee/split settlement, native atomic inbox/order callbacks, uncertainty handling and23 hour replay fences.
- Runnable Django 6.1.2, FastAPI 0.162.0 and Flask 3.1.3 apps with real auth/session/CSRF/ORM/SQLite stock and outbox, English/Turkish guides and native framework tests.
- Dependency floors updated;0.2.0 is a source release, not a package registry publication claim.


This package follows semantic versioning. On the 0.x line a new API surface is
a minor increase.

## 0.1.0

First release.

### Added

- **Core.** `LunixiClient` facade; validated `Configuration`; `ApiClient` with
  bearer authentication, per-request Ed25519 step-up signing, an
  `Idempotency-Key` header and retries limited to idempotent requests.
- **Signing.** `Ed25519Signer` over `cryptography`, accepting a PKCS#8 PEM,
  base64/hex PKCS#8 DER or a bare 32-byte seed; `build_canonical_request` and
  `digest_for_body`; `generate_key_pair` and `verify_signature` for onboarding
  and offline checks.
- **Tokens.** `TokenManager` with a thread-safe `InMemoryTokenStore`, an
  expiry skew, single-flight exchange and a `TokenStore` seam for a shared
  cache.
- **Envelope.** `is_success`, `data_of`, `items_of`, `page_info_of` and `Page`,
  reading `pageInfo` as a sibling of `data`.
- **Errors.** `LunixiError` hierarchy with `ValidationError`,
  `AuthenticationError`, `RateLimitError` and `ServiceUnavailableError`
  carrying `retry_after` and the quota headers.
- **Transport.** `HttpTransport` protocol with a standard-library
  `UrllibTransport`; compact JSON serialization required by the gateway's
  digest check.
- **Fraud.** `evaluate`, decision-log `list` / `get` / `latest_for_payment` /
  `iterate`, and event `record` / `record_batch` with the 500-event limit and
  partial-result reading. Channel, surface, stage, operation-kind, auth-mode,
  product-context and decision dictionaries.
- **Webhooks.** `WebhookVerifier` for the v2 signature: raw-body HMAC,
  fail-closed verification, timestamp tolerance and rotation-window support.
  The seven fraud event types in `FraudEvents`.
- Type hints throughout with `py.typed`; samples under `samples/`; TR and EN
  READMEs.
