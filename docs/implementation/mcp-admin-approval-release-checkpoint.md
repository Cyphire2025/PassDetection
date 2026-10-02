# MCP administrator approval: live release

Administrator approval and the four MCP dashboard pages are live at `https://tech.gctravels.com`. Activation completed on 2 October 2026 at **14:12:24 UTC (19:42:24 IST)**. Independent read-only live verification passed at **14:13:00 UTC (19:43:00 IST)**. MCP access is enabled.

## Deployed identity

| Artifact | Verified identity |
| --- | --- |
| Application revision | `12d11fbf8178e1e5424a5de0ce3f0bb91bd16080` |
| Backend image | `sha256:01ca2029f0e563ec17dd68b74364e0f0078dde3004c23fce0f6cb607be64ca26` |
| Frontend image | `sha256:25d290d368f52eab5eaa37a0b438b8493c07de2167664a851b13826a5bb23019` |
| Source archive SHA-256 | `4a1b8bde5578840f8a9feeb06cd3e6229e79467f532aa61ded2f13d13e6d396d` |
| Source manifest SHA-256 | `c8f7044f96e46106a5ee0c5738d5d8eddbbf8166009ac4e4410bffdba3370d6a` |
| Final operator SHA-256 | `2414e0c07f517cc9078a966ed5e08675210732dfd88999b3039e681834bc9314` |
| Final runner SHA-256 | `e458a1fef2b50768f04b421c0510f17c7dc5ebafb2ea4259af7135f0c6c5d018` |
| Independent verifier SHA-256 | `09856baf2dd42eb0b49f82d428f1b1c3412c1d10e6042ea0896c00607e74c740` |
| Schema | `0125_mcp_connection_requests` |
| Completion journal | `journal/0044-admin-approval-complete.json` |
| Completion SHA-256 | `07ab624979653cb603f265838c9b87a9d109cc71dd19a42f0f436631589771a2` |

Source, helpers, backup and exclusive release receipts remain in `/opt/GlobalConnectsDashboard/tmp/mcp-direct-12d11fbf8178e1e5424a5de0ce3f0bb91bd16080`. This documentation commit records the deployed application revision and is not another application deployment.

## Live behavior

- Clicking Authenticate in the native MCP app opens `/mcp/connect?request_id=UUID` and creates a cookie-bound pending request. The requester does not sign into the Global Connects dashboard.
- The public page says **Waiting for administrator approval**, displays a comparison code, and polls for the decision. The signed-in superadmin matches that code on Requests and approves or rejects it.
- Approval records a decision. The original requester browser finalizes it and returns to the validated native callback with the one-use authorization code. Rejection returns access_denied without granting access. Completed rejection history remains labeled Rejected.
- `/admin/mcp` lists Devices with separate Enable/Disable actions. `/admin/mcp/requests` lists pending requests and decisions. `/admin/mcp/settings` contains row-style section permissions, global pause/resume and monitoring. `/admin/mcp/setup` contains authorization status, MCP URL and native setup instructions.
- The Advanced section, duplicate Connections view and Try a read in Codex section are removed.

Device names and platforms label separate OAuth authorizations; they do not prove hardware identity. Clients that share one authorization across machines share that entry. Separate authentication is required for independent entries. The server's ten-minute request expiry does not guarantee how long a native app keeps its sign-in window open.

## Independent live verification

- All **20** services run, including twelve new application services and eight preserved infrastructure services. All **18** configured health checks are healthy.
- Published backend liveness/readiness, proxy health, frontend revision, four compiled protected dashboard routes and the public waiting route pass. The anonymous invalid-request waiting page is accessible without a dashboard login.
- All **1,089** backend source files covered by the runtime source probe match the committed source manifest. Schema shape, constraints, indexes, defaults, non-superuser role and each runtime SELECT/INSERT/UPDATE request-table privilege pass.
- Native OAuth discovery, resource binding, issuer support and CIMD pass. The in-image read-only policy accepts three native callbacks and rejects three spoofed callbacks. HTTP probes send only fixed invalid authorization requests: **zero** pending requests, grants or access changes are created by verification.
- All **368** current baseline container identities and their baseline images are retained. The final retained inventory contains **397 containers and 199 images**, with no new missing-resource exception. The three historical stopped-reference anomalies remain under their prior exact approval.
- No new application OOM or restart is observed. Infrastructure identities, networks, resource ceilings, starts and restart counters remain unchanged.
- All three preexisting grants and their enabled/platform/capability decisions are preserved. Global enabled state, allowed read sections and read-access revision match the fresh baseline.

The migration proof preserves all four authority tables under the writer fence: one control row, three grants, 530 token rows and three authorization-code rows. The independent live snapshot had the same four counts and hashes at observation. Later normal credential use may change live token/code state; the retained migration proof is the preservation record.

## Retained backup and release discipline

The source124 backup is `12d11fbf8178e1e5424a5de0ce3f0bb91bd16080.1fa8a5a5a18a478bba1eb8077751e9cc.pgdump`, **15,067,155 bytes**, SHA-256 `a24f5eac20590004852d9026c740888ece88fcc33100cc7f62da6c4ac8b8943d`. Full pg_restore archive decoding passed. A restore rehearsal was not performed. Backup bytes, database/network identity, writer fence, candidate image and exact125 helper command/proof bindings are independently verified.

Migration `0125_mcp_connection_requests` SHA-256 is `479083e6ad6825884044a4c0b7662992d3075863e3319fa188226f6f70d69d0b`; the exact upgrade helper SHA-256 is `fb85d4ce4f4a2cd62c1bcededb7575f39327326beef8cf99826cbd1ea3ffe1a1`. Automatic downgrade, cleanup and automatic phase retry remain disabled.

The earlier1782 candidate was built but never activated after a final review found the rejected-history display issue. Its source, images, containers, frozen operator and receipts are retained. Final12d was deployed from separately frozen operator/runner copies. All prior release helpers and receipts remain unchanged.

## Qualification scope

Before activation: 117 backend flow/contract tests, 104 migration helper unit cases, four real PostgreSQL helper CLI scenarios, one PostgreSQL concurrency/quota scenario, 151 frontend MCP/proxy unit tests, eleven isolated desktop/mobile browser scenarios, 37 final operator tests and 102 independently reviewed verifier tests passed. The final history correction passed its focused20-case component regression suite, TypeScript and ESLint. The final production images built successfully on the server.

The backend quality ratchet and inventory retain exactly their known baseline failures: two document distribution budget failures and twenty business surface inventory gaps. This release adds no new failures and does not claim those unrelated gaps are qualified. Coverage floors were not activated without a coverage XML input. Native Windows/Mac installed-app completion has not been manually observed; browser callbacks, backend flow, PostgreSQL behavior and deployed native policy were verified separately.

Local independent evidence: `outputs/admin-approval-live-verification-00c92422aa034707a4ededbf264e9c83.json`.
