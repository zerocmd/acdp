#!/usr/bin/env python3
"""
Simple API server to handle DNS record updates for agents.
This uses Python's built-in HTTP server instead of Flask.
"""

import http.server
import ipaddress
import socketserver
import json
import re
import subprocess
import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 16 * 1024
_LABEL = r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
ZONES = {
    z.strip().lower()
    for z in os.environ.get(
        "ACDP_ZONES", os.environ.get("AGENT_ZONE", "agents.local")
    ).split(",")
    if z.strip()
}
ZONE_SUFFIXES = [
    s.strip().lower()
    for s in os.environ.get("ACDP_ZONE_SUFFIXES", ".example,.local").split(",")
    if s.strip()
]
ZONE_DIR = os.environ.get("ACDP_ZONE_DIR", "/var/cache/bind/zones")
ADD_ZONE_SCRIPT = "/usr/local/bin/add_zone.sh"
NAME_RE = re.compile(rf"^({_LABEL}\.)*{_LABEL}$")
KEY_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
# Argument order of update_zone.sh.
SCRIPT_FIELDS = (
    "domain", "host", "port", "capabilities", "description", "ip_address",
    "a2a", "protocols", "version", "key", "zone",
)
HOST_RE = re.compile(rf"^{_LABEL}(\.{_LABEL})*\.?$")
CAPS_RE = re.compile(r"^[A-Za-z0-9_,-]{0,240}$")
PROTO_RE = re.compile(r"^[A-Za-z0-9._/,+-]{0,120}$")
PATH_RE = re.compile(r"^(/[A-Za-z0-9._~-]+)*/?$")
VERSION_RE = re.compile(r"^\d+(\.\d+){0,2}$")


class ValidationError(ValueError):
    pass


def load_zones(zone_dir: str = ZONE_DIR) -> None:
    """Add zones that add_zone.sh created in an earlier run.

    Args:
        zone_dir: Directory that holds the db.<zone> files.
    """
    if not os.path.isdir(zone_dir):
        return
    for name in os.listdir(zone_dir):
        if name.startswith("db.") and not name.endswith(".jnl"):
            ZONES.add(name[3:])


def zone_for(domain: str) -> str:
    """Return the longest known zone that contains the domain.

    Args:
        domain: A lowercase DNS name.

    Returns:
        The zone name.

    Raises:
        ValidationError: No known zone contains the domain.
    """
    matches = [z for z in ZONES if domain.endswith("." + z)]
    if not matches:
        raise ValidationError(f"domain must be a name under one of: {sorted(ZONES)}")
    return max(matches, key=len)


def validate_zone(zone: str) -> str:
    """Check a zone name for POST /zones.

    Args:
        zone: The requested zone name.

    Returns:
        The lowercase zone name.

    Raises:
        ValidationError: The name is malformed or not under an allowed suffix.
    """
    zone = str(zone).lower()
    if not NAME_RE.fullmatch(zone) or "." not in zone:
        raise ValidationError("zone must be a DNS name with at least two labels")
    for suffix in ZONE_SUFFIXES:
        if suffix.startswith("."):
            if zone.endswith(suffix):
                return zone
        elif zone == suffix or zone.endswith("." + suffix):
            return zone
    raise ValidationError(f"zone must end with one of: {ZONE_SUFFIXES}")


