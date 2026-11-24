# Global Connects assistant at /ai

The dashboard header contains an animated sand and silver particle orb directly
before Notifications. It opens an intercepted full-page dialog at /ai, with a
circle reveal from the launcher. Back reverses the reveal and restores the
mounted dashboard. Direct visits open the same workspace. Both journeys require
a signed-in, authorized account.

The larger horizontal voice-reactive particle sculpture (VRPS) keeps gentle idle movement. Its
microphone sits underneath. Actual input/playback RMS drives deformation, with
a smooth cool color blend for speaking replies. Sparse background particles and
reduced-motion support remain. Typed chat, private attachments, formatted answers,
history, the image reveal, thumbnail selection and private library are retained.
The workspace has no introductory headline. The smaller microphone remains below
VRPS. A local AI-page appearance toggle follows the device preference initially
and persists an explicit light/dark choice. It does not alter the dashboard theme.
Both appearances use the same warm material, including a keyed Canvas2D fallback.
Higher display-density rendering and a finer material grid preserve detail at the
larger size. Canvas pixels remain capped at eight million, and quiet scenes draw
only a sparse grain layer without running the interaction simulation. Hidden tabs
pause rendering; reduced motion disables the ambient deformation and star drift.

The output panel starts collapsed, with one large chevron on its edge tab. Its
slide/fade retains messages and draft text; the composer tracks the sculpture's
column. The last chat ID is remembered per account and authorization scope in
this browser. On return its messages are fetched from the authenticated API;
transcripts never enter browser storage. New chat and successful deletion clear
the remembered selection. Late restore responses cannot replace a newly opened
chat or another account's workspace.

The appearance control offers Human hologram (the default) and Sculpture only.
The human view samples generated female/male portraits into an anatomical WebGL
point relief, with depth, subtle parallax and playback-driven movement. The
selected voice determines presentation. This is not a scanned or fully rigged
human mesh, and the motion is not phoneme-aligned lip sync. Rendering is bounded
to 30 fps, resamples across viewport sizes and pauses when hidden. Reduced motion
and WebGL failure retain a still portrait. Emoji, company-logo and custom-text
appearance controls are removed.

Image boundaries gather the same particles into crossing filaments with gaps,
moving knots and local eddies; opposite streams retain corner arc-length spacing.

## Configuration

Super administrators open **Settings → AI assistant**, or **/settings/ai**.

1. Save an OpenAI key, Gemini key, or both. There is no provider-mode selector.
2. Choose chat/document and native voice models independently from the combined
   account-discovered catalog. Refresh retries discovery without losing choices.
3. Reasoning and voices follow the selected model. Unsupported reasoning is
   omitted; supported voice reasoning defaults to low when selecting a model.
4. Check saved key verifies model metadata access without generating an answer.
   It does not establish billing/entitlement for every selected model.
5. Select an existing owned MCP connection (automatic when exactly one exists).
   AI write access defaults off and cannot expand the connection's permissions.
6. Grant Office roles or specific accounts when ready. Initially only superadmins
   have AI access. The off switch blocks everyone, including superadmins. AI
   access does not grant an account new MCP authority.

Model IDs are discovered from provider APIs. Protocol capability rules for
endpoint compatibility, reasoning and built-in voices are centralized in
model_capabilities.py. Unknown reasoning families use provider defaults. Missing
provider accounts or temporary discovery failures preserve saved selections.

Configuration occupies the existing platform settings row
ai_assistant_workspace_v1; no migration is required. Saves require superadmin,
cookie CSRF, recent MFA and an expected revision. The existing shared MFA step-up
dialog handles reauthentication. Concurrent stale saves fail safely.

Keys use Fernet encryption with a domain-separated HKDF-SHA256 key derived from
the existing application secret. Responses/audits contain configured flags and
changed provider names, never credentials. Password fields clear after saving.
Keys do not enter browser storage or URLs. Blank input preserves the saved key;
explicit removal overrides dedicated environment fallbacks.

