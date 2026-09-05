"""Live PDF workflow proof against the explicitly isolated Docker browser QA stack.

Run with backend/.venv/Scripts/python.exe. Credentials are read only from the
ignored synthetic seed, used in memory, and never included in the report.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import json
import struct
import subprocess
import time
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs/dashboard-qa/pdf-upload-followup"
API = "http://127.0.0.1:58000"
CONTAINER = "passdetection-audit-backend-1"
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "passdetection-real-stack-qa")
GROUP_ID = uuid.uuid5(NAMESPACE, "document-review-group")
PASSENGER_ID = uuid.uuid5(NAMESPACE, "document-review-asha-mehta")


def docker_python(code: str) -> dict:
    result = subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "python", "-"],
        input=code,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        # Server logs may include configuration or unrelated records.
        raise RuntimeError(
            "Guarded QA fixture operation failed; server output suppressed"
        )
    for line in reversed(result.stdout.splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise RuntimeError("QA fixture operation returned no structured result")


def prepare_fixture() -> dict:
    inspection = json.loads(
        subprocess.check_output(["docker", "inspect", CONTAINER], text=True)
    )[0]
    assert (
        inspection["Config"]["Labels"]["com.docker.compose.project"]
        == "passdetection-audit"
    )
    bindings = inspection["NetworkSettings"]["Ports"]["8000/tcp"]
    assert any(
        item["HostIp"] == "127.0.0.1" and item["HostPort"] == "58000"
        for item in bindings
    )
    return docker_python("""
import asyncio,json,uuid
from app.core.config.settings import get_settings
from app.infrastructure.database.models import ClientGroupModel,PassportSubmissionModel,ManagerGroupAccessModel,UserModel
from app.infrastructure.database.session import AsyncSessionFactory,engine

async def main():
    settings=get_settings()
    assert settings.app_env=='development' and settings.database.db=='passdetection_ci_browser'
    assert settings.untrusted_document_ingestion_enabled and settings.malware_scanner_enabled
    namespace=uuid.uuid5(uuid.NAMESPACE_URL,'passdetection-real-stack-qa')
    agency_id=uuid.uuid5(namespace,'agency')
    group_id=uuid.uuid5(namespace,'document-review-group')
    passenger_id=uuid.uuid5(namespace,'document-review-asha-mehta')
    owner=uuid.uuid5(namespace,'manager-chromium')
    async with AsyncSessionFactory() as session:
        actor=await session.get(UserModel,owner)
        assert actor is not None and actor.agency_id==agency_id and actor.email.endswith('@example.test')
        group=await session.get(ClientGroupModel,group_id)
        if group is None:
            group=ClientGroupModel(id=group_id,agency_id=agency_id,name='Document Review Group',token='qa-document-review-synthetic-only',status='active',created_by_user_id=owner)
            session.add(group)
            await session.flush()
        assert group.agency_id==agency_id and group.name=='Document Review Group' and group.deleted_at is None
        fields={'given_names':'ASHA','surname':'MEHTA','passport_number':'P1234567'}
        passenger=await session.get(PassportSubmissionModel,passenger_id)
        if passenger is None:
            passenger=PassportSubmissionModel(id=passenger_id,agency_id=agency_id,group_id=group_id,client_name='Asha Mehta',status='confirmed',image_s3_key='enterprise-browser-qa/document-review-synthetic.jpg',confirmed_fields=fields,extracted_fields=fields)
            session.add(passenger)
        assert passenger.agency_id==agency_id and passenger.group_id==group_id and passenger.confirmed_fields==fields
        for browser in ('chromium','webkit'):
            manager_id=uuid.uuid5(namespace,'manager-'+browser)
            access_id=uuid.uuid5(namespace,'document-review-access-'+browser)
            access=await session.get(ManagerGroupAccessModel,access_id)
            if access is None:
                session.add(ManagerGroupAccessModel(id=access_id,agency_id=agency_id,group_id=group_id,manager_id=manager_id))
            else:
                assert access.agency_id==agency_id and access.group_id==group_id and access.manager_id==manager_id
        await session.commit()
    await engine.dispose()
    print(json.dumps({'database':settings.database.db,'group_id':str(group_id),'passenger_id':str(passenger_id),'scanner_enabled':True,'ingestion_enabled':True}))
