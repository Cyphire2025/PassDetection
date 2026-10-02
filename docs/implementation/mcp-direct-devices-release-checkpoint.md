# Native MCP and device access: live release

The direct native MCP and separate named connection controls are live at
`https://tech.gctravels.com/mcp`. Activation completed on 2 October 2026 at
11:50:36 UTC (17:20:36 IST). Independent live verification passed at
11:51:21 UTC, followed by a separate read-only database and backup check at
11:52:15 UTC. MCP access is enabled.

## Deployed identity and completion

| Artifact | Verified identity |
| --- | --- |
| Application revision | `d3f9eb3cabeeefe0557c0313c0faef2490f1e8fd` |
| Backend image | `sha256:2dfec660be5aad103d28a6744f2e30f9ca500fe889cfb5c325c580a29a8ca8b0` |
| Frontend image | `sha256:e103a5b15893133987e429a21cced7f8f1542388bb3c7723314a391a99957db8` |
| Source archive SHA-256 | `3c57c7068e78da40292574e14f754a5efafd34088929805b6140ca8eab6e1860` |
| Source manifest SHA-256 | `94d9f76e416278c5f281a99a835c1234d13e0bb242b699ee1777b965deab5ade` |
| Original operator SHA-256 | `edebfada4eb28c2a1679d0c2c8048d564f0617b90d4dfd58046c4a873c965056` |
| Successful supplemental v2 SHA-256 | `c3de9bfd6b41c87c6000b9d34e14334d7c4baf826b35adefc65c5160cc18fde3` |
| Schema | `0124_mcp_device_access` |
| Completion journal | `journal/0055-direct-devices-complete.json` |
| Journal SHA-256 | `f14010ecc767194e7c040c918cb8827094372d33a043565a1f63864cb3150222` |
| Finish receipt SHA-256 | `1f5979ce6d30fdc1a7e5ddb7df481a165ded3d7bda70fe3ddbe2e5002f1fbb17` |

Remote source, helpers, backup and exclusive receipts remain in
`/opt/GlobalConnectsDashboard/tmp/mcp-direct-d3f9eb3cabeeefe0557c0313c0faef2490f1e8fd`.
This documentation commit records the deployed revision; it is not a new application deployment.

## Independent verification and retention

- All 20 services run: twelve new application services and eight infrastructure
  services with their original identities. All 18 configured health checks are healthy.
- Public proxy health, backend liveness and readiness passed. The published frontend
  revision and its public asset hash match the deployed application revision.
- Native OAuth discovery, CIMD, issuer response and MCP resource binding passed.
  The ChatGPT callback and two valid Codex loopback ports were accepted; three
  spoofed callbacks were rejected. The probes created no grants or access changes.
- All 336 baseline container identities and 190 present baseline images remain
  retained. The final inventory is 365 containers and 193 images, including
  intermediate builders, recovery services and helpers. No new application OOM
  or restart events, or infrastructure OOM/restart changes, were observed.
- The two existing grants, global control and read-section authority are preserved.
  The actual schema columns, true default and complete platform constraint passed.

The original migration proof, fresh snapshot with all application writers stopped,
and final read-only runtime snapshot agree on every retained authority row:

| Table | Rows | SHA-256 of legacy row projection |
| --- | ---: | --- |
| `mcp_control` | 1 | `4ef34a565bd5834e54237204ff974446d6a9323a4845b24600fb247256ff9fe2` |
| `mcp_grants` | 2 | `dccda6685f43500e5ff147b53be9f2dcc30c67b3c9bb4c41f329b8671761d58b` |
| `mcp_tokens` | 526 | `a1fe06ce692fce6fb29d3daf3675d069b59232852a5d4ce7d30d5e349354484a` |
| `mcp_authorization_codes` | 2 | `685a01f4a20f5368540ea1b99dcf48159ecf5cecada949a4994c55e8610d79dd` |

The retained source-schema backup is
`d3f9eb3cabeeefe0557c0313c0faef2490f1e8fd.cede023757b44f518d278cb53d23eb1f.pgdump`:
15,061,376 bytes, SHA-256
`0687e88311a95db0d7e80c3821a8b1608b8aa871af09433a450dd75b598c1fe0`.
Its bytes and original receipt match, and full archive decoding passed. A restore
rehearsal is not claimed.

## Inspected deployment stops and completion

The original migration succeeded, but its combined helper log contained valid
JSON followed by Alembic diagnostic lines. The original operator's last-line
parser refused the result and restored the qualified MCP-disabled recovery
services. A separate completion operator retained the original source, baseline,
backup, images and helpers. Its first invocation refused a bytes-versus-text
qualification result before any service mutation. The separately frozen v2 added
bounded strict UTF-8 decoding and passed 62 focused operator/sender tests.
After fresh inspection, v2 completed with return code 0 and no timeout. It did
not rerun the migration or downgrade the database. The independent probe's
52 offline tests passed before live use.

The only admitted initial image gap was the already-absent, unreferenced
`sha256:a4de57279423b4ea219521887239cd34166a874b4226a38ae167292cf80a04da`.
The user authorized continuation after disclosure. The approval file SHA-256 is
`dd76da1c4174368bf4f06bd7de7811b63dc4e9abb0ce7e0a16b00b4795020333`;
its canonical record digest is
`add7341d23aa015c63a44a4d61b40bf45f80cdb035b37c9e3bd3cef04a14c2ee`.
No further missing resource, cleanup or authority expansion was admitted.

Retained local evidence under `outputs/`:

- `native-devices-remote-finish-c354b0ddd0b54161a896629ff2f439ba-outcome.json`
- `native-devices-live-verification-cfafb53cb59d4e1e94f7c6946a7f5717.json`
- `native-devices-final-receipt-20261002T115213Z-c11e52eeb9a340cc97984865b6bb8f95.json`

## Native setup and access controls

| Native custom MCP field | Value |
| --- | --- |
| Name | Global Connects |
| Type | Streamable HTTP |
| URL | `https://tech.gctravels.com/mcp` |
| Bearer token env var | Leave empty |
| Headers and headers from environment variables | Leave empty |

Save, then use the client's connect/sign-in action. In the browser, sign in,
complete the existing identity check when required, name the connection, choose
Windows, macOS or Other, and approve its permissions. Saving a URL alone grants
no access. This flow requires no local Global Connects connector or STDIO bridge.

Open `/admin/mcp` (Codex access) and its separate Devices section. Each approved
connection has its own Enable/Disable button. Disable rejects its next MCP request,
code exchange and refresh while preserving credentials and history. Other grants
keep their own access. Enable restores permission while the grant and account
remain valid; a client that discarded credentials may require sign-in again.
Grants expire after seven days. Already-running work is not retroactively cancelled.

Entries represent named OAuth authorizations with administrator-selected platform
labels. MCP does not prove a physical hardware identity. A ChatGPT account
connection may be shared across computers, and copied credentials use the same
entry. Independent controls require separate consent grants. The live protocol
checks do not claim a completed sign-in in an installed Windows or Mac client.
The [implementation checkpoint](mcp-direct-devices.md) records local feature
tests and unchanged preexisting repository/inventory gaps.
