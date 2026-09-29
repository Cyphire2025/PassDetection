"""Typed authenticated artifact transport; remote data never chooses local paths or URLs."""

import hashlib
import hmac
import json
import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import anyio
import httpx2

from .auth import Authorization
from .config import Config, ConnectorError
from .files import FileReceipt, provided_file_chunks, save_verified_download

_HANDLE = re.compile(r"gcmcp_artifact_[A-Za-z0-9_-]{64}\Z")
_DIGEST = re.compile(r"[a-f0-9]{64}\Z")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024


class _RequestError(ConnectorError):
    def __init__(self, status: int):
        super().__init__(
            "Artifact request was denied or unavailable; no business action was retried."
        )
        self.status = status


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    direction: str
    purpose: str
    agency_id: str
    group_id: str
    byte_size: int
    sha256: str

    @classmethod
    def parse(cls, raw: dict, expected_id: str | None = None) -> "Artifact":
        try:
            value = cls(**{name: raw[name] for name in cls.__dataclass_fields__})
            if (
                not _HANDLE.fullmatch(value.artifact_id)
                or expected_id is not None
                and value.artifact_id != expected_id
                or type(value.byte_size) is not int
                or not 1 <= value.byte_size <= MAX_DOWNLOAD_BYTES
                or not _DIGEST.fullmatch(value.sha256)
                or value.direction not in {"upload", "export"}
                or value.purpose
                not in {
                    "group_document_pdf",
                    "passport_excel",
                    "passport_images",
                    "whatsapp_tracking_excel",
                    "rooming_list_excel",
                    "rooming_checkins_excel",
                    "document_assignments_excel",
                }
            ):
                raise ValueError()
            uuid.UUID(value.agency_id)
            uuid.UUID(value.group_id)
            return value
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ConnectorError("Artifact metadata is invalid.") from None


@dataclass(frozen=True)
class DownloadResult:
    artifact_id: str
    file: FileReceipt
    server_delivery_acknowledged: bool

    def as_dict(self) -> dict:
        return asdict(self)


