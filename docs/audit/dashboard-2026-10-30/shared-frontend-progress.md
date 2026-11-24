# Shared frontend source review

All47 runtime TypeScript/TSX files in frontend/lib, stores, providers, components/ui and components/layout have full physical-source review records in shared-frontend-reviewed-files.json.42 were read directly in this lane. Five existing full security reviews were reused with their reviewer attribution, source ledger reference and exact current SHA verified: auth.store, API client, streamed download, download filename and public URL handling. This is source coverage for those prefixes; it does not imply every feature or deployed integration is complete.

## Verified changes

- Clipboard fallback always removes its temporary textarea, including when the browser throws. The original failure still reaches the caller. This avoids leaving copied text in a detached page-level helper across route/access changes.
- Input descriptions merge caller-provided IDs with the currently rendered validation error or hint. Hidden hint IDs are no longer referenced while an error is displayed.
- Mobile navigation uses the existing shared modal boundary instead of a second partial focus trap. It now makes the background inert and contains focus, while preserving Escape/Tab behavior, initial close-button focus, nested dialog ordering, route-close handling and header-trigger focus return. The drawer dropped from103 to53lines. A stable optional return-target resolver preserves its original initially-open behavior.
- Corrected one malformed country-table entry that produced a one-letter option. Existing country tests now assert the code length of every generated two/three-letter option.
- The liquid renderer releases its WebGL context on initialization failure where the context-loss extension is available. Previously the constructor could throw before the owner received an instance, leaving the fallback path unable to call destroy. A fault-path regression verifies context release and propagation of the original failure.

## Verification

- Existing modal, existing drawer/sidebar, new drawer/input/clipboard and query-provider tests:6files,30tests passed.
- Existing country Node tests:6passed, with complete option-shape assertions added.
- New WebGL initialization fault-path regression:1passed.
- ESLint across lib, stores, providers, components/ui and components/layout passed after the shared interaction fixes. Final targeted checks including the renderer guard also passed.
- TypeScript passed again after the final renderer guard.

## Scope limits

Reviewed asynchronous work includes live/history query cancellation and scope changes, sensitive-state recovery, clipboard/GPU/observer/listener lifetime, private URL boundaries, and privacy-safe error telemetry. The shaders use repository constants and controlled local artwork; this pass did not accept user shader or private-image sources.

The large static endpoint registry and liquid renderer were read completely. The renderer remains a candidate for coherent decomposition and device/GPU profiling. Static inspection and mocked GPU fault injection do not establish frame-time or memory performance on every device. No additional browser services were started for this review; existing real DOM keyboard regressions and the main integration checks provide the relevant supplements.
