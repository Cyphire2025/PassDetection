# Codex access UI checkpoint — 30 September 2026

The beginner-facing interface is implemented and locally qualified at
`020ddacc14068337cb1d53a3c971f007068448e1`. That exact source is on `main` and
retained on the VPS. It has **not been built or deployed**. The serving backend
remains `1f4177cb` and the serving frontend remains `1d77c9dd`, on schema
`0122_mcp_gc_push`.

The main screen now explains saved Codex authorization, connection setup,
lookups, passport Excel reports, global pause and named-connection disconnect.
It distinguishes authorization from a desktop being online. Technical setup,
raw tools and scopes, IDs, activity and work/file records are closed under
Advanced. Consent uses plain permission names and still requires explicit
approval. The website does not claim to install or configure the local connector.

Examples require the deployed tool chain and appropriate permissions on the
same current user's connection. Unavailable deployment/inventory and incomplete
connection pagination fail closed. Existing access boundaries, consent, MFA,
CSRF and capability narrowing are preserved.

## Qualification

- Final focused component suite: 49 passed.
- Final isolated Chromium journeys: 9 passed at 1440, 650 and 390 pixels,
  including consent and the real frontend MFA retry/cancellation path.
- Exact final Next type generation, TypeScript and scoped ESLint passed.
- Frontend module budgets: 40 passed.
- Supporting full frontend regression: 1,136 tests across 153 files passed in
  124.80 seconds. This run overlapped the final small guard, label and layout
  edits; the final focused/browser runs cover those changes.
- Root confirmed the entire frontend tree equals the test checkout's tree:
  `8c0e4c91dc9b9ff938a0aa50d11ada58e9c31226`.
- Inventory check passed for 1,510 classified surfaces and 85 source tools.
  This is source coverage evidence, not a production availability or phase claim.
- Frontend/proxy-only v1 operator: 207 final root checks passed.

The exact source archive has 4,066 files and 192,737,280 bytes, with SHA256
`85441f3c4c6d24f33d1dcabf48c6ecea8b62306760a69f956fdb8378f1134327`.
Root evidence is retained in `outputs/codex-v1-ui-release-preflight-20260930.json`.
UI logs and screenshots are retained in the `mcp-dashboard-read` checkout's
`outputs/mcp-simple-ui-20260930` and `mcp-simple-access-*.log` files. All browser
mutation tests used isolated fixtures; no live grants or controls were changed.

## Release admission stopped before build

The v1 prepare attempt at 05:48 UTC stopped on `retained_resource_missing`.
There was no build, worker drain, container creation or service replacement.
All 298 previously recorded containers were present; the current inventory
contained 301 containers, with the expected 20 running services. However,
33 previously recorded image IDs were absent, including on exact image inspection.

None of the missing images was referenced by any retained container. All ten
unique images used by the current/previous release and infrastructure remained
inspectable under their exact IDs. An existing daily cron definition prunes
unused images older than 24 hours at 05:09 UTC. Its timing is consistent with
the gap after the successful 04:59 observation, but the available logs did not
prove causation. The historical loss must not be described as caused by this
release or as fully explained.

## Prepared exception, awaiting explicit approval

A separately retained v2 operator and independent live probe are prepared but
have **not been executed remotely**. Root independently passed all 251 combined
mocked checks (220 operator and 31 probe) in 12.84 seconds.

The proposed exception accepts only the exact 33 already-observed missing IDs
during preparation. It rejects any other missing image or container, verifies
every retained container's referenced image, records the historical gap, and
saves that same checked inventory as the new baseline. Build, stage and cutover
then enforce strict preservation of that baseline and all intermediate resources.
Worker recovery keeps its existing identity and capacity checks. The probe
explicitly reports the historical gap rather than claiming all historical
resources remain. No cleanup or cron change is proposed.

The root asked the user to approve this exact historical-gap exception before
any dependent remote phase. Approval has not been received at this checkpoint.
The proposal, hashes and root review are retained in:

- `outputs/codex-v1-ui-v2-proposal-manifest.json`
- `outputs/codex-v1-ui-v2-root-proposal-review-20260930.json`
- `outputs/codex-v1-ui-v2-root-reviewed-20260930.xml`
- `outputs/codex-v1-ui-retention-mismatch-20260930.json`
- `outputs/codex-v1-ui-missing-image-inspection-20260930.json`
- `outputs/codex-v1-ui-cleanup-attribution-20260930.json`

The v1 attempt, all prior receipts, source archives and unfinished work remain
retained. The 12-hour SSH credential expires at 06:19:11 UTC / 11:49:11 IST and
must not be extended or bypassed without new user authorization.

The complete eight-phase goal remains active. Original business creation,
editing, upload and Excel-to-message workflows remain required V1 work as
recorded in `mcp-v1-product-plan.md`. This UI checkpoint completes no broad
phase or remaining business acceptance gate.
