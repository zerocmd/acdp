"""DNS resolution utilities for agent discovery."""

import dns.resolver
import socket
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class DNSResolver:
    """Utility for resolving agent information via DNS."""

    def __init__(self, dns_server="bind", dns_port=53):
        """Initialize with DNS server details."""
        self.dns_server = dns_server
        self.dns_port = dns_port
        self.resolver = dns.resolver.Resolver()

        # Convert hostname to IP address if needed
        try:
            # Check if dns_server is already an IP address
            socket.inet_aton(dns_server)  # This will raise an exception if not an IP
            self.dns_server_ip = dns_server
        except socket.error:
            # It's not an IP address, try to resolve it
            try:
                logger.info(f"Resolving DNS server hostname: {dns_server}")
                self.dns_server_ip = socket.gethostbyname(dns_server)
                logger.info(
                    f"Resolved DNS server {dns_server} to IP: {self.dns_server_ip}"
                )
            except socket.gaierror as e:
                # Fallback to a default if we can't resolve
                logger.warning(
                    f"Could not resolve DNS server {dns_server}: {e}. Using default: 127.0.0.1"
                )
                self.dns_server_ip = "127.0.0.1"

        # Set the nameserver IP
        self.resolver.nameservers = [self.dns_server_ip]
        self.resolver.port = dns_port
        logger.info(
            f"Initialized DNS resolver with nameserver: {self.dns_server_ip}:{dns_port}"
        )

    def resolve_agent(self, domain: str) -> Optional[Dict]:
        """
        Resolve an agent by domain name.

        Args:
            domain: The agent's domain name

        Returns:
            Dict containing agent information or None if not found
        """
        try:
            # Get SRV record for service endpoint
            srv_record = self._get_srv_record(domain)
            if not srv_record:
                logger.warning(f"No SRV record found for {domain}")
                return None

            host, port = srv_record

            # Get TXT record for capabilities and metadata
            txt_record = self._get_txt_record(domain)
            capabilities = []
            description = ""
            version = "1.0"

            if txt_record:
                # Parse TXT record data
                for item in txt_record:
                    if item.startswith("caps="):
                        capabilities = item[5:].split(",")
                    elif item.startswith("desc="):
                        description = item[5:]
                    elif item.startswith("ver="):
                        version = item[4:]

            # Construct agent info
            agent_info = {
                "id": domain,
                "host": host,
                "port": port,
                "capabilities": capabilities,
                "description": description,
                "version": version,
                "source": "dns",
            }

            return agent_info

        except Exception as e:
            logger.error(f"Error resolving agent {domain}: {e}")
            return None

    def discover_agents(self, domain_suffix="agents.local") -> List[Dict]:
        """
        Discover all agents in a domain.

        This is more complex and would typically require a zone transfer
        or other discovery mechanism. For simplicity, we'll assume we
        know the domain suffix and try to query for known agents.

        Args:
            domain_suffix: The domain suffix to search in

        Returns:
            List of agent information dictionaries
        """
        # In a real implementation, we would use DNS discovery mechanisms
        # For now, we'll return an empty list as this is complex to implement
        # without proper DNS zone transfer capabilities
        logger.warning("DNS-based agent discovery not fully implemented")
        return []

    def _get_srv_record(self, domain: str) -> Optional[Tuple[str, int]]:
        """
        Get SRV record for an agent.

        Args:
            domain: The agent's domain name

        Returns:
            Tuple of (host, port) or None if not found
        """
        try:
            service_name = f"_llm-agent._tcp.{domain}"
            logger.debug(f"Looking up SRV record for {service_name}")
            answers = self.resolver.resolve(service_name, "SRV")

            if answers:
                # Get the first SRV record
                srv = answers[0]
                return str(srv.target).rstrip("."), srv.port

            return None
        except Exception as e:
            logger.error(f"Error getting SRV record for {domain}: {e}")
            return None

    def _get_txt_record(self, domain: str) -> Optional[List[str]]:
        """
        Get TXT record for an agent.

        Args:
            domain: The agent's domain name

        Returns:
            List of TXT record strings or None if not found
        """
        try:
            service_name = f"_llm-agent._tcp.{domain}"
            logger.debug(f"Looking up TXT record for {service_name}")
            answers = self.resolver.resolve(service_name, "TXT")

            if answers:
                # Parse TXT records
                txt_data = []
                for rdata in answers:
                    for txt_string in rdata.strings:
                        txt_data.append(txt_string.decode("utf-8"))
                return txt_data

            return None
        except Exception as e:
            logger.error(f"Error getting TXT record for {domain}: {e}")
            return None
