#!/usr/bin/env python3
"""Tiny HTTP server that serves synthetic Prometheus metrics for testing."""

from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

METRICS_FILE = Path(__file__).parent / "synthetic_metrics.txt"


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/metrics":
            content = METRICS_FILE.read_text()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.end_headers()
            self.wfile.write(content.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress request logs to keep test output clean
        pass


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 9999), MetricsHandler)
    print("Fixture server listening on :9999")
    server.serve_forever()
