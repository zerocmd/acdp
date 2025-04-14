#!/usr/bin/env python3
"""
Simple API server to handle DNS record updates for agents.
This uses Python's built-in HTTP server instead of Flask.
"""

import http.server
import socketserver
import json
import subprocess
import logging
import os
import urllib.parse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DNSUpdateHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        """Handle POST requests for DNS updates"""
        if self.path == "/update_dns":
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)

            try:
                data = json.loads(post_data)

                # Validate required fields
                required_fields = ["domain", "host", "port"]
                for field in required_fields:
                    if field not in data:
                        self._send_error(400, f"Missing required field: {field}")
                        return

                # Extract data
                domain = data["domain"]
                host = data["host"]
                port = str(data["port"])
                capabilities = data.get("capabilities", "")
                description = data.get("description", "")
                ip_address = data.get("ip_address", "")

                # Call the update script
                try:
                    cmd = [
                        "/usr/local/bin/update_zone.sh",
                        domain,
                        host,
                        port,
                        capabilities,
                        description,
                    ]

                    if ip_address:
                        cmd.append(ip_address)

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
