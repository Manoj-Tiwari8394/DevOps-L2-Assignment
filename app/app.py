#!/usr/bin/env python3
"""Small dependency-free HTTP application with Prometheus metrics and JSON logs."""

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock


START_TIME = time.time()
METRICS_LOCK = Lock()
REQUEST_COUNT = {}
REQUEST_DURATION = {}


def metric_key(method, path, status):
    return method, path, str(status)


def observe(method, path, status, duration):
    key = metric_key(method, path, status)
    with METRICS_LOCK:
        REQUEST_COUNT[key] = REQUEST_COUNT.get(key, 0) + 1
        REQUEST_DURATION[key] = REQUEST_DURATION.get(key, 0.0) + duration


def labels(method, path, status):
    return (
        'method="%s",path="%s",status="%s"'
        % (method, path.replace("\\", "\\\\").replace('"', '\\"'), status)
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "devops-l2-app/1.0"

    def log_message(self, _format, *_args):
        # Access logs are emitted as structured JSON in do_GET.
        return

    def do_GET(self):
        started = time.perf_counter()
        path = self.path.split("?", 1)[0]
        status = 200
        body = b""
        content_type = "application/json"

        if path == "/":
            body = json.dumps(
                {
                    "service": "devops-l2-sample-app",
                    "message": "Hello from the Docker Compose observability demo",
                    "version": os.environ.get("APP_VERSION", "1.0.0"),
                }
            ).encode()
        elif path == "/health":
            body = b'{"status":"ok"}'
        elif path == "/metrics":
            content_type = "text/plain; version=0.0.4"
            body = render_metrics().encode()
        else:
            status = 404
            body = b'{"error":"not_found"}'

        duration = time.perf_counter() - started
        observe(self.command, path, status, duration)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self.wfile.flush()

        print(
            json.dumps(
                {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "service": "sample-app",
                    "method": self.command,
                    "path": path,
                    "status": status,
                    "bytes": len(body),
                    "duration_ms": round(duration * 1000, 3),
                    "client": self.client_address[0],
                    "user_agent": self.headers.get("User-Agent", ""),
                },
                separators=(",", ":"),
            ),
            flush=True,
        )


def render_metrics():
    lines = [
        "# HELP app_info Information about the sample application",
        "# TYPE app_info gauge",
        'app_info{version="%s"} 1' % os.environ.get("APP_VERSION", "1.0.0"),
        "# HELP app_uptime_seconds Application uptime in seconds",
        "# TYPE app_uptime_seconds gauge",
        "app_uptime_seconds %.3f" % (time.time() - START_TIME),
        "# HELP http_requests_total Total HTTP requests handled",
        "# TYPE http_requests_total counter",
        "# HELP http_request_duration_seconds_sum HTTP request duration sum",
        "# TYPE http_request_duration_seconds_sum counter",
    ]
    with METRICS_LOCK:
        for key, count in sorted(REQUEST_COUNT.items()):
            method, path, status = key
            label_text = labels(method, path, status)
            lines.append("http_requests_total{%s} %d" % (label_text, count))
            lines.append(
                "http_request_duration_seconds_sum{%s} %.9f"
                % (label_text, REQUEST_DURATION[key])
            )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(
        json.dumps(
            {"service": "sample-app", "event": "started", "port": port},
            separators=(",", ":"),
        ),
        flush=True,
    )
    server.serve_forever()
