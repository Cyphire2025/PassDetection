"""Offline production credential mount contracts; no Docker or secrets are read."""

from pathlib import Path

import yaml


class ResetList(list):
    pass


class OverrideList(list):
    pass


class ComposeLoader(yaml.SafeLoader):
    pass


ComposeLoader.add_constructor(
    "!reset", lambda loader, node: ResetList(loader.construct_sequence(node, deep=True))
)
ComposeLoader.add_constructor(
    "!override", lambda loader, node: OverrideList(loader.construct_sequence(node, deep=True))
)


def _compose(filename):
    root = Path(__file__).resolve().parents[4]
    return yaml.load((root / filename).read_text(), Loader=ComposeLoader)


def test_general_worker_replaces_source_bind_with_one_read_only_external_credential_directory():
    base = _compose("docker-compose.yml")
    production = _compose("docker-compose.prod.yml")
    assert "./backend:/app" in base["services"]["worker"]["volumes"]
    worker = production["services"]["worker"]
    assert isinstance(worker["volumes"], OverrideList)
    assert worker["volumes"] == [
        {
            "type": "bind",
            "source": "/opt/global-connect-secrets/fcm",
            "target": "/run/gc-fcm",
            "read_only": True,
            "bind": {"create_host_path": False},
        }
    ]
    assert (
        worker["environment"]["MOBILE_PUSH_FCM_CREDENTIALS_FILE"]
        == "/run/gc-fcm/service-account.json"
    )
    assert "MOBILE_PUSH_PROVIDER" not in worker["environment"]


def test_other_application_services_receive_no_credential_or_development_source_mount():
    services = _compose("docker-compose.prod.yml")["services"]
    for name in (
        "backend",
        "email-worker",
        "my-photos-worker",
        "email-ai-worker",
        "email-beat",
        "extraction-worker",
        "verification-worker",
        "visa-ai-worker",
    ):
        assert isinstance(services[name]["volumes"], ResetList), name
        assert services[name]["volumes"] == [], name
    for name, service in services.items():
        if name != "worker":
            assert "MOBILE_PUSH_FCM_CREDENTIALS_FILE" not in service.get("environment", {}), name
            assert all(
                not isinstance(volume, dict) or volume.get("target") != "/run/gc-fcm"
                for volume in service.get("volumes", [])
            ), name
