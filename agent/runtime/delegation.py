"""Delegation guard for agent-to-agent calls.

Once every agent can call every other agent through a tool, the model can build
delegation chains (A -> B -> C) and cycles (A -> B -> A). The original PoC avoided
this by never letting ``/assist`` collaborate. With A2A the chain is legitimate, so it
is bounded instead: each outbound A2A message carries a trace of the agents it has
passed through, inside the message metadata under the ACDP extension URI.

    message.metadata[ACDP_EXTENSION_URI] = {"hops": 1, "trace": ["agent1.agents.local"]}

An agent refuses to delegate when the next hop would exceed ``max_depth`` or when the
target already appears in the trace.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

# A2A extension that carries ACDP identity and delegation state. Declared in each
# Agent Card under capabilities.extensions and defined in ACDP.md ("A2A Extension v1").
ACDP_EXTENSION_URI = "https://github.com/zerocmd/acdp/blob/main/ACDP.md#a2a-extension-v1"


@dataclass(frozen=True)
class DelegationState:
    """Where the current request sits in a delegation chain."""

    hops: int = 0
    trace: List[str] = field(default_factory=list)

    @classmethod
    def from_metadata(cls, metadata: Optional[Mapping[str, Any]]) -> "DelegationState":
        payload = (metadata or {}).get(ACDP_EXTENSION_URI) or {}
        try:
            hops = max(0, int(payload.get("hops", 0)))
        except (TypeError, ValueError):
            hops = 0
        trace = [str(t) for t in payload.get("trace", []) if isinstance(t, str)][:32]
        return cls(hops=hops, trace=trace)

    @classmethod
    def from_invocation_state(cls, invocation_state: Mapping[str, Any]) -> "DelegationState":
        """Recover the state from a Strands tool's invocation_state.

        Requests that arrive over A2A carry the RequestContext (set by the Strands
        executor); requests over the legacy REST surface carry an explicit state.
        """
        explicit = invocation_state.get("acdp_delegation")
        if isinstance(explicit, DelegationState):
            return explicit
        request_context = invocation_state.get("a2a_request_context")
        message = getattr(request_context, "message", None)
        return cls.from_metadata(getattr(message, "metadata", None))

    def check(self, self_id: str, target_id: str, max_depth: int) -> Optional[str]:
        """Return a refusal reason, or None if delegating to ``target_id`` is allowed."""
        if target_id == self_id:
            return "an agent cannot delegate to itself"
        if target_id in self.trace:
            return f"{target_id} is already part of this delegation chain ({' -> '.join(self.trace)})"
        if self.hops + 1 > max_depth:
            return f"maximum delegation depth ({max_depth}) reached"
        return None

    def next_hop(self, self_id: str) -> Dict[str, Any]:
        """Metadata payload for a message this agent sends onward."""
        return {
            ACDP_EXTENSION_URI: {
                "hops": self.hops + 1,
                "trace": [*self.trace, self_id],
            }
        }
