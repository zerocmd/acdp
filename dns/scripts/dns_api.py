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

ZONE = os.environ.get("AGENT_ZONE", "agents.local")
MAX_BODY_BYTES = 16 * 1024
_LABEL = r"[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
DOMAIN_RE = re.compile(rf"^({_LABEL}\.)+{re.escape(ZONE)}$")
HOST_RE = re.compile(rf"^{_LABEL}(\.{_LABEL})*\.?$")
CAPS_RE = re.compile(r"^[A-Za-z0-9_,-]{0,240}$")
PROTO_RE = re.compile(r"^[A-Za-z0-9._/,+-]{0,120}$")
PATH_RE = re.compile(r"^(/[A-Za-z0-9._~-]+)*/?$")
VERSION_RE = re.compile(r"^\d+(\.\d+){0,2}$")


class ValidationError(ValueError):
    pass


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
    if not DOMAIN_RE.fullmatch(domain):
        raise ValidationError(f"domain must be a name under {ZONE}")
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
    }


class DNSUpdateHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        """Handle POST requests for DNS updates"""
        if self.path == "/update_dns":
            try:
                content_length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                self._send_error(411, "Content-Length required")
                return
            if content_length <= 0:
                self._send_error(400, "Empty request body")
                return
            if content_length > MAX_BODY_BYTES:
                self._send_error(413, f"Body larger than {MAX_BODY_BYTES} bytes")
                return
            post_data = self.rfile.read(content_length)

            try:
                data = validate_update(json.loads(post_data))

                # Call the update script (argument vector, no shell)
                try:
                    cmd = [
                        "/usr/local/bin/update_zone.sh",
                        data["domain"],
                        data["host"],
                        data["port"],
                        data["capabilities"],
                        data["description"],
                        data["ip_address"],
                        data["a2a"],
                        data["protocols"],
                        data["version"],
                    ]

                    result = subprocess.run(
                        cmd, capture_output=True, text=True, check=True
                    )

                    logger.info(f"DNS update result: {result.stdout}")
                    if result.stderr:
                        logger.warning(f"DNS update warnings: {result.stderr}")

                    self._send_response(
                        200,
                        {
                            "status": "success",
                            "message": "DNS records updated successfully",
                        },
                    )

                except subprocess.CalledProcessError as e:
                    logger.error(f"DNS update failed: {e.stderr}")
                    self._send_error(500, f"Failed to update DNS records: {e.stderr}")

            except json.JSONDecodeError:
                self._send_error(400, "Invalid JSON data")
            except ValidationError as e:
                self._send_error(400, str(e))
        else:
            self._send_error(404, "Not found")

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
    handler = DNSUpdateHandler
    with socketserver.TCPServer(("", port), handler) as httpd:
        logger.info(f"DNS API server started on port {port}")
        httpd.serve_forever()


if __name__ == "__main__":
    run_server()
