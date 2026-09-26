"""Map ACDP agent metadata to an A2A Agent Card and back.

ACDP owns discovery (DNS SRV/TXT, registry, gossip); A2A owns invocation. The Agent
Card is where the two meet:

* each ACDP capability becomes an A2A ``AgentSkill`` (id = capability, tagged with it),
  so A2A-only clients can reason about what the agent does;
* the ACDP identity (agent id, DNS SRV name, ACDP endpoints) travels in a declared A2A
  extension, so an ACDP client can check that the card it fetched belongs to the agent
  id it discovered.
"""

from typing import Any, Dict, List, Optional

from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentExtension,
    AgentProvider,
    AgentSkill,
    HTTPAuthSecurityScheme,
    SecurityScheme,
    TransportProtocol,
)
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH

from .delegation import ACDP_EXTENSION_URI

A2A_PROTOCOL_VERSION = "0.3.0"


def capability_to_skill(capability: str) -> AgentSkill:
    label = capability.replace("_", " ").replace("-", " ").strip()
    return AgentSkill(
        id=capability,
        name=label.title(),
        description=f"Answers questions and performs tasks involving {label}.",
        tags=[capability],
    )


def acdp_extension(config: Dict[str, Any]) -> AgentExtension:
    return AgentExtension(
        uri=ACDP_EXTENSION_URI,
        description="ACDP discovery identity and delegation-trace metadata",
        required=False,
        params={
            "acdp_version": config.get("acdp_version", "1.1"),
            "id": config["id"],
            "capabilities": list(config.get("capabilities", [])),
            "dns_srv": f"_llm-agent._tcp.{config['id']}",
            "registry": config.get("registry_url"),
            "endpoints": {
                k: v
                for k, v in (config.get("endpoints") or {}).items()
                if k in ("metadata", "peers", "ping", "assist")
            },
            "max_delegation_depth": (config.get("collaboration") or {}).get(
                "max_delegation_depth", 2
            ),
        },
    )


def build_agent_card(config: Dict[str, Any]) -> AgentCard:
    """Agent Card served at ``/.well-known/agent-card.json``."""
    token_required = bool((config.get("security") or {}).get("a2a_token"))
    security_schemes = None
    security = None
    if token_required:
        security_schemes = {
            "acdpBearer": SecurityScheme(
                root=HTTPAuthSecurityScheme(
                    scheme="bearer",
                    description="Shared ACDP network token (ACDP_A2A_TOKEN)",
                )
            )
        }
        security = [{"acdpBearer": []}]

    return AgentCard(
        name=config["name"],
        description=config["description"],
        url=config["interfaces"]["a2a"],
        version=config.get("version", "0.0.1"),
        protocol_version=A2A_PROTOCOL_VERSION,
        preferred_transport=TransportProtocol.jsonrpc.value,
        provider=AgentProvider(
            organization=config.get("owner", "unknown"),
            url=config.get("owner_url", "https://github.com/zerocmd/acdp"),
        ),
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(
            streaming=True,
            push_notifications=False,
            extensions=[acdp_extension(config)],
        ),
        skills=[capability_to_skill(c) for c in config.get("capabilities", [])],
        security_schemes=security_schemes,
        security=security,
    )


def acdp_a2a_block(config: Dict[str, Any], card: AgentCard) -> Dict[str, Any]:
    """The ``a2a`` block added to ACDP metadata and registry entries."""
    base = config["interfaces"]["a2a"]
    return {
        "url": base,
        "card_url": base.rstrip("/") + AGENT_CARD_WELL_KNOWN_PATH,
        "protocol_version": card.protocol_version,
        "transport": card.preferred_transport,
        "skills": [s.id for s in card.skills],
        "auth": "bearer" if card.security_schemes else "none",
    }


def card_endpoint(card: Dict[str, Any]) -> Optional[str]:
    """A2A endpoint URL from a card in JSON form, for A2A 0.3 and 1.0 cards.

    0.3 cards carry ``url``; 1.0 cards carry ``supportedInterfaces[].url``. Registries
    store cards as opaque JSON so both generations can coexist during migration.
    """
    if card.get("url"):
        return card["url"]
    for iface in card.get("supportedInterfaces") or card.get("supported_interfaces") or []:
        if iface.get("url"):
            return iface["url"]
    return None


def card_acdp_params(card: Dict[str, Any]) -> Dict[str, Any]:
    """ACDP extension params from a card in JSON form ({} if not declared)."""
    extensions = (card.get("capabilities") or {}).get("extensions") or []
    for ext in extensions:
        if ext.get("uri") == ACDP_EXTENSION_URI:
            return ext.get("params") or {}
    return {}


def card_skill_ids(card: Dict[str, Any]) -> List[str]:
    ids: List[str] = []
    for skill in card.get("skills") or []:
        ids.append(skill.get("id", ""))
        ids.extend(skill.get("tags") or [])
    return [i for i in ids if i]
