"""Exercise the deployed Nginx error includes in an isolated disposable container.

Uses no application data, credentials, networks or named volumes. Only this
script's uniquely named local fixture container is removed at completion.
"""

from __future__ import annotations

import argparse
import json
from http.client import RemoteDisconnected
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CODES = (400, 413, 414, 431, 500, 502, 503, 504)


def docker(*arguments: str) -> str:
    return subprocess.check_output(["docker", *arguments], text=True, stderr=subprocess.PIPE).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, help="Exact already-qualified Nginx image ID/digest")
    options = parser.parse_args()
    name = "passdetection-proxy-errors-" + uuid.uuid4().hex[:10]
    mappings = "/etc/nginx/includes/api-error-pages.inc"
    locations = "/etc/nginx/includes/api-error-locations.inc"
    config = "events {}\nhttp {\nserver { listen 80; client_max_body_size 1k;\n"
    config += f"include {mappings}; include {locations};\n"
    config += "\n".join(f"location = /simulate/{code} {{ return {code}; }}" for code in CODES)
    config += "\nlocation = /simulate/408 { return 408; }"
    config += "\nlocation = /upload { proxy_pass http://127.0.0.1:8081; }"
    config += "\nlocation = /protected { proxy_pass http://127.0.0.1:8081; }"
    config += "\nlocation = /unreachable { proxy_pass http://127.0.0.1:9; proxy_connect_timeout 1s; }"
    config += "\n}\nserver { listen 8081; default_type application/json; return 403 '{\"detail\":\"workflow-specific refusal\"}'; }\n}\n"
    checks = []
    with tempfile.TemporaryDirectory(prefix="passdetection-proxy-errors-") as directory:
        path = Path(directory) / "nginx.conf"
        path.write_text(config, encoding="utf-8")
        started = False
        try:
            docker("run", "--detach", "--rm", "--name", name, "--publish", "127.0.0.1::80",
                   "--mount", f"type=bind,source={path},target=/etc/nginx/nginx.conf,readonly",
                   "--mount", f"type=bind,source={ROOT / 'nginx/conf.d/includes'},target=/etc/nginx/includes,readonly",
                   options.image)
            started = True
            details = json.loads(docker("inspect", name))[0]
            port = details["NetworkSettings"]["Ports"]["80/tcp"][0]["HostPort"]
            origin = f"http://127.0.0.1:{port}"
            def request(route: str, body: bytes | None = None):
                try:
                    response = urllib.request.urlopen(urllib.request.Request(origin + route, data=body), timeout=5)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    return response.status, response.headers, json.load(response)
            for attempt in range(30):
                try:
                    request("/simulate/400")
                    break
                except (urllib.error.URLError, ConnectionError):
                    time.sleep(.1)
            for code in CODES:
                print(f"Checking Nginx generated status {code}", flush=True)
                status, headers, body = request(f"/simulate/{code}?secret=never-reflect")
                assert status == code and body["error"]["code"] and body["error"]["message"]
                assert "secret" not in json.dumps(body)
                assert headers["Content-Type"] == "application/json"
                assert headers["Cache-Control"] == "no-store" and headers["X-Request-ID"]
                checks.append(f"generated-{code}-json")
            # Nginx terminates408 connections in ngx_http_finalize_request before
            # error_page processing. This is a network failure, not a JSON contract.
            try:
                request("/simulate/408")
            except RemoteDisconnected:
                checks.append("client-timeout-408-closes-connection-as-documented")
            else:
                raise AssertionError("Unexpected Nginx408 transport behavior")
            status, _, body = request("/upload", b"x" * 2048)
            assert status == 413 and body["error"]["code"] == "PAYLOAD_TOO_LARGE"
            checks.append("actual-oversize-413")
            status, _, body = request("/unreachable")
            assert status == 502 and body["error"]["code"] == "BAD_GATEWAY"
            checks.append("actual-upstream-connect-failure-502")
            status, _, body = request("/protected")
            assert status == 403 and body == {"detail": "workflow-specific refusal"}
            checks.append("upstream-business-response-preserved")
            report = {"image": details["Image"], "checks": checks, "scope": "Isolated local Nginx include behavior; no VPS changes"}
            (ROOT / "docs/remediation/proxy-error-evidence.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, indent=2))
        finally:
            if started:
                docker("stop", "--time", "2", name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
