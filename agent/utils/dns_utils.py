import requests
import logging
import socket
import os
import time

logger = logging.getLogger(__name__)


def register_dns(domain, host, port, capabilities="", description=""):
    """
    Register agent in DNS by calling the DNS update API

    Args:
        domain: The domain name for the agent (e.g., agent1.agents.local)
        host: The hostname where the agent is running
        port: The port the agent is listening on
        capabilities: Comma-separated list of capabilities
        description: Short description of the agent
    """
    dns_server = os.environ.get("DNS_API_URL", "http://bind:8053")

    # Add retry logic
    max_retries = 5
    retry_delay = 5  # seconds

    for attempt in range(max_retries):
        try:
            # Try to get the IP address
            try:
                ip_address = socket.gethostbyname(host)
                logger.info(f"Resolved {host} to {ip_address}")
            except:
                ip_address = "127.0.0.1"  # Default to localhost if resolution fails
                logger.warning(f"Could not resolve {host}, using {ip_address}")

            # Prepare the data
            data = {
                "domain": domain,
                "host": host,
                "port": port,
                "capabilities": capabilities,
                "description": description,
                "ip_address": ip_address,
            }

            logger.info(
                f"Attempting to register DNS records for {domain} (attempt {attempt+1}/{max_retries})"
            )
            logger.info(f"DNS API URL: {dns_server}/update_dns")
            logger.info(f"Registration data: {data}")

            # Send the update request
            response = requests.post(f"{dns_server}/update_dns", json=data, timeout=30)

            response_text = response.text
            logger.info(f"DNS registration response: {response_text}")

            response.raise_for_status()
            result = response.json()

            if result.get("status") == "success":
                logger.info(f"Successfully registered DNS records for {domain}")
                return True
            else:
                logger.error(f"Failed to register DNS: {result.get('message')}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    return False

        except Exception as e:
            logger.error(f"Error registering with DNS: {str(e)}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                return False

    return False
