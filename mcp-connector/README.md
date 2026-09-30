# Global Connects desktop MCP connector 0.2.4

The minimum read-only release uses `serve --read-only`. It exposes only remote
tools explicitly marked with `mcp:read` and a true read-only annotation, and
rechecks the current remote catalog before every direct tool call. All local
file tools are unavailable, including calls made without discovery. File
selections and download folders cannot be combined with this mode. The backend
independently enforces read-only capability and section permissions; this local
mode does not replace that server enforcement.

This Windows connector exposes the application's deployed MCP tools over local stdio. Its remote endpoint is the configured application's `/mcp`; browser authorization uses the existing superadmin login and MFA flow. It does not read or write Codex's credential storage or configuration.

Version 0.2.3 handles cancellation during refresh rotation. When the outcome is
uncertain, it clears the refresh credential synchronously before releasing the
rotation locks, propagates cancellation, and requires fresh browser sign-in.
The surviving connector blocks the exact uncertain credential even if native
vault deletion fails. A new credential saved by a separate successful sign-in
can recover that connector. If deletion fails, this fence exists only in the
surviving process: stop other connector processes, repair vault access, and
complete fresh sign-in before resuming them. A successor already saved after a
successful refresh is retained when a later cancellation is propagated; the
cancelled request is never dispatched automatically.

Version 0.2.2 releases the local callback listener when browser sign-in is
cancelled, including when a callback has already arrived. Cancellation prevents
token exchange after cleanup. The existing five-minute sign-in deadline,
callback validation, requested permissions and credential storage policy remain
unchanged.

Version 0.2.1 publishes guidance to ask only for missing details and preserve an
already explicit send request through the required exact-plan confirmation. It
also explains supported contact-workbook rejection codes using fixed local
corrections. A request merely to prepare a message still does not authorize
sending, and recipient opt-in remains a separate required fact. Available tools
and permissions continue to come from the deployed application and current
connection. Installing this version does not enable uploads or communications.

**Qualification status:** local mocked HTTP/vault, real loopback callback, Windows kernel mutex, and SDK protocol tests are available in `tests/`. An actual TCP test runs the backend OAuth/MCP adapters under uvicorn against a disposable SQLite database: metadata discovery, PKCE exchange, connection-status tool execution, refresh rotation, and revocation pass through the connector and official SDK. Real Codex sign-in, native vault sign-in, production access isolation, and production file transfers have not been qualified. Only deployed remote tools appear. This package does not make the eight-phase integration complete.

## Install into a separate environment

Use CPython 3.11 and a version of `uv` already approved for the repository. Run from this directory:

```powershell
uv venv --python 3.11 .venv
uv pip install --python .venv/Scripts/python.exe --require-hashes -r requirements.lock
uv pip install --python .venv/Scripts/python.exe --no-deps .
.venv/Scripts/gc-mcp.exe --version
```

The runtime lock pins the official MCP SDK at **2.2.0**, httpx2 at **2.13.1**, and Windows Credential Manager access through pywin32 at **312**. Its resolved dependencies match the existing qualified backend environment at the time the lock was generated. Installing the connector must not reuse or modify the production backend environment.

## Sign in explicitly

Replace the example origin with the deployed application's public origin. Reads are the default; request only capabilities that are available and approved for that connection.

```powershell
.venv/Scripts/gc-mcp.exe --origin https://app.example.com sign-in --scopes mcp:read
```

The browser opens after the connector binds **127.0.0.1:8765**. The callback must be exactly `http://127.0.0.1:8765/callback`; client ID is `global-connects-desktop`. A conflicting local listener causes sign-in to stop. The callback checks Host, state, issuer when supplied, and duplicate parameters. One callback is accepted; codes and callback URLs are never logged. The sign-in attempt expires after five minutes.

The connector validates protected-resource and authorization-server metadata against the explicitly configured origin and expected `/oauth/mcp/authorize` and `/oauth/mcp/token` endpoints. HTTP is permitted only for local loopback qualification; deployment requires HTTPS. HTTP redirects cannot change authorization endpoints.

Only the rotating refresh credential and its local authorization deadline are persisted, under a dedicated `GlobalConnects:MCP:v1:...` Windows Credential Manager entry scoped to the application resource. Access tokens remain in process memory. There is no plaintext, environment-token, or alternative vault fallback. Other operating systems are unsupported in this Windows release and fail closed.

## Review the local MCP command before adding it to Codex

Configure a local **stdio** MCP server using the installed executable and these arguments:

| Field | Value |
|---|---|
| Command | Absolute path to this installation's `.venv/Scripts/gc-mcp.exe` |
| Arguments | `--origin`, the deployed public origin, `serve` |
| Secret environment variables | None |

No tool or install script edits Codex configuration. Use the installed client's supported MCP configuration UI or command after reviewing the executable path and origin. Tool discovery fails explicitly if the application or authorization is unavailable; an unavailable server is not reported as an empty capability inventory. Current pagination cursors and structured tool results are preserved.

