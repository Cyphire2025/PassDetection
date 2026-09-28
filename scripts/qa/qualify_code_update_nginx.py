"""Qualify real release routing and request draining on disposable Docker fixtures.

Only uniquely named synthetic containers and their private network are removed.
No application services, credentials, data volumes or external providers are used.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from release_code_update import CodeUpdate, ReleaseError

SERVER = """
import http.server,json,sys,threading
name=sys.argv[1]
holds={}
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_GET(self):
  route=self.path.split('/')
  if route[1]=='release':
   holds.setdefault(route[2],threading.Event()).set()
  body=json.dumps({'release':name,'port':self.server.server_port}).encode()
  self.send_response(200)
  self.send_header('Content-Type','application/json')
  self.send_header('Content-Length',str(len(body)))
  self.end_headers()
  if route[1]=='hold':
   self.wfile.write(body[:1])
   self.wfile.flush()
   if not holds.setdefault(route[2],threading.Event()).wait(40):
    self.close_connection=True
    return
   self.wfile.write(body[1:])
  else:
   self.wfile.write(body)
for port in (8000,3000):
 server=http.server.ThreadingHTTPServer(('0.0.0.0',port),Handler)
 threading.Thread(target=server.serve_forever,daemon=True).start()
threading.Event().wait()
"""

NGINX = """pid /tmp/nginx.pid;
error_log stderr notice;
worker_processes 1;
events { worker_connections 128; }
http {
    access_log off;
    client_body_temp_path /tmp/client_temp;
    proxy_temp_path /tmp/proxy_temp;
    upstream backend { server backend:8000; }
    upstream frontend { server frontend:3000; }
    server {
        listen 8080;
        location /frontend { proxy_pass http://frontend; }
        location / {
            proxy_pass http://backend;
            proxy_buffering off;
            proxy_http_version 1.1;
            proxy_set_header Connection close;
            proxy_read_timeout 45s;
        }
    }
}
"""


def docker(*args: str) -> str:
    result = subprocess.run(["docker", *args], check=True, capture_output=True,
                            text=True, timeout=90)
    return result.stdout.strip()


class FixtureRelease(CodeUpdate):
    """Override production bindings only; route/drain/inspection remain real."""

    def __init__(self, root: Path, nginx: str, original: str) -> None:
        super().__init__("a" * 40, root, root / "unused-manifest.json", source=ROOT)
        self.fixture_nginx = nginx
        self.fixture_original = original
        self.failed_config_checks = 0
        self.drain_scan_observed = threading.Event()
        self.observed_drain_thread: int | None = None
        self.original_nginx = root / "original-nginx.conf"
        self.original_nginx.write_text(NGINX, encoding="utf-8")
        self.record = {"phase": "qualification", "nginx_bindings": {},
                       "serving": {"backend": original, "frontend": original}}

    def container(self, service: str) -> dict:
        if service not in {"nginx", "backend", "frontend"}:
            raise AssertionError("Synthetic qualification attempted production discovery")
        return self.inspect(self.fixture_nginx if service == "nginx" else self.fixture_original)

    def verify_binding(self) -> None:
        # This fixture deliberately has no production Compose/env/recovery files.
        pass

    def run(self, *args: str, **kwargs) -> str:
        try:
            return super().run(*args, **kwargs)
        except ReleaseError:
            if args[-2:] == ("nginx", "-t"):
                self.failed_config_checks += 1
            raise

    def save(self, phase: str) -> None:
        self.record["phase"] = phase

    def nginx_workers(self) -> set[str]:
        workers = super().nginx_workers()
        if threading.get_ident() == self.observed_drain_thread:
            self.drain_scan_observed.set()
        return workers


def request(origin: str, route: str, headers_received: threading.Event | None = None) -> dict:
    with urllib.request.urlopen(origin + route, timeout=45 if headers_received else 3) as response:
        assert response.status == 200
        if headers_received is not None:
            headers_received.set()
        return json.load(response)


def wait_serving(origin: str, expected: str) -> None:
    for attempt in range(60):
        try:
            if all(request(origin, route)["release"] == expected
                   for route in ("/identity", "/frontend")):
                return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(0.1)
    raise AssertionError(f"Synthetic ingress never served {expected} on both upstreams")


def switch_with_held_request(release: FixtureRelease, origin: str, old: str, new: str,
                             expected_old: str, expected_new: str, token: str) -> dict:
    headers = threading.Event()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        held = executor.submit(request, origin, "/hold/" + token, headers)
        try:
            assert headers.wait(10), "Long request did not reach its original upstream"
            assert not held.done(), "Synthetic response was not held open"
            release.route({"backend": new, "frontend": new})
            wait_serving(origin, expected_new)
            started = threading.Event()
            release.drain_scan_observed.clear()

            def drain() -> None:
                release.observed_drain_thread = threading.get_ident()
                started.set()
                release.drain_upstreams({"backend": old, "frontend": old})

            draining = executor.submit(drain)
            assert started.wait(5)
            assert release.drain_scan_observed.wait(10), "Drain did not inspect actual Nginx workers"
            try:
                draining.result(timeout=0.75)
            except concurrent.futures.TimeoutError:
                pass
            else:
                raise AssertionError("Drain returned while an old upstream response was still open")
            assert not held.done(), "The route switch interrupted the held HTTP response"
        finally:
            # Release this exact synthetic request even when qualification fails.
            docker("exec", old, "python", "-c",
                   "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/release/"
                   + token + "',timeout=5).read()")
        result = held.result(timeout=10)
        assert result == {"release": expected_old, "port": 8000}
        draining.result(timeout=12)
    docker("stop", "--time", "2", old)
    wait_serving(origin, expected_new)
    return {"from": expected_old, "to": expected_new, "held_response": result,
            "drain_blocked_until_response_completed": True, "ingress_after_retirement": expected_new}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Pinned Nginx image digest or local image ID")
    parser.add_argument("--python-image", required=True, help="Qualified backend/Python image ID")
    parser.add_argument("--evidence", type=Path,
                        default=ROOT / "outputs/qualification/code-update-nginx-evidence.json")
    args = parser.parse_args()
    # Resolve tags once so every fixture is launched by immutable local ID.
    images = {name: json.loads(docker("image", "inspect", value))[0]["Id"]
              for name, value in (("nginx", args.image), ("python", args.python_image))}
    prefix = "passdetection-code-update-" + uuid.uuid4().hex[:12]
    network = prefix + "-net"
    names = {name: prefix + "-" + name for name in ("old", "new", "nginx")}
    created: list[str] = []
    network_created = False
    with tempfile.TemporaryDirectory(prefix=prefix + "-") as directory:
        root = Path(directory)
        (root / "nginx").mkdir()
        config = root / "nginx/nginx.conf"
        config.write_text(NGINX, encoding="utf-8")
        server = root / "fixture.py"
        server.write_text(SERVER, encoding="utf-8")
        config.chmod(0o644)
        server.chmod(0o644)
        caps = ("--memory", "64m", "--memory-swap", "64m", "--cpus", "0.5",
                "--pids-limit", "64", "--cap-drop", "ALL", "--security-opt", "no-new-privileges")
        try:
            docker("network", "create", network)
            network_created = True
            for name in ("old", "new"):
                aliases = ("--network-alias", "backend", "--network-alias", "frontend") if name == "old" else ()
                docker("create", "--name", names[name], "--network", network, *aliases, *caps,
                       "--mount", f"type=bind,source={server},target=/tmp/fixture.py,readonly",
                       "--entrypoint", "python", images["python"], "-u", "/tmp/fixture.py", name)
                created.append(names[name])
                docker("start", names[name])
            docker("create", "--name", names["nginx"], "--network", network, *caps,
                   "--user", "101:101", "--publish", "127.0.0.1::8080",
                   "--mount", f"type=bind,source={config},target=/etc/nginx/nginx.conf,readonly",
                   "--entrypoint", "nginx", images["nginx"], "-g", "daemon off;")
            created.append(names["nginx"])
            docker("start", names["nginx"])
            details = {name: json.loads(docker("inspect", value))[0] for name, value in names.items()}
            port = details["nginx"]["NetworkSettings"]["Ports"]["8080/tcp"][0]["HostPort"]
            origin = "http://127.0.0.1:" + port
            release = FixtureRelease(root, details["nginx"]["Id"], details["old"]["Id"])
            old, new = details["old"]["Id"], details["new"]["Id"]
            wait_serving(origin, "old")
            checks = [switch_with_held_request(release, origin, old, new, "old", "new", "first")]
            docker("start", old)
            checks.append(switch_with_held_request(release, origin, new, old, "new", "old", "second"))
            docker("start", new)
            valid = config.read_text()
            release.original_nginx.write_text(NGINX + "\ninvalid_synthetic_directive;\n", encoding="utf-8")
            try:
                release.route({"backend": new, "frontend": new})
            except ReleaseError:
                pass
            else:
                raise AssertionError("Invalid Nginx configuration unexpectedly activated")
            assert release.failed_config_checks == 1, "Qualification did not reach a failing real nginx -t"
            assert config.read_text() == valid, "Failed configuration did not restore original file"
            wait_serving(origin, "old")
            report = {"schema_version": 1, "images": images, "switches": checks,
                      "failed_nginx_config_preserved_original": True,
                      "production_changes": False, "synthetic_max_memory_bytes": 3 * 64 * 1024**2}
            args.evidence.parent.mkdir(parents=True, exist_ok=True)
            args.evidence.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
            print(json.dumps(report, indent=2), flush=True)
        finally:
            for name in reversed(created):
                docker("rm", "--force", name)
            if network_created:
                docker("network", "rm", network)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