class ArtifactClient:
    def __init__(self, config: Config, authorization: Authorization, client: httpx2.AsyncClient):
        self.config, self.authorization, self.client = config, authorization, client

    def _url(self, handle: str | None = None, suffix: str = "") -> str:
        if handle is not None and not _HANDLE.fullmatch(handle):
            raise ConnectorError("Use the exact artifact ID supplied by Global Connects.")
        if suffix not in {"", "/content", "/delivery"}:
            raise ConnectorError("Unsupported artifact operation.")
        return f"{self.config.origin}/mcp/artifacts/{handle or 'uploads'}{suffix}"

    async def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {await self.authorization.access_token()}",
            "Accept-Encoding": "identity",
        }

    async def _json(self, method: str, url: str, *, expected_status: int = 200, **kwargs) -> dict:
        headers = {**await self._headers(), **kwargs.pop("headers", {})}
        try:
            async with self.client.stream(
                method, url, headers=headers, auth=None, follow_redirects=False, **kwargs
            ) as response:
                if response.status_code != expected_status:
                    if response.status_code in {401, 403}:
                        self.authorization.tokens = None
                    raise _RequestError(response.status_code)
                body = bytearray()
                async for part in response.aiter_bytes():
                    if len(body) + len(part) > 64 * 1024:
                        raise ConnectorError("Artifact metadata exceeded its permitted size.")
                    body.extend(part)
                raw = json.loads(body)
                if not isinstance(raw, dict):
                    raise ValueError()
                return raw
        except ConnectorError:
            raise
        except (httpx2.HTTPError, ValueError, UnicodeError):
            raise ConnectorError(
                "Artifact request did not complete safely; it was not retried."
            ) from None

    async def metadata(self, handle: str) -> Artifact:
        return Artifact.parse(await self._json("GET", self._url(handle)), handle)

    async def authority(self, capability: str | None = None) -> None:
        if capability not in {None, "mcp:upload", "mcp:export"}:
            raise ConnectorError("Unsupported local transfer capability.")
        raw = await self._json(
            "GET",
            f"{self.config.origin}/mcp/artifacts/authority",
            params={"capability": capability} if capability else None,
        )
        available = raw.get("capabilities")
        if (
            raw.get("authorized") is not True
            or not isinstance(available, list)
            or not available
            or any(item not in {"mcp:upload", "mcp:export"} for item in available)
            or capability is not None
            and capability not in available
        ):
            raise ConnectorError("The current connection does not authorize this local transfer.")

    async def upload_pdf(
        self,
        path: Path,
        *,
        allowed_paths: frozenset[Path],
        agency_id: uuid.UUID,
        group_id: uuid.UUID,
    ) -> Artifact:
        size, digest = 0, hashlib.sha256()
        async for part in provided_file_chunks(
            path, allowed_paths=allowed_paths, max_bytes=MAX_UPLOAD_BYTES
        ):
            size += len(part)
            digest.update(part)
        if size == 0:
            raise ConnectorError("The provided PDF is empty.")
        checksum = digest.hexdigest()
        # Hash first, then stream the exact explicitly authorized path. If it
        # changes between reads, the server's size/checksum gate rejects it.
        raw = await self._json(
            "POST",
            self._url(),
            expected_status=201,
            params={"agency_id": str(agency_id), "group_id": str(group_id), "filename": path.name},
            headers={
                "Content-Type": "application/pdf",
                "X-Artifact-Size": str(size),
                "X-Artifact-SHA256": checksum,
            },
            content=provided_file_chunks(
                path, allowed_paths=allowed_paths, max_bytes=MAX_UPLOAD_BYTES
            ),
        )
        result = Artifact.parse(raw)
        if (
            result.direction != "upload"
            or result.purpose != "group_document_pdf"
            or result.agency_id != str(agency_id)
            or result.group_id != str(group_id)
            or result.byte_size != size
            or not hmac.compare_digest(result.sha256, checksum)
        ):
            raise ConnectorError(
                "The staged upload receipt does not match the provided file and group."
            )
        return result

    async def _acknowledge(self, artifact: Artifact, receipt: FileReceipt) -> bool:
        # Completion is idempotent. The last response byte can reach the client
        # just before the server commits its stream marker, so only this precise
        # acknowledgement permits bounded retries on conflict, never uploads.
        for attempt in range(3):
            try:
                raw = await self._json(
                    "POST",
                    self._url(artifact.artifact_id, "/delivery"),
                    json={"byte_size": receipt.size_bytes, "sha256": receipt.sha256},
                )
                confirmed = Artifact.parse(raw, artifact.artifact_id)
                return bool(raw.get("delivered_at")) and confirmed == artifact
            except _RequestError as exc:
                if exc.status == 409 and attempt < 2:
                    await anyio.sleep(0.1)
                    continue
                return False
            except ConnectorError:
                return False
        return False

    async def download(self, handle: str, *, destination: Path) -> DownloadResult:
        if not destination.is_absolute() or destination.exists() or not destination.parent.is_dir():
            raise ConnectorError("Choose an explicit new local filename in an existing directory.")
        artifact = await self.metadata(handle)
        if artifact.direction != "export":
            raise ConnectorError("Only generated exports use verified local delivery.")
        try:
            async with self.client.stream(
                "GET",
                self._url(handle, "/content"),
                headers=await self._headers(),
                auth=None,
                follow_redirects=False,
            ) as response:
                if response.status_code != 200:
                    raise _RequestError(response.status_code)
                if (
                    response.headers.get("x-artifact-sha256") != artifact.sha256
                    or response.headers.get("x-artifact-size") != str(artifact.byte_size)
                    or response.headers.get("content-encoding", "identity") != "identity"
                ):
                    raise ConnectorError(
                        "Artifact stream integrity headers do not match its metadata."
                    )
                receipt = await save_verified_download(
                    response.aiter_bytes(),
                    destination=destination,
                    expected_size=artifact.byte_size,
                    expected_sha256=artifact.sha256,
                    max_bytes=MAX_DOWNLOAD_BYTES,
                )
        except httpx2.HTTPError:
            raise ConnectorError(
                "Download was interrupted; delivery was not acknowledged."
            ) from None
        return DownloadResult(handle, receipt, await self._acknowledge(artifact, receipt))

    async def acknowledge_existing(
        self, handle: str, *, path: Path, allowed_paths: frozenset[Path]
    ) -> DownloadResult:
        """Recover a lost acknowledgement by verifying an explicitly selected existing file."""
        artifact = await self.metadata(handle)
        if artifact.direction != "export":
            raise ConnectorError("Only exports can be acknowledged.")
        size, digest = 0, hashlib.sha256()
        async for part in provided_file_chunks(
            path, allowed_paths=allowed_paths, max_bytes=MAX_DOWNLOAD_BYTES
        ):
            size += len(part)
            digest.update(part)
        if size != artifact.byte_size or not hmac.compare_digest(
            digest.hexdigest(), artifact.sha256
        ):
            raise ConnectorError("The selected local file does not match the export.")
        receipt = FileReceipt(str(path), size, digest.hexdigest())
        return DownloadResult(handle, receipt, await self._acknowledge(artifact, receipt))
