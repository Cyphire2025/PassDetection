# Mobile performance budgets

These are source-level regression guardrails for the iOS and Android app. They
prevent known classes of accidental performance regressions; they are not a
claim that simulator or unit-test results prove physical-device frame time,
startup time, memory, battery use, or production concurrency.

## Automated budgets

- Every production `FlatList` and `SectionList` uses a shared immutable
  windowing profile. Current profiles preserve the existing screen-specific
  values: 6-18 initial rows, 8-24 rows per batch, 35-50 ms batching, and a 5-7
  viewport window.
- Production lists do not force `removeClippedSubviews`. React Native can use
  its platform default; this avoids the documented risk of missing iOS content
  while retaining Android's native default behavior.
- High-cardinality trip and passenger searches must use `useDeferredValue` or
  `useDebouncedValue`, with derived collections memoized.
- React Compiler and Hermes remain enabled. Continuous decorative motion must
  retain reduced-motion handling, and the tab-bar blur must retain both the
  reduced-transparency and device-capability fallbacks.
- React Query does not independently refetch on reconnect/window focus because
  the synchronization runtime owns those events. Automatic query retries stop
  after two failures. Focused active-attendance polling cannot run faster than
  every 8 seconds, and the lifecycle safety refresh cannot run faster than
  every 5 minutes.
- Full synchronization, coordinated trip synchronization, and background
  workspace preparation retain two-worker ceilings.
- Bundled PNG images are capped at 12 files, 4 MiB combined, 1.75 MB per file,
  and 1.75 million decoded pixels per file. These thresholds cover the current
  four reviewed assets while stopping silent bundle/decode-size growth.

The automated contract is
`src/core/performance/__tests__/mobile-performance-contract.test.ts`.

## Required physical-device release gates

Run these on representative low-end and current iOS/Android devices using a
release build and production-like data. Record device model, OS, build commit,
dataset size, network profile, thermal state, and at least three runs.

- Android Perfetto/System Trace: cold/warm startup, list scrolling, passenger
  search, attendance scan-to-confirm, document open, and background-to-foreground.
- Android vitals: ANR rate, crash-free sessions, slow/frozen frames, peak and
  steady-state memory, excessive wakeups, network bytes, and battery impact.
- iOS Instruments: App Launch, Time Profiler, Core Animation, Allocations,
  Leaks, Network, and Energy Log for the equivalent workflows.
- Frame-time acceptance must be set from collected traces for the supported
  device tier; do not infer it from Jest, Metro, a simulator, or source review.
- Measure cold/warm interactive startup, p50/p95 API-to-visible-data latency,
  1,000-row and 10,000-row list/search behavior, encrypted document cache hit
  and miss opens, memory warnings, offline recovery, and account switching.
- Run endurance sessions covering repeated scans, sync reconnects, foreground /
  background cycles, and large document hydration. Verify no ANR, memory leak,
  runaway polling, battery drain, or stale-account publication.

Any failed physical-device gate requires trace-backed tuning. Window sizes,
animation complexity, image resolution, and visual effects must not be reduced
speculatively without that evidence and design acceptance.
