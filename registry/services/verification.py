"""Registration checks: card re-fetch, DNS key pin, and organization anchor.

The registry records the result and accepts the registration in all cases.
Peers decide what to do with an agent that fails verification.
"""

import base64
import datetime
import hashlib
import re
from typing import Any, Callable, Dict, List, Optional

# Must match agent/runtime/a2a_card.py. A test checks this.
ACDP_EXTENSION_URI = "https://github.com/zerocmd/acdp/blob/main/ACDP.md#a2a-extension-v1"


def fingerprint_jwk(jwk: Dict[str, Any]) -> Optional[str]:
    """Base64url SHA-256 of the raw Ed25519 public key in a JWK.

    Args:
        jwk: An OKP/Ed25519 JWK with an "x" member.

    Returns:
        The 43-character fingerprint, or None if the key is malformed.
    """
    x = jwk.get("x") if isinstance(jwk, dict) else None
    if not isinstance(x, str):
        return None
    try:
        raw = base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))
    except ValueError:
        return None
    if len(raw) != 32:
        return None
    return base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b"=").decode()


def normalize_org(name: str) -> str:
    """Lowercase alphanumeric form of an organization name."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


class OrgDirectory:
    """First registrant of an organization name owns its canonical domain."""

    def __init__(self) -> None:
        self._entries: Dict[str, Dict[str, str]] = {}

    def claim(self, organization: str, domain: str) -> Dict[str, Any]:
        """Record or check a claim.

        Args:
            organization: Organization name from the Agent Card.
            domain: Domain from the Agent Card.

        Returns:
            {"canonical_domain": str, "conflict": bool}
        """
        normalized = normalize_org(organization)
        if not normalized or not domain:
            return {"canonical_domain": domain, "conflict": False}
        entry = self._entries.setdefault(
            normalized, {"organization": organization, "canonical_domain": domain}
        )
        return {
            "canonical_domain": entry["canonical_domain"],
            "conflict": entry["canonical_domain"] != domain,
        }

    def get(self, normalized: str) -> Optional[Dict[str, str]]:
        return self._entries.get(normalized)

    def clear(self) -> None:
        self._entries.clear()


def acdp_params(card: Dict[str, Any]) -> Dict[str, Any]:
    """ACDP extension params from an Agent Card in JSON form."""
    for ext in (card.get("capabilities") or {}).get("extensions") or []:
        if isinstance(ext, dict) and ext.get("uri") == ACDP_EXTENSION_URI:
            return ext.get("params") or {}
    return {}


def txt_fields(txt: List[str]) -> Dict[str, str]:
    """Map "name=value" TXT strings to a dict."""
    return dict(item.split("=", 1) for item in txt if "=" in item)


def verify_registration(
    data: Dict[str, Any],
    fetch_card: Callable[[str], Optional[Dict[str, Any]]],
    lookup_txt: Callable[[str], Optional[List[str]]],
    orgs: OrgDirectory,
) -> Dict[str, Any]:
    """Check a registration against the live card and DNS.

    Args:
        data: The registration body. It has "id", "agent_card", and "a2a.card_url".
        fetch_card: Returns the card JSON at a URL, or None.
        lookup_txt: Returns the TXT strings for an agent id, or None.
        orgs: The organization directory.

    Returns:
        The verification record.
    """
    reasons: List[str] = []
    card_url = (data.get("a2a") or {}).get("card_url")
    fetched = fetch_card(card_url) if card_url else None
    card_fetched = isinstance(fetched, dict)
    if not card_fetched:
        reasons.append("card unreachable")
    params = acdp_params(fetched if card_fetched else data.get("agent_card") or {})
    agent_id = str(data["id"])
    card_id = str(params.get("id", ""))
    card_domain = str(params.get("domain", ""))
    if card_id != agent_id or not card_domain or not agent_id.endswith("." + card_domain):
        reasons.append("card identity mismatch")

    txt = lookup_txt(data["id"])
    dns_found = txt is not None
    if not dns_found:
        reasons.append("txt record missing")
    fingerprint = fingerprint_jwk(params.get("publicKeyJwk") or {})
    key_matches = bool(dns_found and fingerprint and txt_fields(txt).get("key") == fingerprint)
    if dns_found and not key_matches:
        reasons.append("key mismatch")

    org = orgs.claim(params.get("organization", ""), params.get("domain", ""))
    if org["conflict"]:
        reasons.append(f"organization registered under {org['canonical_domain']}")

    verified = (
        card_fetched and dns_found and key_matches and not org["conflict"]
        and "card identity mismatch" not in reasons
    )
    return {
        "status": "verified" if verified else "failed",
        "card_fetched": card_fetched,
        "dns_found": dns_found,
        "key_matches_dns": key_matches,
        "org_conflict": org["conflict"],
        "canonical_domain": org["canonical_domain"],
        "reasons": reasons,
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
