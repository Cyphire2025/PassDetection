"""Exercise configured collection over HTTP on the isolated local audit stack.

Creates only uniquely named synthetic review groups and retains them for manual
inspection. It never uploads a passport personal details page, so OCR and
external AI verification are not invoked. Run with backend/.venv Python.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import json
import secrets
import struct
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
MAX_BYTES = 2 * 1024 * 1024
REQUIRED_FIELD_NAMES = (
    "base_city", "nearest_domestic_airport", "departure_city", "staff_code",
    "agent_employee_code", "designation", "agency_dealership_name", "meal_preference",
    "relation_with_qualifier",
)


def totp(secret: str) -> str:
    digest = hmac.new(
        base64.b32decode(secret), struct.pack("!Q", int(time.time()) // 30), hashlib.sha1,
    ).digest()
    offset = digest[-1] & 15
    return f"{(struct.unpack('!I', digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def synthetic_cover(label: str) -> bytes:
    image = Image.new("RGB", (540, 760), "#172c47")
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((24, 24, 516, 736), outline="#c7ae73", width=3)
    drawing.text((65, 290), "SYNTHETIC QA ONLY", fill="#ffffff", font_size=28)
    drawing.text((65, 350), label, fill="#c7ae73", font_size=24)
    drawing.text((65, 430), "No personal information", fill="#ffffff", font_size=22)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--origin", default="http://localhost:3000")
    parser.add_argument("--reuse-manual-token", help="Reuse a synthetic manual review link from an interrupted run")
    args = parser.parse_args()
    parsed = urlsplit(args.api)
    if parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.scheme != "http":
        raise RuntimeError("This fixture runner only accepts a local HTTP audit API.")

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    output = ROOT / "outputs" / "upload-configuration-http" / run_id
    output.mkdir(parents=True, exist_ok=False)
    report: dict = {"run_id": run_id, "api": args.api, "checks": [], "groups": [], "submissions": []}
    seed = json.loads((ROOT / "outputs/dashboard-qa/synthetic-seed.json").read_text(encoding="utf-8-sig"))
    account = seed["accounts"]["webkit"]
    if not account["email"].endswith("@example.test"):
        raise RuntimeError("Synthetic QA account required.")

    def record(name: str, **facts) -> None:
        report["checks"].append({"name": name, "passed": True, **facts})
        print("PASS: " + name, flush=True)

    def request(client: httpx.Client, method: str, path: str, *, expected: int = 200, **kwargs) -> httpx.Response:
        response = client.request(method, path, **kwargs)
        if response.status_code != expected:
            detail = "non-JSON error"
            if response.headers.get("content-type", "").startswith("application/json"):
                payload = response.json()
                detail = str(payload.get("detail", payload.get("error", "request rejected")))[:240]
            raise RuntimeError(f"{method} {path}: expected {expected}, observed {response.status_code}; {detail}")
        return response

    def create_group(client: httpx.Client, suffix: str, **changes) -> dict:
        start = datetime.now(UTC).date() + timedelta(days=30)
        payload = {
            "name": f"Upload Settings Local Review {run_id} {suffix}",
            "destination": "Synthetic Local Review",
            "travel_date": start.isoformat(), "return_date": (start + timedelta(days=5)).isoformat(),
            **changes,
        }
        group = request(client, "POST", "/api/v1/upload-links", expected=201, json=payload).json()
        report["groups"].append({
            "id": group["id"], "name": group["name"], "token": group["token"],
            "url": f"{args.origin}/upload/{group['token']}",
        })
        return group

    def upload(public: httpx.Client, group: dict, credential: str, *, files=None, mode="file", expected=201) -> httpx.Response:
        return request(
            public, "POST", f"/api/v1/passports/upload/{group['token']}", expected=expected,
            data={"client_name": "Synthetic HTTP Traveller", "acquisition_mode": mode, "upload_idempotency_key": credential},
            files=files, headers={"X-Upload-Session-ID": credential},
        )

    def finalize(public: httpx.Client, group: dict, submission: dict, credential: str, *, expected=200, **values) -> dict:
        return request(
            public, "POST", f"/api/v1/passports/{submission['id']}/client-submit", expected=expected,
            headers={"X-Upload-Session-ID": credential},
            json={
                "group_token": group["token"],
                "confirmed_fields": {"given_names": "Synthetic HTTP Traveller"},
                "client_email": f"upload-qa-{group['id']}@example.com",
                "client_phone": f"+120255501{int(uuid.UUID(group['id'])) % 100:02d}",
                **values,
            },
        ).json()

    try:
        with httpx.Client(base_url=args.api, timeout=60, headers={"Origin": args.origin}) as staff, httpx.Client(base_url=args.api, timeout=60, headers={"X-Upload-Session-ID": secrets.token_urlsafe(40)}) as public:
            live = request(public, "GET", "/api/v1/health/live").json()
            if live.get("environment") != "development":
                raise RuntimeError("Development audit API required.")
            ready = request(public, "GET", "/api/v1/health/ready").json()
            report["readiness"] = {"status": ready.get("status"), "checks": ready.get("checks")}
            record("Local API reports development and readiness")

            auth = request(staff, "POST", "/api/v1/auth/login", data={"username": account["email"], "password": seed["manager_password"]}).json()
            if auth.get("challenge_token"):
                auth = request(staff, "POST", "/api/v1/auth/mfa/verify", json={"challenge_token": auth["challenge_token"], "code": totp(account["mfa_secret"])}).json()
            if auth.get("user", {}).get("agency_id") != seed["agency_id"]:
                raise RuntimeError("Authenticated account must belong to the isolated seed agency.")
            record("Synthetic WebKit manager authenticated with MFA")

            question_id, detail_id = str(uuid.uuid4()), str(uuid.uuid4())
            optional_fields = {name: False for name in REQUIRED_FIELD_NAMES}
            questions = [{"id": question_id, "label": "Preferred local review slot", "options": ["Morning", "Afternoon"], "enabled": True, "required": True}]
            details = [{"id": detail_id, "label": "Additional local review detail", "enabled": True, "required": False}]
            field_options = {
                "base_city_enabled": True, "ask_nearest_domestic_airport": True,
                "nearest_international_airport_enabled": True, "departure_cities": ["Delhi", "Mumbai"],
                "staff_code_enabled": True, "agent_employee_code_enabled": True,
                "designation_enabled": True, "agency_dealership_name_enabled": True, "meal_preference_enabled": True,
                "custom_questions": questions, "custom_details": details,
            }
            labels = {"agent_employee_code_label": "Producer Code", "agency_dealership_name_label": "Production Company"}
            if args.reuse_manual_token:
                manual = request(public, "GET", f"/api/v1/upload-links/token/{args.reuse_manual_token}").json()
                if not manual["name"].startswith("Upload Settings Local Review "):
                    raise RuntimeError("Only this runner's synthetic review group can be reused.")
                report["groups"].append({
                    "id": manual["id"], "name": manual["name"], "token": manual["token"],
                    "url": f"{args.origin}/upload/{manual['token']}",
                })
            else:
                manual = create_group(
                    staff, "Four Pages", **field_options, require_selfie=True,
                    upload_configuration={
                        "passport_upload_pages": ["cover", "back_cover", "front", "back"],
                        "visa_photo_required": False, "required_fields": optional_fields, **labels,
                    },
                )
            manual_public = request(public, "GET", f"/api/v1/upload-links/token/{manual['token']}").json()
            assert manual_public["upload_configuration"]["passport_upload_pages"] == ["cover", "back_cover", "front", "back"]
            assert manual_public["upload_configuration"]["agent_employee_code_label"] == "Producer Code"
            record("Manual four-page review link retains page order and editable labels")

            no_passport = create_group(
                staff, "Details Only", **field_options, relation_with_qualifier_enabled=True,
                upload_configuration={"passport_enabled": False, "required_fields": optional_fields, **labels},
            )
            public_config = request(public, "GET", f"/api/v1/upload-links/token/{no_passport['token']}").json()
            assert public_config["upload_configuration"]["passport_enabled"] is False
            assert public_config["custom_questions"][0]["required"] is True
            assert public_config["custom_details"][0]["required"] is False
            record("Public link exposes independent required and optional settings")

            details_capability = secrets.token_urlsafe(40)
            details_draft = upload(public, no_passport, details_capability).json()
            assert details_draft["image_s3_key"] == "" and details_draft["extraction_status"] == "ready_for_review"
            assert details_draft["processing_job_id"] is None
            report["submissions"].append({"id": details_draft["id"], "group_id": no_passport["id"], "kind": "details"})
            record("Details-only upload persists without documents or OCR")

            missing_question = finalize(public, no_passport, details_draft, details_capability, expected=400)
            assert "Preferred local review slot" in json.dumps(missing_question)
            record("Required custom question blocks final submission")
            details_values = {
                "custom_answers": [{"question_id": question_id, "value": "Morning"}],
                "agent_employee_code": "PROD-LOCAL-42", "agency_dealership_name": "Synthetic Review Studio",
            }
            final_details = finalize(public, no_passport, details_draft, details_capability, **details_values)
            assert final_details["status"] == "needs_review"
            assert final_details["post_submission_verification"]["provider_status"] == "not_applicable"
            assert final_details["staff_metadata"]["agent_employee_code_label"] == "Producer Code"
            assert final_details["confirmed_fields"]["agent_employee_code"] == "PROD-LOCAL-42"
            assert not final_details["qualifier_enabled_snapshot"]
            assert final_details["custom_detail_answers"] == []
            record("Optional fields and qualifier can be skipped; code label and text persist")
            replay = finalize(public, no_passport, details_draft, details_capability, **details_values)
            assert replay["post_submission_verification_revision"] == final_details["post_submission_verification_revision"]
            record("Final details submission retry is idempotent")

            covers_group = create_group(staff, "Cover Storage", upload_configuration={"passport_upload_pages": ["cover", "back_cover"], "passport_live_scan": False})
            cover_bytes = synthetic_cover("FRONT COVER SAMPLE")
            back_bytes = synthetic_cover("BACK COVER SAMPLE")
            (output / "synthetic-front-cover.jpg").write_bytes(cover_bytes)
            (output / "synthetic-back-cover.jpg").write_bytes(back_bytes)
            files = {"passport_cover_file": ("cover.jpg", cover_bytes, "image/jpeg"), "passport_back_cover_file": ("back-cover.jpg", back_bytes, "image/jpeg")}
            cover_capability = secrets.token_urlsafe(40)
            upload(public, covers_group, cover_capability, files=files, mode="camera", expected=400)
            record("Disabled live scanner rejects a forged upload request")
            oversized = {**files, "passport_cover_file": ("oversized-cover.jpg", b"x" * (MAX_BYTES + 1), "image/jpeg")}
            rejected = upload(public, covers_group, cover_capability, files=oversized, expected=400)
            assert "2 MB" in rejected.text
            record("Original document exceeding 2 MiB rejected before decoding", bytes=MAX_BYTES + 1)

            cover_draft = upload(public, covers_group, cover_capability, files=files).json()
            assert cover_draft["image_s3_key"] == "" and cover_draft["processing_job_id"] is None
            assert cover_draft["passport_cover_s3_key"] and cover_draft["passport_back_cover_s3_key"]
            report["submissions"].append({"id": cover_draft["id"], "group_id": covers_group["id"], "kind": "covers"})
            record("Both covers pass local scanner and persist without OCR")

            for kind in ("cover", "back_cover"):
                path = f"/api/v1/passports/upload/{covers_group['token']}/{cover_draft['id']}/image/{kind}"
                preview = request(public, "GET", path, headers={"X-Upload-Session-ID": cover_capability})
                with Image.open(io.BytesIO(preview.content)) as image:
                    assert image.size == (540, 760)
                request(public, "GET", path, expected=404, headers={"X-Upload-Session-ID": secrets.token_urlsafe(40)})
            wrong_group_path = f"/api/v1/passports/upload/{no_passport['token']}/{cover_draft['id']}/image/cover"
            request(public, "GET", wrong_group_path, expected=404, headers={"X-Upload-Session-ID": cover_capability})
            record("Public cover previews require the matching group and upload capability")

            final_covers = finalize(public, covers_group, cover_draft, cover_capability)
            assert final_covers["status"] == "needs_review" and final_covers["post_submission_verified_at"] is None
            assert not final_covers["passport_cover_s3_key"].startswith("drafts/")
            assert not final_covers["passport_back_cover_s3_key"].startswith("drafts/")
            record("Final cover submission promotes both stored images without claiming AI verification")
            for kind in ("cover", "back_cover"):
                staff_path = f"/api/v1/passports/{cover_draft['id']}/covers/{kind}"
                request(public, "GET", staff_path, expected=401)
                response = request(staff, "GET", staff_path)
                with Image.open(io.BytesIO(response.content)) as image:
                    assert image.size == (540, 760)
                request(public, "GET", f"/api/v1/passports/upload/{covers_group['token']}/{cover_draft['id']}/image/{kind}", headers={"X-Upload-Session-ID": cover_capability})
            record("Authenticated and capability-protected cover previews survive permanent promotion")
            report["completed_at"] = datetime.now(UTC).isoformat()
            report["external_ai_invoked"] = False
            report["status"] = "passed"
    except Exception as exc:
        report["status"] = "failed"
        report["failure"] = str(exc)
        raise
    finally:
        (output / "results.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": report.get("status"), "report": str(output / "results.json"), "checks": len(report["checks"]), "groups": report["groups"]}), flush=True)


if __name__ == "__main__":
    run()
