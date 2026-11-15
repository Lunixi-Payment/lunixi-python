"""Identity signals: device and account linking of a browser trace.

Reach it as ``client.identity()``; see :class:`~lunixi.identity.client.IdentityClient`.
"""

from .client import IdentityClient
from .values import (
    IDENTITY_ANALYZE_FIELDS,
    IDENTITY_ROUTES,
    identity_link_reasons,
    is_identity_device_shared,
)

__all__ = [
    "IdentityClient",
    "IDENTITY_ANALYZE_FIELDS",
    "IDENTITY_ROUTES",
    "is_identity_device_shared",
    "identity_link_reasons",
]
