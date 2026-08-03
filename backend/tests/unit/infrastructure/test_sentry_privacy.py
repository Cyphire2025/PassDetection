from __future__ import annotations

import json

from app.infrastructure.observability.sentry import (
    scrub_sentry_event,
    sentry_init_options,
)


def test_sentry_event_is_allowlisted_and_removes_travel_pii() -> None:
    passenger_id = "11111111-1111-4111-8111-111111111111"
    secrets = (
        "Nipun Vashistha",
        "+919873299928",
        "Z7418523",
        "eyJhbGciOiJIUzI1NiJ9.secret.signature",
        "s3://private/passports/Z7418523-front.jpg",
        "nipun@example.com",
    )
    event = {
        "event_id": "event-1",
        "timestamp": "2026-08-03T00:00:00Z",
        "platform": "python",
        "level": "error",
        "environment": "production",
        "message": f"Failed passport for {secrets[0]} {secrets[2]}",
        "request": {
            "method": "post",
            "url": f"https://tech.gctravels.com/api/v1/passports/{passenger_id}?phone={secrets[1]}",
            "query_string": f"email={secrets[5]}",
            "data": {"passport_number": secrets[2], "phone": secrets[1]},
            "headers": {"authorization": f"Bearer {secrets[3]}"},
            "cookies": {"refresh_token": secrets[3]},
        },
        "transaction": f"POST /api/v1/passports/{passenger_id}",
        "user": {"email": secrets[5], "ip_address": "203.0.113.10"},
        "extra": {"storage_url": secrets[4], "passenger_name": secrets[0]},
        "contexts": {"passport": {"number": secrets[2]}},
        "tags": {"phone": secrets[1]},
        "breadcrumbs": {
            "values": [
                {
                    "timestamp": 1,
                    "type": "http",
                    "category": "request",
                    "level": "info",
                    "message": f"Uploaded {secrets[4]}",
                    "data": {"phone": secrets[1]},
                }
            ]
        },
        "exception": {
            "values": [
                {
                    "type": "RuntimeError",
                    "value": f"Passenger {secrets[0]} passport {secrets[2]}",
                    "mechanism": {"type": "generic", "handled": False, "data": secrets[1]},
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "mobile_resources.py",
                                "function": "download",
                                "lineno": 42,
                                "vars": {"token": secrets[3], "passport": secrets[2]},
                            }
                        ]
                    },
                }
            ]
        },
    }

    scrubbed = scrub_sentry_event(event)
    encoded = json.dumps(scrubbed, sort_keys=True)

    for secret in secrets:
        assert secret not in encoded
    assert passenger_id not in encoded
    assert scrubbed["request"] == {
        "method": "POST",
        "url": "https://tech.gctravels.com/api/v1/passports/{id}",
    }
    assert scrubbed["transaction"] == "POST /api/v1/passports/{id}"
    assert scrubbed["exception"]["values"][0]["type"] == "RuntimeError"
    assert "value" not in scrubbed["exception"]["values"][0]
    assert "vars" not in scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]


def test_sentry_sdk_collection_defaults_are_fail_closed() -> None:
    options = sentry_init_options()

    assert options["send_default_pii"] is False
    assert options["include_local_variables"] is False
    assert options["max_request_body_size"] == "never"
    assert options["before_send"] is scrub_sentry_event
    assert options["before_send_transaction"] is scrub_sentry_event
