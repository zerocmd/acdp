"""Async facade over the ACDP registry, the DNS API, and the DNS resolver."""

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx
import requests

logger = logging.getLogger(__name__)


def dns_txt(capability: str, description: str, card_path: str, key: str) -> List[str]:
    """TXT strings as update_zone.sh writes them (for display; DNS is the source)."""
    clean = "".join(ch for ch in description if ch.isprintable() and ch not in '"\\')[:200]
    txt = ["ver=1.1", f"caps={capability}", f"desc={clean}", "proto=a2a/0.3",
           f"a2a={card_path}"]
    if key:
        txt.append(f"key={key}")
    return txt


class AcdpError(Exception):
    """An ACDP service refused a request or could not be reached."""


class AcdpClient:
    """ACDP calls for the arena runtime.

    Args:
        dns_api_url: Base URL of the DNS update API.
        registry: Shared RegistryClient (sync).
        resolver: Shared DNSResolver (sync).
        http_factory: Returns a new httpx.AsyncClient.
        sleep: Async sleep (tests replace it).
        register_attempts: Registry attempts before AcdpError.
        retry_delay: Seconds between registry attempts.
    """

    def __init__(
        self,
        dns_api_url: str,
        registry: Any,
        resolver: Any,
        http_factory: Callable[[], httpx.AsyncClient],
        sleep: Callable[[float], Any] = asyncio.sleep,
        register_attempts: int = 4,
        retry_delay: float = 10.0,
        registry_url: str = "",
    ) -> None:
        self.dns_api_url = dns_api_url.rstrip("/")
        self.registry = registry
        self.resolver = resolver
        self.http_factory = http_factory
        self.sleep = sleep
        self.register_attempts = register_attempts
        self.retry_delay = retry_delay
        self.registry_url = registry_url.rstrip("/")

    async def _post_dns(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        """POST to the DNS API. Retries connection errors; a refusal fails at once."""
        response = None
        for attempt in range(self.register_attempts):
            async with self.http_factory() as http:
                try:
                    response = await http.post(f"{self.dns_api_url}{path}", json=body)
                    break
                except httpx.HTTPError as e:
                    logger.warning(f"DNS API attempt {attempt + 1} failed: {e}")
                    if attempt == self.register_attempts - 1:
                        raise AcdpError(f"DNS API unreachable: {e}") from e
            await self.sleep(self.retry_delay)
        try:
            result = response.json()
        except ValueError:
            result = {}
        if response.status_code != 200:
            raise AcdpError(result.get("message") or f"DNS API returned {response.status_code}")
        return result

    async def registry_get(self, path: str) -> Tuple[int, Any]:
        """GET a registry path. Returns (status, json body).

        Raises:
            AcdpError: The registry cannot be reached.
        """
        async with self.http_factory() as http:
            try:
                response = await http.get(f"{self.registry_url}{path}")
            except httpx.HTTPError as e:
                raise AcdpError(f"registry unreachable: {e}") from e
        try:
            body = response.json()
        except ValueError:
            body = {"error": response.text[:200]}
        return response.status_code, body

    async def create_zone(self, zone: str) -> str:
        """Create the zone if it does not exist. Returns "created" or "exists"."""
        result = await self._post_dns("/zones", {"zone": zone})
        return str(result.get("result", ""))

    async def publish_dns(
        self,
        *,
        agent_id: str,
        host: str,
        port: int,
        capability: str,
        description: str,
        card_path: str,
        key: str,
    ) -> None:
        """Write the agent's SRV and TXT records."""
        await self._post_dns(
            "/update_dns",
            {
                "domain": agent_id,
                "host": host,
                "port": port,
                "capabilities": capability,
                "description": description[:200],
                "a2a": card_path,
                "protocols": "a2a/0.3",
                "version": "1.1",
                "key": key,
            },
        )

    async def register(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Register with the registry. Returns the stored entry."""
        last_error: Optional[Exception] = None
        for attempt in range(self.register_attempts):
            try:
                response = await asyncio.to_thread(self.registry.register_agent, payload)
                return response["agent"]
            except requests.RequestException as e:
                last_error = e
                logger.warning(f"Registry attempt {attempt + 1} failed: {e}")
                if attempt < self.register_attempts - 1:
                    await self.sleep(self.retry_delay)
        raise AcdpError(f"registry unreachable: {last_error}")

    async def find(self, capability: str) -> List[Dict[str, Any]]:
        """Registry entries that offer the capability."""
        response = await asyncio.to_thread(self.registry.get_agents, capability=capability)
        return list(response.get("agents") or [])

    async def org(self, organization: str) -> Optional[Dict[str, Any]]:
        """Canonical domain of an organization, or None when it is not registered.

        Raises:
            AcdpError: The registry cannot be reached. Callers must fail closed.
        """
        try:
            return await asyncio.to_thread(self.registry.get_org, organization)
        except requests.RequestException as e:
            raise AcdpError(f"organization lookup failed: {e}") from e

    async def dns_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """SRV and TXT data for an agent id, with "key"."""
        return await asyncio.to_thread(self.resolver.resolve_agent, agent_id)
