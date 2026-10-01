"""Peer-side trust check for inbound messages.

A message is verified only when all of these hold:
1. The sender card is reachable.
2. The card is the sender's card: its id equals the message from_id, the id is a
   name under the card domain, and the DID is the did:web form of that id.
3. The DID equals the message from_did.
4. The signature matches the card key.
5. DNS for the sender agent id publishes that key's fingerprint.
6. The registry anchors the card organization to the card domain. An unknown
   organization or an unreachable registry fails the check.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from runtime.a2a_card import card_acdp_params

from arena.acdp import AcdpError
from arena.envelope import ArenaMessage
from arena.identity import fingerprint_jwk, verify_signature

Lookup = Callable[[str], Awaitable[Optional[Dict[str, Any]]]]


@dataclass(frozen=True)
class Trust:
    status: str
    reason: str = ""


VERIFIED = Trust("verified")


class Verifier:
    """Runs the five checks. Each lookup is an async callable.

    Args:
        fetch_card: URL to card JSON, or None.
        dns_lookup: Agent id to DNS data with "key", or None.
        org_lookup: Organization to {"canonical_domain"}, or None.
    """

    def __init__(self, fetch_card: Lookup, dns_lookup: Lookup, org_lookup: Lookup) -> None:
        self.fetch_card = fetch_card
        self.dns_lookup = dns_lookup
        self.org_lookup = org_lookup

    async def check(self, message: ArenaMessage) -> Trust:
        card = await self.fetch_card(message.card_url)
        if not card:
            return Trust("failed", "card unreachable")
        params = card_acdp_params(card)
        agent_id = str(params.get("id", ""))
        domain = str(params.get("domain", ""))
        if agent_id != message.from_id:
            return Trust("failed", "sender mismatch")
        if not domain or not agent_id.endswith("." + domain):
            return Trust("failed", "card domain mismatch")
        slug = agent_id[: -len(domain) - 1]
        expected_did = f"did:web:{domain}:agents:{slug}"
        if params.get("did") != expected_did or message.from_did != expected_did:
            return Trust("failed", "did mismatch")
        jwk = params.get("publicKeyJwk") or {}
        if not verify_signature(message.payload(), jwk):
            return Trust("failed", "bad signature")
        dns = await self.dns_lookup(agent_id)
        try:
            expected = fingerprint_jwk(jwk)
        except (KeyError, ValueError):
            expected = None
        if not dns or not expected or dns.get("key") != expected:
            return Trust("failed", "key not in dns")
        try:
            org = await self.org_lookup(str(params.get("organization", "")))
        except AcdpError:
            return Trust("failed", "registry unreachable")
        if not org:
            return Trust("failed", "organization not registered")
        if org.get("canonical_domain") != domain:
            return Trust("failed", "domain mismatch")
        return VERIFIED