Keep the existing application secret stable. Rotating it requires re-entering
encrypted provider keys; decryption failures remain recoverable from settings.
Dedicated AI_ASSISTANT_OPENAI_API_KEY and AI_ASSISTANT_GEMINI_API_KEY are optional
fallbacks. General application provider credentials are never inherited.

## Live dashboard access

The assistant discovers and invokes currently permitted tools from the existing
MCP registry via list_mcp_tools and call_mcp_tool. The bridge checks the current
actor, selected owned grant, scopes, global/device settings, sections and tool
allowlist on every call. It invokes the existing audited MCP wrapper with a
short-lived server-only credential removed afterwards. No grant, scope, global
MCP policy, connector configuration or tool implementation is changed.

Only tools explicitly classified observational are exposed while AI writes are
off. Enabling AI writes permits only writes already authorized by MCP; the human
must explicitly request an action. Existing preview, validation, idempotency and
audit workflows remain authoritative. Revocation and effective-role changes fail
closed. An uncertain operation is not repeated by voice answer recovery. Missing
MCP access leaves general chat and the account's private attachments available.

Current means current at the observation time, not ingestion of the whole
database. Broad results require pagination or narrower queries. Prior context is
bounded to ten exchanges and four attachments. Historical messages, documents and
tool results are untrusted data, not authority to change instructions.

## Native voice

The browser sends 16-bit little-endian PCM at 16 kHz through the same-origin
/api/v1/ai-assistant/voice WebSocket. The backend verifies the HttpOnly cookie and
exact Origin/Host, then connects to the selected provider's fixed native endpoint
with a server-side header key. Query/header user credentials and redirects are rejected.
Retained Fast releases preserve operator proxy configuration while adding the
exact reviewed voice location to their candidate copy. Source admission alone
does not install it: post-release checks must inspect the running Nginx location
and syntax, then qualify Gemini model metadata and a setup-only native handshake.
Those diagnostics keep the saved credential in the server process.
The production worker uses a route-aware WebSocket protocol: accepted AI voice
connections permit at most 32 KiB per incoming message, covering 100 ms PCM
packets (about 4.3 KiB in JSON) and bounded typed input. Every other route retains
the 1 KiB transport ceiling. Queue depth remains four and compression stays off.
Real loopback tests use the same options as Gunicorn; socket mocks and TestClient
alone cannot qualify this pre-ASGI limit. Post-release qualification sends a
synthetic microphone-sized packet through the running release's worker options
and checks that mobile/dashboard limits still reject oversized messages.

Gemini understands the original audio and streams spoken PCM at 24 kHz. Optional
input/output transcription serves chat captions and private history; no HTTP
transcription request sits before the live answer. Web Audio plays the stream and
measures its actual level. Interruption clears playback; closing, hiding the page,
ending voice or a connection error releases capture. AudioWorklet has a bounded
older-WebKit fallback.

Gemini 3.8 Live uses provider-default reasoning; Extended Thinking is a separate
model with compatible reasoning controls and nonblocking tool declarations.
OpenAI Realtime requests automatic audio output with server VAD, interruption and
350 ms silence detection. Tool results explicitly trigger spoken continuation.
Audio is never held waiting for ASR captions. GPT-Live uses its separate continuous
session protocol, with bounded background delegation to the selected chat model
and the same MCP authorization. Existing-message read-aloud uses Gemini or Realtime;
GPT-Live is available for native conversations only. Native file questions use a bounded,
tool-free file reader and return observations to the voice model.

Voice checks access every five seconds and ends when settings revision changes.
Superadmin **Usage limits** in /settings/ai controls daily voice chats, typed
requests, images, uploads, standalone speech requests and maximum voice connection
duration (1–60 minutes). Defaults are 30/200/12/80/300 and ten minutes. Zero daily
allowance disables that operation. Limits are per authorized account and take
effect on settings save; the existing optimistic revision, CSRF, recent MFA and
encrypted provider-key protections apply. Legacy environment defaults are retained
until explicitly saved. No migration is required.

