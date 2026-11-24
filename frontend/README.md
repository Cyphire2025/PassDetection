# Global Connects Dashboard web application

This directory contains the Next.js dashboard and browser traveller/coordinator
flows. The Expo application is maintained separately in `../mobile/`. Read the
repository [working instructions](../AGENTS.md) and this directory's
[framework instructions](AGENTS.md) before changing application code.

## Local development

Use the reviewed Node.js and npm versions in
[`tooling/toolchain.json`](../tooling/toolchain.json). Install the existing lock
with `npm ci`; avoid regenerating dependency locks for unrelated changes.

From this directory:

```sh
npm ci
npm run dev
```

The development server uses port 3000 unless explicitly configured otherwise.
Follow the repository [development setup](../README.md) for the Python API and
local environment configuration. Public Next.js environment variables are
browser-visible; API credentials and production data belong outside client
configuration and test fixtures.

## Source ownership

- `app/` owns routes, metadata, layouts and loading/error boundaries.
- `features/` owns each workflow's UI, hooks, API adapters and services.
- `components/`, `hooks/`, `lib/`, `providers/` and `stores/` contain shared
  primitives and session/transport infrastructure.
- `types/` and `constants/` contain shared contracts and route definitions.
- `public/` includes the explicit public offline scanner runtime and assets.

Keep permission checks, private request ownership, upload receipt identities and
document/camera acceptance rules intact when extracting a focused owner. Move
the meaningful tests and coverage obligations with the implementation.

The standalone offline scanner is maintained in
[`features/tour-operations/offline-runtime/`](features/tour-operations/offline-runtime/README.md)
and generated into the existing public script. Its source guide explains the
regeneration command and the stale-artifact check in the normal build.

`features/upload/components/passport-detail-samples-original.tsx` retains the
original detail-page illustrations as reference artwork. Retired cover and
portrait PNG examples are preserved in the local `Not related to project`
archive and are no longer public assets. Release health checks use the existing
PWA icon; the active upload flow does not depend on those retired examples.

## Verification

During implementation, run the affected tests and checks for a coherent change.
Examples:

```sh
node node_modules/vitest/vitest.mjs run path/to/affected.test.tsx --maxWorkers=1 --pool=threads
node --test path/to/affected.contract.test.mjs
npm run type-check
npm run lint
npm run maintainability:check
```

The repository working instructions and CI define the complete integration and
release gates, including coverage, production builds and browser journeys. A
focused source or component test does not qualify a production deployment.

Browser journeys use [`playwright.config.ts`](playwright.config.ts) and
[`config/e2e-isolation.ts`](config/e2e-isolation.ts). They own isolated loopback
services on ports 3100 and 3199 and override API destinations with their fixture
server. Use synthetic accounts and documents, and preserve that isolation.

## Existing VPS release

This frontend participates in the existing single-VPS release. Use the
[current release and storage procedure](../docs/CURRENT_RELEASE_AND_STORAGE.md)
and [production readiness requirements](../docs/PRODUCTION_RELEASE_READINESS.md).
The repository release helpers qualify and activate the intended revision;
changing application branding or source structure does not require a new
hosting setup. This README does not deploy or migrate the VPS.
