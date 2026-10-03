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
