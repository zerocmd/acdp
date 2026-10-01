"""Agent identity: an Ed25519 key, a did:web identifier, and message signatures.

The DNS TXT record of each agent publishes the key fingerprint. A peer trusts a
signature only when the signing key matches that fingerprint.
"""

import base64
import binascii
import hashlib
import json
from typing import Any, Dict, Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


def b64url(data: bytes) -> str:
    """Base64url without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64url_decode(text: str) -> bytes:
    """Decode base64url with or without padding.

    Raises:
        ValueError: The text is not valid base64url.
    """
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def canonical(payload: Dict[str, Any]) -> bytes:
    """Bytes that a signature covers: sorted-key JSON without the "sig" member."""
    body = {k: v for k, v in payload.items() if k != "sig"}
    return json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()


def fingerprint_jwk(jwk: Dict[str, str]) -> str:
    """Base64url SHA-256 of the raw public key in an OKP/Ed25519 JWK.

    Raises:
        KeyError: The JWK has no "x" member.
        ValueError: "x" is not valid base64url.
    """
    return b64url(hashlib.sha256(b64url_decode(jwk["x"])).digest())


def verify_signature(payload: Dict[str, Any], jwk: Dict[str, str]) -> bool:
    """Check payload["sig"] against the key in the JWK.

    Returns:
        True only for a valid signature. Malformed input returns False.
    """
    try:
        key = Ed25519PublicKey.from_public_bytes(b64url_decode(jwk["x"]))
        key.verify(b64url_decode(payload["sig"]), canonical(payload))
    except (InvalidSignature, KeyError, TypeError, ValueError, binascii.Error):
        return False
    return True


class Identity:
    """Key pair and identifiers of one arena agent.

    Args:
        slug: Short agent name, unique in the arena.
        domain: Organization domain, for example northgate.example.
        private_key: Fixed key for tests. A new key is generated when omitted.
    """

    def __init__(
        self, slug: str, domain: str, private_key: Optional[Ed25519PrivateKey] = None
    ) -> None:
        self.slug = slug
        self.domain = domain
        self._key = private_key or Ed25519PrivateKey.generate()

    @property
    def agent_id(self) -> str:
        return f"{self.slug}.{self.domain}"

    @property
    def did(self) -> str:
        return f"did:web:{self.domain}:agents:{self.slug}"

    def public_jwk(self) -> Dict[str, str]:
        raw = self._key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        return {"kty": "OKP", "crv": "Ed25519", "x": b64url(raw)}

    def fingerprint(self) -> str:
        return fingerprint_jwk(self.public_jwk())

    def sign(self, payload: Dict[str, Any]) -> str:
        """Signature over canonical(payload), base64url encoded."""
        return b64url(self._key.sign(canonical(payload)))
