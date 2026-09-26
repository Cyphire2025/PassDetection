"""Prove retained OCI digest retrieval locally; does not issue or fake signatures."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from release_artifacts import archive_config, validate_local_config, verify_image_bytes

REGISTRY = "registry:3@sha256:852b3e4d378c426dda6b318fe9d9bfe8e92a0eccb9926671ec3d3ea17a196696"


def docker(*args: str) -> str:
    return subprocess.check_output(["docker", *args], text=True).strip()


def main() -> None:
    name = "passdetection-retrieval-" + uuid.uuid4().hex[:10]
    started = False
    try:
        # Registry binds only the Docker engine's loopback. Host networking keeps
        # the daemon pull path identical on native Linux and Docker Desktop's VM.
        port = str(52000 + int(uuid.uuid4().hex[:4], 16) % 12000)
        docker("run", "--detach", "--rm", "--name", name, "--network", "host",
               "--env", f"REGISTRY_HTTP_ADDR=127.0.0.1:{port}", "--env", "REGISTRY_HTTP_DEBUG_ADDR=127.0.0.1:0",
               "--tmpfs", "/var/lib/registry", REGISTRY)
        started = True
        for attempt in range(50):
            try:
                assert json.loads(docker("exec", name, "wget", "-q", "-O", "-", f"http://127.0.0.1:{port}/v2/")) == {}
                break
            except (OSError, subprocess.CalledProcessError):
                if attempt == 49:
                    raise
                time.sleep(.1)
        inventory = []
        def read_fixture_manifest(reference: str) -> list:
            # Docker Desktop's daemon loopback differs from Windows CLI
            # loopback. Read real registry metadata from the fixture namespace;
            # production uses docker manifest inspect against authenticated GHCR.
            digest = reference.rsplit("@", 1)[1]
            def fetch(identifier: str) -> dict:
                return json.loads(docker("exec", name, "wget", "-q", "-O", "-", "--header",
                    "Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json",
                    f"http://127.0.0.1:{port}/v2/synthetic/manifests/{identifier}"))
            document = fetch(digest)
            if "manifests" in document:
                return [{"Descriptor": descriptor, "OCIManifest": fetch(descriptor["digest"])}
                        for descriptor in document["manifests"]]
            return [{"OCIManifest": document}]
        with tempfile.TemporaryDirectory(prefix="passdetection-retrieval-") as directory:
            work = Path(directory)
            for release in ("a", "b"):
                revision = release * 40
                (work / "Dockerfile").write_text("FROM scratch\nLABEL org.opencontainers.image.revision=" + revision + "\nCOPY receipt /receipt\n")
                (work / "receipt").write_text("synthetic release " + revision)
                reference = f"127.0.0.1:{port}/synthetic:{revision}"
                docker("build", "--tag", reference, str(work))
                archive = work / f"{release}.tar"
                docker("save", "--output", str(archive), reference)
                config_id, configuration = archive_config(archive, reference)
                validate_local_config(json.loads(docker("image", "inspect", reference))[0], configuration)
                docker("load", "--input", str(archive))
                docker("push", reference)
                details = json.loads(docker("image", "inspect", reference))[0]
                digest = next(ref for ref in details["RepoDigests"] if ref.startswith(f"127.0.0.1:{port}/synthetic@"))
                inventory.append({"reference": digest, "image_id": config_id, "revision": revision})
            # Retrieve the previous release after the next release is published.
            for entry in reversed(inventory):
                verify_image_bytes(**entry, pull=True, manifest_reader=read_fixture_manifest)
            for mutation in ("image_id", "revision"):
                bad = dict(inventory[0])
                bad[mutation] = "sha256:" + "0" * 64 if mutation == "image_id" else "0" * 40
                try:
                    verify_image_bytes(**bad, pull=True, manifest_reader=read_fixture_manifest)
                except ValueError:
                    continue
                raise AssertionError("Mismatched artifact was accepted")
        receipt = {"result": "passed", "registry_image": REGISTRY, "releases": inventory,
                   "assertions": ["previous release retrieved after successor publication", "digest and config readback",
                                  "archive save/load preserves hashed config and filesystem layers",
                                  "registry config verified independently of Docker local index/config ID",
                                  "wrong config rejected", "wrong source revision rejected"],
                   "limitation": "Synthetic local OCI transport only; real registry metadata is read inside the fixture namespace to bridge Docker Desktop loopback. Both local store-ID shapes also have unit tests; no second physical Docker engine was provisioned. GitHub OIDC issuance, signature verification and registry retention are separate external gates."}
        path = ROOT / "docs/remediation/artifact-retrieval-evidence.json"
        path.write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt, indent=2))
    finally:
        # This tmpfs-only fixture owns no application volumes or data.
        if started and docker("ps", "--quiet", "--filter", f"name=^/{name}$"):
            docker("stop", name)


if __name__ == "__main__":
    main()
