"""Lunixi platform client for Python.

Start with :class:`~lunixi.client.LunixiClient`:

.. code-block:: python

    from lunixi import Channel, LunixiClient

    client = LunixiClient(
        base_url="https://api.lunixi.com",
        key_id="kid_...",
        private_key=private_key_pem,          # from your secret store
    )

    decision = client.fraud().evaluate(
        channel=Channel.STANDALONE_API,
        transaction_ref="order-2026-0001",
        payment={"amount": "149.90", "currency": "TRY"},
    )
    if decision.blocked:
        ...

This release carries the shared core — request signing, token exchange,
envelope decoding, paging and the error hierarchy — and the fraud surface on
top of it. :meth:`~lunixi.client.LunixiClient.api` reaches any other gateway
route with the same signing and error handling.
"""

from .api_client import ApiClient
from .auth.ed25519_signer import Ed25519Signer, generate_key_pair, verify_signature
from .auth.token_manager import InMemoryTokenStore, TokenManager, TokenStore
from .client import LunixiClient
from .configuration import Configuration
from .errors import (
    ApiError,
    AuthenticationError,
    ConfigurationError,
    LunixiError,
    RateLimitError,
    ServiceUnavailableError,
    SignatureError,
    ValidationError,
    WebhookVerificationError,
)
from .fraud.fraud_client import (
    EVENT_BATCH_LIMIT,
    FraudClient,
    FraudDecisionsClient,
    FraudEventsClient,
)
from .fraud.fraud_events import FRAUD_EVENT_TYPES, FraudEvents
from .fraud.results import EventBatchResult, EventResult, FraudDecision
from .fraud.taxonomy import (
    INTEGRATION_MODE_STANDALONE,
    AuthMode,
    Channel,
    Decision,
    OperationKind,
    ProductContext,
    Stage,
    Surface,
)
from .http.envelope import Page, data_of, is_success, items_of, page_info_of
from .http.transport import HttpResponse, HttpTransport, TransportError, UrllibTransport
from .webhook.verifier import WebhookEvent, WebhookVerifier

__all__ = [
    "LunixiClient",
    "Configuration",
    "ApiClient",
    "Ed25519Signer",
    "generate_key_pair",
    "verify_signature",
    "TokenManager",
    "TokenStore",
    "InMemoryTokenStore",
    "HttpTransport",
    "HttpResponse",
    "UrllibTransport",
    "TransportError",
    "Page",
    "is_success",
    "data_of",
    "items_of",
    "page_info_of",
    "FraudClient",
    "FraudDecisionsClient",
    "FraudEventsClient",
    "FraudDecision",
    "EventResult",
    "EventBatchResult",
    "EVENT_BATCH_LIMIT",
    "FraudEvents",
    "FRAUD_EVENT_TYPES",
    "Channel",
    "Surface",
    "Stage",
    "OperationKind",
    "AuthMode",
    "ProductContext",
    "Decision",
    "INTEGRATION_MODE_STANDALONE",
    "WebhookVerifier",
    "WebhookEvent",
    "LunixiError",
    "ConfigurationError",
    "SignatureError",
    "WebhookVerificationError",
    "ApiError",
    "ValidationError",
    "AuthenticationError",
    "RateLimitError",
    "ServiceUnavailableError",
]
