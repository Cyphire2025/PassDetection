"""Synthetic policy inputs; never render Compose or contact a Docker daemon."""

import copy
import pickle
import unittest
from typing import get_type_hints

import compose_runtime_clients as clients
import compose_runtime_contract as contract
import compose_runtime_values as values
import compose_runtime_workers as workers
import verify_compose_runtime as facade


def frontend():
    return {
        "frontend": {
            "environment": {"NEXT_PUBLIC_APP_URL": "https://synthetic.example.invalid"},
            "build": {"args": {"NEXT_PUBLIC_API_BASE_URL": "", "NEXT_PUBLIC_DEV_APP_URL": ""}},
        }
    }


def worker_services():
    services = {}
    for name, parts in contract.WORKER_QUEUE_CONTRACTS.items():
        services[name] = {
            "command": [
                "sh",
                "-c",
                f"exec celery worker --hostname={parts[0]}%h -Q {','.join(parts[1:])}",
            ],
            "healthcheck": {
                "test": ["CMD-SHELL", "python -m worker_healthcheck " + " ".join(parts)]
            },
        }
    services["email-beat"] = {
        "command": "celery -A synthetic beat --loglevel=INFO",
        "healthcheck": {
            "test": ["CMD", "python", "-m", "app.infrastructure.email.beat_healthcheck"]
        },
    }
    return services


class FrontendPolicyTests(unittest.TestCase):
    def test_existing_projection_aliases_keep_their_runtime_type_and_import_contract(self):
        for name in (
            "_command_text",
            "_volume_targets",
            "_healthcheck_text",
            "_published_port_targets",
            "_require",
        ):
            function = getattr(values, name)
            with self.subTest(name=name):
                self.assertIs(getattr(facade, name), function)
                self.assertIs(pickle.loads(pickle.dumps(function)), function)
                self.assertTrue(get_type_hints(function))

    def test_same_origin_public_configuration_remains_accepted(self):
        clients.validate_frontend(frontend())

    def test_server_credentials_and_env_files_never_enter_frontend_runtime_or_build(self):
        baseline = frontend()
        variants = []
        for location in ("runtime", "build"):
            value = copy.deepcopy(baseline)
            target = (
                value["frontend"]["environment"]
                if location == "runtime"
                else value["frontend"]["build"]["args"]
            )
            target["APP_SECRET_KEY"] = "synthetic-sensitive-placeholder"
            variants.append(value)
        value = copy.deepcopy(baseline)
        value["frontend"]["env_file"] = [".env"]
        variants.append(value)
        for value in variants:
            with self.subTest(value=value), self.assertRaises(AssertionError) as error:
                clients.validate_frontend(value)
            self.assertNotIn("synthetic-sensitive-placeholder", str(error.exception))

    def test_external_api_and_development_origin_cannot_be_baked_into_production(self):
        for name in ("NEXT_PUBLIC_API_BASE_URL", "NEXT_PUBLIC_DEV_APP_URL"):
            value = frontend()
            value["frontend"]["build"]["args"][name] = "https://synthetic-wrong.example.invalid"
            with self.subTest(name=name), self.assertRaises(AssertionError):
                clients.validate_frontend(value)

    def test_actual_owned_runtime_source_files_keep_their_security_contracts(self):
        clients.validate_runtime_source_files(
            contract.BACKEND_DOCKERFILE,
            contract.GUNICORN_CONFIG,
            contract.FRONTEND_DOCKERIGNORE,
            contract.BACKEND_DOCKERIGNORE,
        )


class WorkerQueuePolicyTests(unittest.TestCase):
    def test_exact_existing_shell_worker_shapes_keep_every_reviewed_queue(self):
        workers.validate_workers(worker_services())

    def test_lookalike_queue_cannot_satisfy_the_required_queue_contract(self):
        services = worker_services()
        services["ecr-worker"]["command"][2] = services["ecr-worker"]["command"][2].replace(
            "-Q ecr_checks",
            "-Q ecr_checks_backup",
        )
        with self.assertRaises(AssertionError):
            workers.validate_workers(services)

    def test_required_queue_in_an_unrelated_argument_does_not_prove_consumption(self):
        services = worker_services()
        services["ecr-worker"]["command"][2] = services["ecr-worker"]["command"][2].replace(
            "-Q ecr_checks",
            "--logfile=ecr_checks -Q other_queue",
        )
        with self.assertRaises(AssertionError):
            workers.validate_workers(services)

    def test_supported_queue_option_shapes_keep_exact_membership(self):
        commands = (
            ["celery", "worker", "-Q", "ecr_checks"],
            ["celery", "worker", "--queues=ecr_checks"],
            ["celery", "worker", "--queues", "ecr_checks"],
            ["celery", "worker", "-Q=ecr_checks"],
            ["sh", "-c", "exec celery worker -Q ecr_checks"],
            'sh -c "exec celery worker -Q ecr_checks"',
            "celery worker -Q ecr_checks",
        )
        for command in commands:
            with self.subTest(command=command):
                self.assertEqual(workers._worker_queues({"command": command}), {"ecr_checks"})

    def test_missing_duplicate_empty_extra_or_malformed_queue_options_fail_closed(self):
        commands = (
            None,
            "celery worker",
            "celery worker -Q",
            "celery worker -Q ecr_checks --queues=other",
            "celery worker -Q 'ecr_checks",
            "celery worker -Q ecr_checks,other",
            ["celery", "worker", "-Q", ""],
        )
        for command in commands:
            with self.subTest(command=command):
                try:
                    queues = workers._worker_queues({"command": command})
                except AssertionError:
                    continue
                self.assertNotEqual(queues, {"ecr_checks"})


if __name__ == "__main__":
    unittest.main()