Each remote request gets the latest authorized bearer token. In-process serialization and a Windows named mutex protect refresh rotation across connector processes. A token refresh with an uncertain outcome clears the locally stored refresh credential and requires browser sign-in, because retrying a consumed rotating token can revoke the connection. Tool writes are never automatically retried after a network error. Reconcile the operation identifier before repeating a creation or send.

## Explicit local file transfers

`files.py` contains bounded upload streaming for exact caller-authorized paths and atomic download publication with size and SHA-256 verification. Existing local files are never overwritten, including when another process creates the destination during a download. Incomplete temporary transfer copies are removed on handled failure or cancellation; source files are untouched. Filesystems without safe hard-link publication fail closed.

The typed artifact client uses only the configured origin and fixed `/mcp/artifacts/` endpoints. Remote filenames, paths, or URLs cannot choose an upload source or download destination. Redirects are rejected. The PDF upload lane accepts one PDF for an existing agency/group pair; it scans the file through the existing application security service and creates a private, connection-bound staged artifact. **Staging alone does not import a passport or attach a document to a business workflow.** The separately deployed PDF inspection/ingestion tools can append a retained travel-document draft after explicit lane/revision selection. Contact XLSX staging similarly precedes a separate preview/create workflow.

After signing in with the required `mcp:upload` or `mcp:export` capability, run these commands with explicit absolute paths and IDs:

```powershell
gc-mcp --origin https://app.example.com upload-pdf --file C:/Provided/document.pdf --agency AGENCY_UUID --group GROUP_UUID
gc-mcp --origin https://app.example.com download --artifact ARTIFACT_ID --destination C:/Downloads/group.xlsx
gc-mcp --origin https://app.example.com acknowledge-download --artifact ARTIFACT_ID --file C:/Downloads/group.xlsx
```

Upload reads and hashes only the explicitly selected regular file, then streams it with its expected size/checksum. The server checks both before scanning and storage. The connector currently caps PDF uploads at 10 MiB and downloads at 512 MiB; the deployment may apply a lower upload limit. Generated export artifacts expire after one hour, and every new metadata/download/acknowledgement request revalidates the connection and current authority.

Download completion has three steps: a complete authenticated server stream, an atomic local save verified against expected size and SHA-256, and an explicit delivery acknowledgement. The acknowledgement completes an associated prepared passport export checkpoint; generation and partial downloads do not. The server records receipt metadata, never the local path. The JSON command result contains an absolute `file.path` and `server_delivery_acknowledged`. If acknowledgement fails after saving, the verified local file remains and that boolean is false. Use `acknowledge-download` with that exact file to reverify and recover; do not download over it. Only the idempotent acknowledgement gets bounded retries for a transient stream-completion conflict. Uploads and business operations are never automatically repeated.

The connector exposes eight local MCP tools: `local_selected_files`, `local_upload_pdf`, `local_upload_contact_excel`, `local_upload_whatsapp_header_image`, `local_inspect_whatsapp_header_image`, `local_recover_whatsapp_header_image`, `local_download_export`, and `local_acknowledge_export`. Select exact source files and an existing download folder in the connector's `serve` startup arguments:

```powershell
gc-mcp --origin https://app.example.com serve --allow-file C:/Provided/document.pdf --download-directory C:/Downloads
```

Repeat `--allow-file` for additional files, up to 100. `local_selected_files` returns opaque selection IDs; upload and acknowledgement tools accept those IDs rather than arbitrary paths. Downloads accept a filename within the selected folder and never overwrite. Verified downloads become eligible for acknowledgement recovery in the current session. Restart with the saved file selected to recover after a process restart. Remote tool definitions, responses, spreadsheet/document text, and tool arguments cannot widen this filesystem authority. Reserved local tool names cannot be overridden by a remote server. The connector rejects Codex credential/configuration files.

Each local tool also checks the current dedicated server authorization before listing selected filenames or reading/writing transfer bytes. Listing requires an active upload or export capability; transferring requires the corresponding capability. This supports upload/export-only connections without adding read permission. The upload/content/acknowledgement endpoints recheck authority independently, including after a successful preflight.

Without these startup selections, remote tools work normally and local transfer tools report the missing selection. Automatic handoff of newly attached Codex files has not been qualified: this release requires explicit connector selections. A process kill can leave a `.gcmcp-*.part` sibling; it is not a completed download and must never complete export history.

The API foundation includes code-only registration of generated passport Excel/image and group WhatsApp tracking artifacts, authenticated bounded reads, and shared website/connector history completion where that export family has a history checkpoint. Tracking workbooks use the website's status/broadcast filters and never change passport history or send messages. Their `whatsapp_tracking_excel` purpose is accepted by the same verified local download tool. It does not yet expose all export generation families. Server transfer copies use unique private S3 keys and conditional writes; originals are untouched. Their expiry denies access immediately, while physical removal of expired/orphaned copies requires a storage lifecycle policy limited to `mcp-transfers/v1/`. No MCP removal endpoint exists.

