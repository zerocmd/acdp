"""Resolve where a peer can be reached from its ACDP metadata.

ACDP metadata arrives from three sources (registry, DNS SRV/TXT, gossip) and from two
generations of agents (ACDP 1.0 REST-only, ACDP 1.1 with A2A). This module is the single
place that turns any of those shapes into URLs; the original code repeated this logic in
four places with slightly different fallbacks.
"""

from typing import Any, Dict, Optional
from urllib.parse import urlparse

DEFAULT_PORT = 8000


def _origin(url: str) -> Optional[str]:
    """Return scheme://host[:port] for an absolute URL, or None."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return None


def base_url(peer_id: str, info: Dict[str, Any], default_port: int = DEFAULT_PORT) -> Optional[str]:
    """Best-effort origin (scheme://host:port) for a peer's HTTP surface."""
    a2a = info.get("a2a") or {}
    interfaces = info.get("interfaces") or {}
    for candidate in (a2a.get("url"), interfaces.get("a2a"), interfaces.get("rest")):
        if candidate and (origin := _origin(candidate)):
            return origin

    host = info.get("host")
    port = info.get("port")
    if not host and "." in peer_id:
        # Docker Compose service name is the first label of the agent id.
        host = peer_id.split(".")[0]
    if not host:
        return None
    try:
        port = int(port) if port else default_port
    except (TypeError, ValueError):
        port = default_port
    return f"http://{host}:{port}"


def endpoint_url(
    peer_id: str, info: Dict[str, Any], key: str, default_path: str
) -> Optional[str]:
    """Absolute URL for a named ACDP endpoint (metadata, peers, ping, assist, ...)."""
    path = (info.get("endpoints") or {}).get(key) or default_path
    if path.startswith(("http://", "https://")):
        return path
    origin = base_url(peer_id, info)
    if not origin:
        return None
    return f"{origin}/{path.lstrip('/')}"


def a2a_url(info: Dict[str, Any]) -> Optional[str]:
    """The peer's A2A base URL if it advertises A2A support, else None.

    ACDP 1.1 agents advertise A2A in any of: an ``a2a`` block (registry/metadata),
    ``interfaces.a2a``, or the ``a2a=`` key in their DNS TXT record (surfaced by the
    DNS resolver as ``a2a.url``). ACDP 1.0 agents have none of these and are reached
    through the legacy ``/assist`` endpoint instead.
    """
    a2a = info.get("a2a") or {}
    url = a2a.get("url") or (info.get("interfaces") or {}).get("a2a")
    if url:
        return url
    if any(str(p).startswith("a2a") for p in info.get("protocols") or []):
        origin = base_url(info.get("id", ""), info)
        return f"{origin}/" if origin else None
    return None
