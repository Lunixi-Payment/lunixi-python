"""The facade a caller constructs.

One object owns the configuration, the signer, the token cache and the feature
clients, so an application builds it once at start-up and shares it. Sharing it
matters: the token cache lives on this object, and a fresh client per request
would exchange a fresh token per request.
"""

from __future__ import annotations

from typing import Optional

from .api_client import ApiClient
from .auth.ed25519_signer import Ed25519Signer
from .auth.token_manager import TokenManager, TokenStore
from .configuration import DEFAULT_AUTH_TOKEN_PATH, Configuration
from .fraud.fraud_client import FraudClient
from .http.transport import HttpTransport
from .webhook.verifier import WebhookVerifier

__all__ = ["LunixiClient"]


class LunixiClient:
    """Entry point to the Lunixi platform.

    .. code-block:: python

        from lunixi import LunixiClient

        client = LunixiClient(
            base_url="https://api.lunixi.com",
            key_id="kid_...",
            private_key=open("lunixi-private-key.pem").read(),
        )
        decision = client.fraud().evaluate(
            channel="standalone_api",
            transaction_ref="order-2026-0001",
        )

    Args:
        base_url: Gateway origin.
        key_id: Key id from the console.
        private_key: Your Ed25519 private key; see
            :class:`~lunixi.auth.ed25519_signer.Ed25519Signer` for the accepted
            shapes. Load it from your secret store — not from source, and not
            from a file inside your repository.
        auth_token_path: Token endpoint path; the default is correct.
        timeout_seconds: Per-request timeout.
        max_retries: Extra attempts for an idempotent request.
        user_agent: Appended to, or replacing, the default.
        transport: Your own HTTP stack.
        token_store: A shared token cache. Supply one in a multi-process
            deployment so the workers share a token instead of each exchanging
            their own.

    This object is thread-safe: the token cache is guarded, and nothing else is
    mutated after construction.
    """

    def __init__(
        self,
        *,
        base_url: str,
        key_id: str,
        private_key: str,
        auth_token_path: str = DEFAULT_AUTH_TOKEN_PATH,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        user_agent: Optional[str] = None,
        transport: Optional[HttpTransport] = None,
        token_store: Optional[TokenStore] = None,
    ) -> None:
        self._config = Configuration(
            base_url=base_url,
            key_id=key_id,
            auth_token_path=auth_token_path,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            user_agent=user_agent,
            transport=transport,
        )
        self._signer = Ed25519Signer(private_key)
        self._tokens = TokenManager(self._config, self._signer, token_store)
        self._api = ApiClient(self._config, self._signer, self._tokens)
        self._fraud = FraudClient(self._api)

    def fraud(self) -> FraudClient:
        """The fraud surface: decisions, decision logs and event ingest."""
        return self._fraud

    def api(self) -> ApiClient:
        """The raw authenticated request path.

        Use it to reach a gateway route this version does not wrap yet, with
        the signing, retry and error mapping already handled.
        """
        return self._api

    def tokens(self) -> TokenManager:
        """The token manager — call ``invalidate()`` to force a fresh token."""
        return self._tokens

    def signer(self) -> Ed25519Signer:
        """The signer, for signing a canonical string yourself."""
        return self._signer

    def configuration(self) -> Configuration:
        """The validated configuration."""
        return self._config

    def webhooks(self, secret: str, **kwargs) -> WebhookVerifier:
        """Builds a verifier for one webhook endpoint's secret.

        A secret belongs to an endpoint, not to an account, so this is a
        factory rather than a property: an application with several endpoints
        holds several verifiers.
        """
        return WebhookVerifier(secret, **kwargs)