Hotel rooming-list and check-in-control workbooks use `rooming_list_excel` and `rooming_checkins_excel`. Both use the same verified local download tool. Their remote preparation requires exact agency/group/hotel IDs and a current allocation revision snapshot. Exporting reads existing allocation and check-in evidence; it never allocates rooms, performs check-ins, issues keys or letters, sends messages, or advances passport export history.

## Explicit WhatsApp header images

Select the JPEG/PNG outside MCP with `serve --allow-file C:/Provided/header.png`. Resolve the existing agency and broadcast, then call `local_upload_whatsapp_header_image` with the selection ID, `agency_id`, `broadcast_id`, and a caller-chosen stable `idempotency_key`. Keys contain 16–256 letters, digits, periods, underscores, colons or hyphens; a saved UUID without separators is suitable. The tool never invents or changes a retry key.

Before opening or hashing the file, the connector calls the fixed-origin `/mcp/whatsapp-media/authority` endpoint and requires both current `mcp:upload` and `mcp:communicate` capabilities for that exact agency/broadcast. It reads only the startup-selected regular file, caps the source at 5 MiB, checks the JPEG/PNG signature, hashes it, and makes one raw POST to `/mcp/whatsapp-media/uploads` with the original filename, expected byte count, SHA-256 and stable key. The backend performs full image validation/security scanning, retains normalized media, and owns the durable provider-upload claim. The connector never chooses a storage key or provider media ID and never follows redirects or automatically retries the POST.

The result contains only validated scoped receipt metadata and opaque application handles. Extra response URLs, paths, storage keys, provider IDs or instructions are discarded. `ready_for_message_plan` is true only for `status: ready`; `messages_queued` must be zero. Readiness does not authorize sending: a separate reviewed message plan is required.

For `uploading`, `unknown`, `failed` or `staged`, inspect the existing `media_handle` with `local_inspect_whatsapp_header_image`, using the same explicit agency/broadcast. A response that is lost, redirected, rejected or inconsistent is reported as an unavailable outcome with the original retry key. Preserve that key and selected file; do not create a new key or upload again automatically. If no handle reached the client, an explicitly requested retry of the same original file/key asks the backend for its retained outcome. Changed bytes or scope with an existing key conflict instead of creating another upload.

After a new connection is authorized, `local_recover_whatsapp_header_image` accepts the saved `media_artifact_id` plus exact agency/broadcast. Only a retained, unexpired ready image owned by the same actor can be recovered. This creates protected access for the current connection without rereading a local image or repeating a provider call. Inspection/recovery use only the fixed metadata routes; they cannot widen selected local file authority. An uncertain provider outcome is never converted into a fresh upload by recovery.

Local qualification includes strict request/receipt tests and real SDK→connector→loopback HTTP flows for ready and uncertain outcomes. Those flows use the backend's actual scan/normalization/durable-claim services, synthetic storage/scanner adapters, and a mocked provider upload. They prove a stable-key retry scans/uploads once and queues zero messages; they do not qualify a real WhatsApp provider, production vault, or real Codex attachment handoff.

## Revoke and recover

- To revoke server access, use **Administration → MCP**, revoke the named connection, or activate emergency disable. The connector cannot change its own server grants.
- To remove this installation's local authorization, run `gc-mcp --origin https://app.example.com forget`. This clears only its own vault entry; it does not revoke the server grant.
- If the vault is inaccessible or saving fails, sign-in fails. Revoke any just-created named connection in the application, repair the vault, and sign in again.
- If refresh is uncertain or denied, sign in again. Do not copy tokens into configuration, command-line arguments, logs, or support messages.
- If a business operation disconnects, inspect its existing operation record before attempting another send or creation. The proxy deliberately does not retry it.

## Local verification

From `mcp-connector/`, using the existing worktree test runtime:

```powershell
../backend/.venv311/Scripts/python.exe -m pytest -q
../backend/.venv311/Scripts/python.exe -m ruff check .
../backend/.venv311/Scripts/python.exe -m ruff format --check .
```

Tests use fake credentials and fixture data. Native Windows tests generate unique qualification targets, assert that the synthetic credential target is absent before writing, and remove only their own test entry afterward. They do not access the configured connection's credential. Tests do not open the browser, modify Codex, contact production, or send messages. The loopback callback and uvicorn tests bind ephemeral local test ports; the production browser callback always uses the fixed approved port. The TCP fixture uses the application's real OAuth router, MCP adapter, authorization service and models; it does not run the entire production startup stack, a PostgreSQL migration, or a real browser/MFA login. Those remain separate release gates.

Design references: [MCP authorization specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) and [Windows Credential Manager credential writes](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew). SDK usage was checked against the installed 2.2.0 Python source, including its `httpx2` transport and constructor-based low-level server handlers.

Document-assignment review workbooks use `document_assignments_excel` and the same verified local download tool. Remote preparation requires exact agency/group/document-type IDs and an inspected source revision, with the website review filters and passenger-name search. It reads existing assignment and delivery metadata without creating PDF links, changing assignments or approvals, sending messages, or advancing passport export history. Availability depends on the deployment export-family allowlist.
