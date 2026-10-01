"""Agent Card and registry payload for an arena agent."""

from typing import Any, Dict

from a2a.types import AgentCard
from runtime.a2a_card import acdp_a2a_block, build_agent_card

from arena.cast import MODEL_IDS, AgentSpec
from arena.identity import Identity

WELL_KNOWN = "/.well-known/agent-card.json"


def agent_base_url(base_url: str, slug: str) -> str:
    """A2A base URL of a mounted agent. It ends with "/"."""
    return f"{base_url.rstrip('/')}/agents/{slug}/"


def card_path(slug: str) -> str:
    """Card path on the arena host, for the DNS TXT "a2a=" field."""
    return f"/agents/{slug}{WELL_KNOWN}"


def _config(spec: AgentSpec, identity: Identity, base_url: str) -> Dict[str, Any]:
    return {
        "id": identity.agent_id,
        "name": spec.name,
        "description": spec.description,
        "capabilities": [spec.capability],
        "interfaces": {"a2a": agent_base_url(base_url, spec.slug)},
        "owner": spec.organization,
        "owner_url": f"https://{spec.domain}",
        "version": "0.1.0",
        "did": identity.did,
        "organization": spec.organization,
        "domain": spec.domain,
        "publicKeyJwk": identity.public_jwk(),
        "model_name": MODEL_IDS[spec.model],
        "collaboration": {"max_delegation_depth": 0},
    }


def build_card(spec: AgentSpec, identity: Identity, base_url: str) -> AgentCard:
    """Agent Card with the ACDP extension and identity params."""
    return build_agent_card(_config(spec, identity, base_url))


def registration_payload(
    spec: AgentSpec, identity: Identity, base_url: str, card: AgentCard
) -> Dict[str, Any]:
    """Body for POST /registerAgent."""
    config = _config(spec, identity, base_url)
    return {
        "id": identity.agent_id,
        "name": spec.name,
        "description": spec.description,
        "capabilities": [spec.capability],
        "interfaces": config["interfaces"],
        "protocols": ["a2a/0.3"],
        "model_info": {"provider": "Anthropic", "model": MODEL_IDS[spec.model]},
        "a2a": acdp_a2a_block(config, card),
        "agent_card": card.model_dump(mode="json", exclude_none=True),
        "organization": spec.organization,
        "domain": spec.domain,
        "did": identity.did,
    }
