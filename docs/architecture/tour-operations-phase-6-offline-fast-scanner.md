# Tour Operations Phase 6 Offline Fast Scanner

## Scope

Phase 6 optimizes the coordinator scanner for fast repeated QR capture and adds offline persistence for the mobile PWA.

## Scanner Performance

- QR decode retry delay reduced for sub-second next-code detection.
- Success delay reduced so a coordinator can move from one QR to the next quickly.
- Duplicate suppression window reduced to avoid blocking different passengers while still suppressing repeated frames of the same QR.
- Camera constraints request environment camera, 720p, and high frame rate where supported.

## Offline Storage

The PWA stores:

- Pending attendance scans in IndexedDB.
- Last-known assigned groups in localStorage.
- Last-known group passenger lists in localStorage.

Pending scans include:

- session id
- QR payload
- client event id
- scan timestamp
- device id

## Sync Behavior

- Online scans are sent immediately.
- Offline scans are queued locally.
- Network failures while online also queue the scan.
- The PWA syncs automatically when the browser comes online and retries every 15 seconds while online.
- The scanner page shows online/offline state, pending scan count, and manual sync.

## Remaining Hardening

- Background Sync API integration for supported browsers.
- Conflict review UI for permanently failed sync events.
- Offline activity creation if a coordinator starts a new activity without network.
