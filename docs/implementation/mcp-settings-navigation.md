# MCP Settings navigation and configured controls

## Implementation scope

This frontend change reorganizes MCP Settings into an internal navigation menu: General, Read access, Write access, Activity, Tools, Workflows and Files. The selected view opens alongside the menu; the menu wraps on narrow screens. Read-only deployments expose only their available views. Monitoring data remains loaded on selection.

Read and Write use one versioned draft, retained while switching internal views. Saving applies both choices together. Existing revision conflict handling, identity confirmation and confirmed-response behavior remain in place. The save footer stays in normal flow on mobile to avoid covering controls.

Permission lists contain only supported catalog entries. Supported device Write actions disabled in global Settings remain visible with an Off in Settings explanation. Section IDs, policy authority and operation mappings are unchanged. Descriptions are centralized in a presentation helper with server text as a fallback for future supported sections.

## Configured coverage

Read has 18 business sections: Dashboard, My Tour, All Groups, Group Links, WhatsApp, Operations Inbox, Documents, Coordinators, Rooming Lists, Menu, Tour Ops, GC App, Manager, Staff, Analytics, Audit Logs, Old Data and Settings. MCP administration has no separate business Read permission; connection status is independent.

Write has 13 sections: All Groups, Group Links, Coordinators, Rooming Lists, Menu, Tour Ops, GC App, Manager, Staff, WhatsApp broadcasts, Document delivery, Group Excel imports and Exports. Coverage is limited to the implemented actions described by each section, rather than every action on its dashboard page.

General Write adapters are absent for Dashboard, My Tour, general WhatsApp operations, Operations Inbox, general Documents operations, MCP administration, Analytics, Audit Logs, Old Data and business Settings. WhatsApp broadcasts and Document delivery already have their own implemented controls. Observational views do not necessarily need mutable operations.

## Validation and release boundaries

195 MCP unit cases passed. Type checking and scoped ESLint passed. 25 isolated Chromium browser journeys passed at desktop and mobile widths, including shared draft retention, configured-only rows, lazy monitoring, independent device allowances, conflict handling and identity-confirmation flows. The browser harness used webpack because the existing node_modules junction is outside the worktree root accepted by Turbopack; application configuration and dependencies were unchanged.

The live release is frontend/proxy only. Backend and worker revision 4fa22b13286eae56871a34959bb77cdb333e1374 and schema 0128_mcp_document_delivery are preserved. No production business operations, permission updates, new grants or migration are part of this release. OAuth investigation changes remain an uncommitted local draft for the user to resume later.

## Verified live checkpoint — 3 October 2026

Frontend revision eeb406e64b4c4e85369a10d9677496957f2ea62d is live at https://tech.gctravels.com/admin/mcp/settings. Backend/workers remain at 4fa22b13286eae56871a34959bb77cdb333e1374 and schema 0128_mcp_document_delivery. This documentation checkpoint is later than the deployed frontend commit.

The independent read-only verifier passed. It confirmed 20 running services with healthy configured checks, current Settings client-reference-manifest membership for all four feature markers, exact public asset bytes, backend readiness, unchanged saved authority, and an unauthenticated MCP 401 challenge. It invoked no business tools and changed no permissions. Evidence: outputs/mcp-settings-frontend-live-verification-eeb406e6.json. The public current Settings asset is /_next/static/chunks/1f7-rz8sgvae_.js, SHA-256 20382908427a467090dcfaa319e23426a51e13eecdadc10823dd54fbd8587518. The remote completion receipt has SHA-256 1339a9ed6fdc8600dcf7f10e859f118c658d7644d9da4af4e60c8c5aad329113.

The frozen operator SHA-256 is 31c597f64cb5c9a5075105ff64be41c536be454512f533ab79ed905867a48b06. Production compilation succeeded, but an immediate post-worker-restore health check initially failed; the failing service was not captured, so a transient backend readiness cause remains an inference. After all original services were healthy, reviewed completion amendment 593df7044fd275d9c73636b5e6910781479693fe29877a8e96ea24b9323101f2 bound both successful builders, logs, source, image and restored service identities and recorded the remaining memory/retention receipts. It performed no Docker mutation or rebuild. Its successful checkpoint SHA-256 is 4025da4cf8fb3c869815b4c3e438eaa9b1de2e29bb81a6dc7b79921f8631dcde.

The actual pre-release baseline was 440 containers and 205 unique images. Two unreferenced historical images were already missing before any Docker mutation; outputs/mcp-settings-preexisting-image-reconciliation-v1.json records that gap. Current live and recovery image pins and all retained container references were available. All resources from the actual current baseline were retained; the release added two builders, a frontend/proxy pair and one frontend image. No migration, backend replacement, production test records, permission changes or authentication fixes were included.

The final mobile footer adjustment was followed by two passing desktop/mobile browser save journeys. These overlap the earlier 25-journey suite and are not counted as separate overall test coverage.
