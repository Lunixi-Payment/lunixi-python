# Changelog

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
