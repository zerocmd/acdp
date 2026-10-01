"""Expose the node's Strands agent over A2A.

Strands' ``A2AServer`` provides the JSON-RPC endpoint, task store and executor. It
derives a minimal Agent Card from the agent (name, description, tools-as-skills); ACDP
replaces that card with one that maps ACDP capabilities to skills and declares the ACDP
extension, so the card also works as an ACDP identity document.
"""

import hmac
import json
import logging
from typing import Any, Dict, Optional

from a2a.types import AgentCard
from strands.multiagent.a2a import A2AServer

logger = logging.getLogger(__name__)


class ACDPA2AServer(A2AServer):
    """A2AServer that serves an ACDP-built Agent Card."""

    def __init__(self, *, card: AgentCard, **kwargs: Any):
        self._acdp_card = card
        super().__init__(**kwargs)

    @property
    def public_agent_card(self) -> AgentCard:
        return self._acdp_card


class BearerTokenMiddleware:
    """Require ``Authorization: Bearer <token>`` on endpoints that spend credits or change state.

    Guards the endpoints that spend model credits on a peer's behalf (A2A JSON-RPC,
    legacy ``/assist``) and the operator controls that change node state (shared-memory
    writes, starting/stopping gossip). Discovery documents (Agent Card, /metadata,
    /peers, /health) stay public, as ACDP and A2A both expect them to be fetchable
    before any credential exchange. ``POST /peers`` stays open because gossip is a
    hint: every id it carries is re-resolved through the registry or DNS. ``/chat`` is
    the user-facing surface and is left to network-level access control.
    """

    PROTECTED = {
        ("POST", "/"),
        ("POST", "/assist"),
        ("POST", "/memory"),
        ("POST", "/gossip/start"),
        ("POST", "/gossip/stop"),
    }

    def __init__(self, app: Any, token: Optional[str]):
        self.app = app
        self.expected = f"Bearer {token}".encode() if token else None

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if (
            self.expected is not None
            and scope["type"] == "http"
            and (scope["method"], scope["path"]) in self.PROTECTED
        ):
            supplied = dict(scope.get("headers") or []).get(b"authorization", b"")
            if not hmac.compare_digest(supplied, self.expected):
                body = json.dumps({"error": "unauthorized"}).encode()
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"www-authenticate", b"Bearer"),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
