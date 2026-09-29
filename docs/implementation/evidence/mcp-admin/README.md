# MCP administration frontend qualification

Local qualification on 2026-09-29 in the managed `mcp-application-workflows` checkout.

## Verified behavior

- MCP administration and consent routes require the active `super_admin` role and `mcp.manage` capability. Direct navigation by another role mounts no MCP API queries and exposes no MCP navigation entry.
- Connections show the granted capabilities and authorization expiry. Administrators can rename, narrow permissions, revoke, refresh status, and operate the emergency access switch through the existing authenticated API client.
- History uses server pagination and action search. Connection setup shows the application endpoint, approved clients, and explicit release qualification status.
- Versioned Windows connector setup shows the reviewed 0.1.0 source installation, browser sign-in, Codex stdio fields, and revocation/recovery commands. Missing client approval is surfaced. It does not present an unpublished hosted installer or unqualified file tools as available.
- Consent validates the exact approved client, callback, resource, requested scopes, and S256 request. It accepts bounded opaque OAuth state, authorizes only selected permissions, prevents duplicate submissions, and returns only to the validated callback.
- The interface labels unfinished workflow qualification as in progress. Displaying a permission category does not claim that its application workflows are qualified.

## Checks

| Check | Result |
| --- | --- |
| Combined Vitest run: WhatsApp, MCP, route capabilities, group overview, document delivery | **252/252 passed**, 23 files |
| MCP browser checks: management at 1440/768/390 px, role isolation, consent callback | **5/5 passed** |
| Additional mobile consent footer capture/check | **1/1 passed** |
| `npm run type-check` (route generation plus global TypeScript) | Passed |
| Focused ESLint across MCP routes/components/hooks/API/tests, navigation/endpoint changes, WhatsApp production changes | Passed |
| WhatsApp Node contract/utility suite earlier in this implementation | **104/104 passed** |

The final combined unit run used `npm run test:unit -- features/whatsapp features/mcp features/auth/config/route-capabilities.test.ts features/passports/components/passport-group-overview-panel.test.tsx features/passports/components/group-document-delivery-panel.test.tsx`. The breakdown was 196 WhatsApp, 40 MCP/auth, and 16 overview/document tests.

Browser coverage lives in `frontend/e2e/mcp-administration.spec.ts`. It launches the actual Next.js application and intercepts HTTP at the API boundary with isolated fixtures. No live account, live connection, provider delivery, or real Codex client was used. Assertions check submitted scopes, opaque state roundtrip, absence of protected requests for other roles, browser errors, and horizontal overflow. Application control mutations remain inside the mocked API fixture.

The standard local Playwright launch initially hit the known Turbopack limitation with the shared `node_modules` junction outside the worktree root. The passing run used a temporary Playwright configuration that appended Next's documented `--webpack` option to the dev-server command. That temporary configuration was removed; dependency files and the repository Playwright configuration were not changed.

## Visual evidence

Visually inspected desktop, tablet, mobile connection views, desktop/mobile connector setup, and both mobile consent positions. Text, cards, controls, and narrow layouts fit without horizontal overflow or overlapping actions. Mobile forms and setup instructions scroll within the existing dashboard content area.

- [Desktop connections](mcp-connections-1440.png)
- [Tablet connections](mcp-connections-768.png)
- [Mobile connections](mcp-connections-390.png)
- [Mobile consent](mcp-consent-mobile.png)
- [Mobile consent controls](mcp-consent-mobile-footer.png)
- [Desktop connector setup](mcp-setup-1440.png)
- [Tablet connector setup](mcp-setup-768.png)
- [Mobile connector setup](mcp-setup-390.png)

These checks establish local frontend behavior with fixture responses. They do not establish end-to-end backend authorization, production deployment, real provider receipt arrival, or installation and authentication of a real Codex connector. Those release gates require their separate evidence.


## Later Files/Tools and retry-recovery checkpoint

The updated Administration suite passes all five cases again in a joined
8-case run with normal-send browser recovery (34.9s). It shows distinct ready,
unknown, imported and ingested file states without labeling them delivered;
Tools lists both required capabilities for WhatsApp header transfers. The
current connector setup shows0.2.0, superseding the earlier0.1.0 screenshot
checkpoint above. Actual Codex and production access remain unqualified.

Six new Files/Tools screenshots were copied without replacing the earlier
connection/setup/consent evidence. Desktop/tablet text and badges fit; mobile
cards wrap and the tab strip scrolls horizontally inside its own boundary.
Browser overflow assertions pass. The viewport screenshots do not show every
lower file row; the test asserts each required status in the rendered page.

- [Desktop files](mcp-files-1440.png)
- [Tablet files](mcp-files-768.png)
- [Mobile files](mcp-files-390.png)
- [Desktop tools](mcp-tools-1440.png)
- [Tablet tools](mcp-tools-768.png)
- [Mobile tools](mcp-tools-390.png)

The temporary webpack test configuration was removed after the run, and the
Playwright-managed development server stopped. UI state and all actions used
isolated synthetic fixtures.