asyncio.run(main())
""")


def make_pdf(path: Path, lines: list[str]) -> bytes:
    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    commands = ["BT /F1 14 Tf 48 780 Td 24 TL"]
    for index, line in enumerate(lines):
        if index:
            commands.append("T*")
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        commands.append(f"({escaped}) Tj")
    commands.append("ET")
    stream = DecodedStreamObject()
    stream.set_data("\n".join(commands).encode("ascii"))
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    content = output.getvalue()
    path.write_bytes(content)
    assert "ASHA MEHTA" in PdfReader(io.BytesIO(content)).pages[0].extract_text()
    return content


def totp(secret: str) -> str:
    digest = hmac.new(
        base64.b32decode(secret),
        struct.pack("!Q", int(time.time()) // 30),
        hashlib.sha1,
    ).digest()
    offset = digest[-1] & 15
    return f"{(struct.unpack('!I', digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000:06d}"


def run() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures-only", action="store_true")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse only batch IDs from this runner's prior local report",
    )
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    fixture = prepare_fixture()
    visa_path = OUT / "synthetic-asha-mehta-visa.pdf"
    ticket_path = OUT / "synthetic-asha-mehta-ticket.pdf"
    visa = make_pdf(
        visa_path,
        [
            "SYNTHETIC QA DOCUMENT - NOT VALID FOR TRAVEL",
            "VIETNAM ELECTRONIC VISA",
            "Vietnam Immigration Department",
            "Full name: ASHA MEHTA",
            "Passport No: P1234567",
            "Visa number: EVN240099",
            "Valid from: 01 August 2026",
            "Number of entries: Multiple",
        ],
    )
    ticket = make_pdf(
        ticket_path,
        [
            "SYNTHETIC QA DOCUMENT - NOT VALID FOR TRAVEL",
            "E-TICKET ITINERARY",
            "Booking reference: ABC123",
            "AIRLINE NAME: GLOBAL AIRWAYS",
            "Departure: Delhi",
            "Arrival: Hanoi",
            "Passenger name: ASHA MEHTA",
            "Passport No: P1234567",
            "Flight: QA101",
            "Travel date: 01 October 2026",
        ],
    )
    report = {
        "started_at": datetime.now(UTC).isoformat(),
        "fixture": fixture,
        "pdfs": [str(visa_path), str(ticket_path)],
        "checks": [],
    }
    if args.resume:
        previous = json.loads((OUT / "api-results.json").read_text(encoding="utf-8"))
        assert previous["fixture"]["group_id"] == str(GROUP_ID)
        assert previous["fixture"]["database"] == "passdetection_ci_browser"
        report = previous
        report.pop("error", None)
        report["resumed_at"] = datetime.now(UTC).isoformat()
    (OUT / "fixtures.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "group_id": str(GROUP_ID),
                "passenger_id": str(PASSENGER_ID),
                "pdfs": report["pdfs"],
            }
        ),
        flush=True,
    )
    if args.fixtures_only:
        return
    seed = json.loads(
        (ROOT / "outputs/dashboard-qa/synthetic-seed.json").read_text(
            encoding="utf-8-sig"
        )
    )
    account = seed["accounts"]["webkit"]
    assert account["email"].endswith("@example.test")

    def record(name: str, started: float, **facts) -> None:
        if any(check["name"] == name for check in report["checks"]):
            print("RECONFIRMED: " + name, flush=True)
            return
        report["checks"].append(
            {
                "name": name,
                "passed": True,
                "seconds": round(time.perf_counter() - started, 3),
                **facts,
            }
        )
        print("PASS: " + name, flush=True)

    def request(client, method, path, *, expected=200, **kwargs):
        response = client.request(method, path, **kwargs)
        if response.status_code != expected:
            # Auth tokens, receipts and signed URLs are never written to evidence.
            detail = (
                response.json().get("detail", "")
                if response.headers.get("content-type", "").startswith(
                    "application/json"
                )
                else "non-JSON response"
            )
            raise RuntimeError(
                f"{method} {path}: expected {expected}, got {response.status_code}; {str(detail)[:300]}"
            )
        return response

    try:
        with httpx.Client(
            base_url=API,
            timeout=150,
            headers={"Origin": "http://127.0.0.1:3200"},
            follow_redirects=False,
        ) as client:
            started = time.perf_counter()
            auth = request(
                client,
                "POST",
                "/api/v1/auth/login",
                data={
                    "username": account["email"],
                    "password": seed["manager_password"],
                },
            ).json()
            if auth.get("challenge_token"):
                request(
                    client,
                    "POST",
                    "/api/v1/auth/mfa/verify",
                    json={
                        "challenge_token": auth["challenge_token"],
                        "code": totp(account["mfa_secret"]),
                    },
                )
            record("Synthetic WebKit account authentication", started)
            started = time.perf_counter()
            if args.resume and report.get("rename_batch_id"):
                renamed = request(
                    client,
                    "GET",
                    f"/api/v1/document-rename/batches/{report['rename_batch_id']}",
                ).json()
            else:
                renamed = request(
                    client,
                    "POST",
                    "/api/v1/document-rename/batches",
                    expected=201,
                    data={"title": "Synthetic PDF Upload Follow-up"},
                    files=[
                        ("files", (visa_path.name, visa, "application/pdf")),
                        ("files", (ticket_path.name, ticket, "application/pdf")),
                    ],
                ).json()
            assert (
                renamed["total_count"] == 2
                and renamed["visa_count"] == 1
                and renamed["ticket_count"] == 1
                and renamed["unknown_count"] == 0
            )
            assert all(
                item["extracted_name"] == "Asha Mehta" for item in renamed["items"]
            ), "Rename did not extract the synthetic passenger name"
            assert {item["detected_type"] for item in renamed["items"]} == {
                "visa",
                "flight_ticket",
            }
            report["rename_batch_id"] = renamed["batch_id"]
            record(
                "Rename: two real PDFs analyzed with correct names and types",
                started,
                total=2,
                visa_count=1,
                ticket_count=1,
                filenames=[item["renamed_filename"] for item in renamed["items"]],
            )
            started = time.perf_counter()
            stored = request(
                client, "GET", f"/api/v1/document-rename/batches/{renamed['batch_id']}"
            ).json()
            assert len(stored["items"]) == 2
            for item in renamed["items"]:
                downloaded = request(
                    client,
                    "GET",
                    f"/api/v1/document-rename/items/{item['id']}/download",
                )
                assert downloaded.content in (visa, ticket)
            archive = request(
                client,
                "GET",
                f"/api/v1/document-rename/batches/{renamed['batch_id']}/download.zip",
            )
            with zipfile.ZipFile(io.BytesIO(archive.content)) as zip_file:
                assert len(zip_file.namelist()) == 2
            record(
                "Rename: stored batch, individual PDFs and ZIP retrieved",
                started,
                documents=2,
            )

            for lane, path, content in (
                ("visa", visa_path, visa),
                ("flight_ticket", ticket_path, ticket),
            ):
                started = time.perf_counter()
                upload_id, chunk_id = str(uuid.uuid4()), str(uuid.uuid4())
                base = f"/api/v1/document-distribution/groups/{GROUP_ID}/{lane}"
                resuming_batch = args.resume and lane in report.get(
                    "distribution_batches", {}
                )
                if resuming_batch:
                    batch = request(client, "GET", base).json()
                    assert batch["batch_id"] == report["distribution_batches"][lane]
                else:
                    verified = request(
                        client,
                        "POST",
                        base + "/verify",
                        data={"upload_id": upload_id, "chunk_id": chunk_id},
                        files={"files": (path.name, content, "application/pdf")},
                    ).json()
                    assert (
                        verified["accepted_count"] == 1
                        and verified["rejected_count"] == 0
                    )
                    entry = verified["files"][0]
                    assert (
                        entry["matched_passenger_id"] == str(PASSENGER_ID)
                        or str(PASSENGER_ID) in entry["matched_passenger_ids"]
                    )
                    assert entry["staging_receipt"]
                    record(
                        f"Distribution {lane}: real analysis matched Asha Mehta and produced receipt",
                        started,
                        accepted=1,
                        confidence=entry["match_confidence"],
                    )
                    started = time.perf_counter()
                    batch = request(
                        client,
                        "POST",
                        base + "/upload",
                        expected=201,
                        data={
                            "upload_id": upload_id,
                            "chunk_id": chunk_id,
                            "chunk_index": "0",
                            "expected_chunk_count": "1",
                            "expected_file_count": "1",
                            "staging_receipts": entry["staging_receipt"],
                        },
                    ).json()
                assert (
                    batch["physical_file_count"] == 1
                    and batch["assigned_passenger_count"] == 1
                    and batch["needs_assignment_count"] == 0
                )
                document = batch["review_rows"][0]["document"]
                assert (
                    document
                    and document["extracted_name"] == "Asha Mehta"
                    and document["extracted_passport_number"] == "P1234567"
                )
                assert document["delivery_status"] == "not_sent"
                report.setdefault("distribution_batches", {})[lane] = batch["batch_id"]
                stored = request(client, "GET", base).json()
                assert any(
                    row["passenger_id"] == str(PASSENGER_ID) and row["document"]
                    for row in stored["review_rows"]
                )
                if document.get("url"):
                    parsed = urlsplit(document["url"])
                    assert parsed.hostname in {None, "127.0.0.1", "localhost"}, (
                        "Refusing non-local document download"
                    )
                    if not parsed.scheme:
                        download = request(client, "GET", document["url"])
                    else:
                        download = httpx.get(document["url"], timeout=30)
                    assert download.status_code == 200 and download.content == content
                record(
                    f"Distribution {lane}: receipt uploaded, assigned and retrieved",
                    started,
                    physical_files=1,
                    assigned_passengers=1,
                    provider_sends=0,
                    timing_scope=(
                        "retrieval of a previously uploaded batch"
                        if resuming_batch
                        else "receipt upload, assignment and retrieval"
                    ),
                )

            for family, path in (
                ("Rename", "/api/v1/document-rename/batches"),
                (
                    "Distribution",
                    f"/api/v1/document-distribution/groups/{GROUP_ID}/visa/verify",
                ),
            ):
                started = time.perf_counter()
                response = request(
                    client,
                    "POST",
                    path,
                    expected=422,
                    data={"title": "Malformed synthetic QA"},
                    files={
                        "files": (
                            "malformed.pdf",
                            b"Synthetic invalid PDF bytes",
                            "application/pdf",
                        )
                    },
                )
                assert "not a readable, unencrypted PDF" in response.json()["detail"]
                record(
                    f"{family}: clean but malformed content accurately rejected",
                    started,
                    http_status=422,
                )
                started = time.perf_counter()
                # Official harmless AV test marker is assembled in memory only.
                marker = (
                    b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$"
                    + b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
                )
                response = request(
                    client,
                    "POST",
                    path,
                    expected=422,
                    data={"title": "Antivirus synthetic QA"},
                    files={"files": ("security-test.pdf", marker, "application/pdf")},
                )
                assert "failed security scanning" in response.json()["detail"]
                record(
                    f"{family}: real ClamAV test marker rejected",
                    started,
                    http_status=422,
                )
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["error"] = str(exc)
        raise
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        (OUT / "api-results.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    run()
