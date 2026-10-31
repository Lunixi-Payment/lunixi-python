"""Ed25519 request signing.

The curve arithmetic is delegated to ``cryptography`` (``pip install
lunixi-sdk`` pulls it in). This package deliberately contains no hand-written
Ed25519: a signing bug would be silent — a wrong-but-well-formed signature
simply fails verification — and a customer SDK is the last place to discover it.
"""

from __future__ import annotations

import base64
import binascii
import hmac
from typing import Tuple

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ..errors import SignatureError

__all__ = ["Ed25519Signer", "generate_key_pair"]

# DER prefix of a PKCS#8-wrapped Ed25519 private key; the 32-byte seed follows.
_PKCS8_PREFIX = bytes.fromhex("302e020100300506032b657004220420")

_SEED_LENGTH = 32
_PKCS8_DER_LENGTH = len(_PKCS8_PREFIX) + _SEED_LENGTH  # 48
_SEED_AND_PUBLIC_LENGTH = 64


class Ed25519Signer:
    """Signs canonical request strings with a merchant private key.

    Accepts the key material in the shapes a merchant actually has on hand:

    * a PKCS#8 PEM block (``-----BEGIN PRIVATE KEY-----``) — what the console
      hands out, and what we recommend keeping;
    * base64 (or hex) PKCS#8 DER, 48 bytes;
    * a bare 32-byte seed, base64 or hex;
    * a 64-byte seed-then-public-key concatenation, base64 or hex, as some
      Ed25519 tooling exports. Only the first 32 bytes are the private key.

    The private key never leaves this object: it is not stored on the
    configuration, not logged, and not included in ``repr``.
    """

    __slots__ = ("_private_key",)

    def __init__(self, private_key: "str | bytes") -> None:
        self._private_key = _load_private_key(private_key)

    def sign(self, message: str) -> str:
        """Returns the base64 signature of ``message`` (UTF-8 encoded)."""
        try:
            return base64.b64encode(self._private_key.sign(message.encode("utf-8"))).decode("ascii")
        except Exception as error:  # pragma: no cover - cryptography internal failure
            raise SignatureError(f"Ed25519 signing failed: {error}") from error

    def public_key_pem(self) -> str:
        """Returns the matching public key as an SPKI PEM block.

        This is the value you upload to the console when you generate the
        keypair yourself, which is the model we recommend: the private key then
        never exists outside your own systems.
        """
        return (
            self._private_key.public_key()
            .public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode("ascii")
        )

    def __repr__(self) -> str:
        return "Ed25519Signer(<private key withheld>)"


def generate_key_pair() -> Tuple[str, str]:
    """Generates a fresh Ed25519 keypair for onboarding or for tests.

    Returns:
        ``(private_key_pem, public_key_pem)``. Upload the public PEM to the
        console and store the private PEM in your own secret store.
    """
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("ascii")
    )
    return private_pem, public_pem


def verify_signature(public_key_pem: str, signature_base64: str, message: str) -> bool:
    """Verifies a base64 Ed25519 signature against an SPKI PEM public key.

    Present so a caller can check their own signing setup offline, against the
    public key they uploaded, without sending a request.
    """
    try:
        public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
    except Exception as error:
        raise SignatureError(f"Unsupported Ed25519 public key PEM: {error}") from error
    if not isinstance(public_key, Ed25519PublicKey):
        raise SignatureError("Public key is not an Ed25519 key.")
    try:
        public_key.verify(base64.b64decode(signature_base64), message.encode("utf-8"))
    except Exception:
        return False
    return True


def _load_private_key(value: "str | bytes") -> Ed25519PrivateKey:
    if isinstance(value, bytes):
        return _from_raw_material(value)

    if not isinstance(value, str) or value.strip() == "":
        raise SignatureError("Ed25519 private key is empty.")

    trimmed = value.strip()
    if "-----BEGIN" in trimmed:
        try:
            key = serialization.load_pem_private_key(trimmed.encode("utf-8"), password=None)
        except (ValueError, TypeError, UnsupportedAlgorithm) as error:
            raise SignatureError(
                "Unsupported Ed25519 private key PEM. An encrypted PEM must be "
                "decrypted before it is passed in."
            ) from error
        if not isinstance(key, Ed25519PrivateKey):
            raise SignatureError("The private key PEM is not an Ed25519 key.")
        return key

    return _from_raw_material(_decode_key_material(trimmed))


def _from_raw_material(material: bytes) -> Ed25519PrivateKey:
    try:
        if len(material) == _PKCS8_DER_LENGTH and material.startswith(_PKCS8_PREFIX):
            return Ed25519PrivateKey.from_private_bytes(material[len(_PKCS8_PREFIX) :])
        if len(material) == _SEED_LENGTH:
            return Ed25519PrivateKey.from_private_bytes(material)
        if len(material) == _SEED_AND_PUBLIC_LENGTH:
            key = Ed25519PrivateKey.from_private_bytes(material[:_SEED_LENGTH])
            public = key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
            if not hmac.compare_digest(public, material[_SEED_LENGTH:]):
                raise SignatureError("Ed25519 seed/public export is inconsistent.")
            return key
    except ValueError as error:
        raise SignatureError(f"Unusable Ed25519 private key material: {error}") from error

    raise SignatureError(
        "Unsupported Ed25519 private key. Expected a PKCS#8 PEM block, "
        "base64/hex PKCS#8 DER (48 bytes), or a 32-byte seed."
    )


def _decode_key_material(value: str) -> bytes:
    """Decodes base64 or hex key material.

    Hex is tried first: a 64-character hex seed is also valid base64, and
    decoding it as base64 would yield 48 meaningless bytes instead of the
    intended 32-byte seed.
    """
    compact = "".join(value.split())
    try:
        return bytes.fromhex(compact)
    except ValueError:
        pass
    try:
        return base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as error:
        raise SignatureError(
            "Ed25519 private key is neither a PEM block nor base64/hex material."
        ) from error