def validate_update(data):
    """Validate and normalise a DNS update request.

    Every value ends up inside an nsupdate script, where a quote or newline would let
    a caller inject arbitrary zone updates, so values are checked against strict
    patterns and the free-text description is stripped of quotes, backslashes and
    control characters.
    """
    if not isinstance(data, dict):
        raise ValidationError("Expected a JSON object")
    for field in ("domain", "host", "port"):
        if field not in data:
            raise ValidationError(f"Missing required field: {field}")

    domain = str(data["domain"]).lower()
    if not NAME_RE.fullmatch(domain):
        raise ValidationError("domain must be a DNS name")
    zone = zone_for(domain)
    host = str(data["host"])
    if not HOST_RE.fullmatch(host):
        raise ValidationError("host must be a DNS name")
    try:
        port = int(data["port"])
    except (TypeError, ValueError):
        raise ValidationError("port must be an integer")
    if not 1 <= port <= 65535:
        raise ValidationError("port out of range")

    capabilities = str(data.get("capabilities", ""))
    if not CAPS_RE.fullmatch(capabilities):
        raise ValidationError("capabilities may contain only letters, digits, _ , -")
    protocols = str(data.get("protocols", ""))
    if not PROTO_RE.fullmatch(protocols):
        raise ValidationError("protocols contains invalid characters")
    a2a_path = str(data.get("a2a", ""))
    if a2a_path and not PATH_RE.fullmatch(a2a_path):
        raise ValidationError("a2a must be a URL path such as /.well-known/agent-card.json")
    version = str(data.get("version", "1.0"))
    if not VERSION_RE.fullmatch(version):
        raise ValidationError("version must look like 1.1")

    description = "".join(
        ch for ch in str(data.get("description", "")) if ch.isprintable() and ch not in '"\\'
    )[:200]

    ip_address = str(data.get("ip_address", ""))
    if ip_address:
        try:
            ipaddress.ip_address(ip_address)
        except ValueError:
            raise ValidationError("ip_address is not a valid IP address")

    key = str(data.get("key", ""))
    if key and not KEY_RE.fullmatch(key):
        raise ValidationError("key must be a 43-character base64url fingerprint")

    return {
        "domain": domain,
        "host": host,
        "port": str(port),
        "capabilities": capabilities,
        "description": description,
        "ip_address": ip_address,
        "a2a": a2a_path,
        "protocols": protocols,
        "version": version,
        "key": key,
        "zone": zone,
    }


class DNSUpdateHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        """Route POST /update_dns and POST /zones."""
        routes = {"/update_dns": self._update_dns, "/zones": self._add_zone}
        handler = routes.get(self.path)
        if handler is None:
            self._send_error(404, "Not found")
            return
        data = self._read_json()
        if data is None:
            return
        try:
            handler(data)
        except ValidationError as e:
            self._send_error(400, str(e))

    def _read_json(self):
        """Read and parse the JSON body. Send the error response on failure."""
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            self._send_error(411, "Content-Length required")
            return None
        if content_length <= 0:
            self._send_error(400, "Empty request body")
            return None
        if content_length > MAX_BODY_BYTES:
            self._send_error(413, f"Body larger than {MAX_BODY_BYTES} bytes")
            return None
        try:
            return json.loads(self.rfile.read(content_length))
        except json.JSONDecodeError:
            self._send_error(400, "Invalid JSON data")
            return None

    def _update_dns(self, raw):
        data = validate_update(raw)
        cmd = ["/usr/local/bin/update_zone.sh", *[data[k] for k in SCRIPT_FIELDS]]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"DNS update failed: {e.stderr}")
            self._send_error(500, f"Failed to update DNS records: {e.stderr}")
            return
        logger.info(f"DNS update result: {result.stdout}")
        if result.stderr:
            logger.warning(f"DNS update warnings: {result.stderr}")
        self._send_response(
            200, {"status": "success", "message": "DNS records updated successfully"}
        )

    def _add_zone(self, raw):
        if not isinstance(raw, dict) or "zone" not in raw:
            raise ValidationError("Missing required field: zone")
        zone = validate_zone(raw["zone"])
        try:
            result = subprocess.run(
                [ADD_ZONE_SCRIPT, zone, ZONE_DIR],
                capture_output=True, text=True, check=True,
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"Zone creation failed for {zone}: {e.stderr}")
            self._send_error(500, f"Failed to create zone: {e.stderr}")
            return
        ZONES.add(zone)
        self._send_response(
            200, {"status": "success", "zone": zone, "result": result.stdout.strip()}
        )

    def _send_response(self, status_code, data):
        """Send a JSON response"""
        self.send_response(status_code)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _send_error(self, status_code, message):
        """Send an error response"""
        self._send_response(status_code, {"status": "error", "message": message})


def run_server(port=8053):
    """Run the HTTP server"""
    load_zones()
    handler = DNSUpdateHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        logger.info(f"DNS API server started on port {port}")
        httpd.serve_forever()


if __name__ == "__main__":
    run_server()
