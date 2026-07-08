# Tour Operations Phase 2 Scanner Proof

## Scope

Phase 2 validates the browser camera and continuous QR scanning experience before attendance workflows are built.

This phase does not create attendance sessions, persist scan records, assign passengers, or implement offline queues.

## Implementation

The scanner proof uses `@zxing/browser` through an isolated hook:

- `features/tour-operations/hooks/use-continuous-qr-scanner.ts`

The proof UI is:

- `features/tour-operations/components/qr-scanner-proof.tsx`
- `/tour-operations/scanner-proof`

## Validation Behaviors

The proof screen supports:

- Secure-context camera checks.
- Camera permission error handling.
- Back-camera preference where device labels are available.
- Continuous QR decoding.
- Local duplicate suppression for rapid repeated reads.
- Recent scan history for manual field testing.
- Vibration feedback where supported.
- Torch toggle where the browser exposes torch controls.

## PWA Basics

Phase 2 adds:

- `app/manifest.ts`
- `public/pwa-icon.svg`
- `public/sw.js`
- `components/pwa/pwa-registrar.tsx`

The service worker caches the Tour Operations shell for install testing only. It is not the future offline attendance sync layer.

## Manual Device Test Checklist

Before Phase 3 starts, test this route on real devices:

- Android Chrome over HTTPS or localhost tunnel.
- iPhone Safari over HTTPS or localhost tunnel.
- Camera permission allow/deny flows.
- Back camera selection.
- QR detection speed under normal light.
- QR detection under low light.
- Repeated scans of the same QR.
- Different QR codes in quick sequence.
- PWA add-to-home-screen install behavior.

## Phase Gate

Phase 3 can start after the scanner proof is usable on target mobile devices. If iPhone Safari scanning is slow or unreliable, resolve that before building coordinator workflows on top of it.