GET /api/v1/ai-assistant/settings/usage is superadmin-only and returns that actor's
usage, applied limits, observation time and next UTC midnight reset. The UI polls
every thirty seconds, refreshes on focus/save and formats reset time locally.
Redis errors show unavailable usage, not fabricated zeros.

Voice counts distinct conversation IDs each UTC day, atomically shared across
workers. Reconnecting an already-counted chat does not increment or require spare
daily capacity; a zero allowance still blocks it. Reservations that fail before
Gemini setup completes are refunded under the owning lease. A new voice_chats
counter replaces the historical microphone-start counter without deleting it.
Forty turns and 32 tool calls per connection, three global operations and one per
account remain safety ceilings. Audio-byte/rate bounds scale with the configured
duration. Long Redis leases cannot be shortened by later short operations. End
the connection when finished; provider audio/context can remain billable.

Raw microphone audio is not saved. Caption turns persist privately when complete
or interrupted. A disconnected partial reply is marked unfinished in the browser,
without claiming durable persistence.

## Files, images and retention

Existing upload scanning and bounded PDF/image/text/DOCX/XLSX handling remain.
Archive expansion, macros, external links, formulas, dimensions and excerpts stay
restricted. Images require an explicit user action/intent and weighted quota,
then normalize to PNG. Center expansion, animated particle boundaries, the
thumbnail rail and library are retained.

Superadmin records retain assistant/v1/accounts/<user UUID>/. Delegated accounts
use a hashed role/agency subdirectory, preventing broader previous-role context
from carrying into a reduced role or another agency. No existing objects move
or disappear. Conditional writes and request claim/replay behavior remain.

## Independent models and shared history

Chat and voice can use either provider independently. File analysis, Gemini lookup
recovery and GPT-Live delegated tasks use the selected chat model and reasoning.
Provider credentials remain server-side and separate. Saved legacy mode settings
still load until replaced by explicit model selections.

Typing during native voice sends an end frame and waits for the current voice
turn to save before the selected chat model starts with the same conversation ID.
Failed handoffs preserve the typed draft. Reopening voice loads shared history.

Both channels use the same most-recent-ten-exchange, 48,000-character context
budget. Complete older messages remain saved, and prompts disclose omissions.
Tool outputs use compact JSON; dashboard observations still refresh on each
authorized lookup. Gemini Live compresses its active context from 24,576 toward
16,384 tokens without replacing saved transcripts. Captions come from the same
voice session, avoiding a duplicate transcription or second answer-generation
request. Stable instructions/tools remain ahead of changing question content,
allowing OpenAI's automatic prefix caching without caching business facts across
requests. No extra model call is made solely to summarize history.
Typed answers are read aloud only on request. Recorded voice questions still
receive spoken replies automatically. Native audio/caption output stays live.

## Pricing checked on 2026-10-18

Gemini 3.8 Flash Standard costs $0.75/million input and $3.75/million output tokens,
including thinking, through December 31, 2026. January 1, 2027 prices are $1.50 and
$7.50. Live audio costs $0.005/input minute and $0.018/output minute, plus text/tool
context. 300 minutes each direction is about $6.90 before extras and tax.

Google Cloud welcome/free-trial credits generally cannot pay Gemini API/AI Studio
charges. Check credit eligibility and paid billing on the API project. Use paid
tier data treatment for private dashboard usage.

Official references: [pricing](https://ai.google.dev/gemini-api/docs/pricing),
[billing](https://ai.google.dev/gemini-api/docs/billing),
[Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash),
[Live](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live),
[protocol](https://ai.google.dev/api/live).

QA uses synthetic transports and accounts, without real provider keys or paid
calls. Local SQL/browser checks do not establish model entitlement or full real
PostgreSQL/Redis/private-storage CI qualification. Fast VPS deployment preserves
existing data, backups and the paused-worker resource profile.
