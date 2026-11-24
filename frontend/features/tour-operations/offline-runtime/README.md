# Standalone offline scanner

These modules maintain the coordinator scanner served at `/offline-scanner.js`.
They are bundled into one classic script so the offline shell keeps its existing
three public cache entries and does not need a network module loader.

After editing the modules, regenerate the checked-in artifact from `frontend/`:

```sh
node scripts/build-offline-scanner.mjs --write
```

`npm run build` checks that the artifact matches its normalized source hashes
and pinned Vite output. It rejects stale output; it does not silently regenerate
reviewed sources. The build disables environment-file loading and emits no
additional assets, source maps, or runtime imports.

The controller owns page lifetime and serialized scans. The view owns DOM text
and selections; the camera owns decoder startup and stream teardown. Signed
authorization validation, trusted time, protected storage, database upgrades,
legacy queue migration, and pending writes have separate owners. Authorization
and queue factories keep one page's private state in the generated IIFE.

The persisted database remains version 5. Store names, signed manifest bindings,
clock tolerances, scan identities, AES associated data, and queue capacity must
remain compatible with the online attendance services. Cache updates replace
only public assets; they preserve pending records, authorization time anchors,
keys, and active page state. A cache-version change belongs with the installed
cache update fixture, rather than a forced page reload or queue reset.

Focused tests live in `services/cold-offline-*.test.mjs` and
`services/offline-scanner-artifact.test.mjs`. The native crypto fixtures use an
asynchronous test database and synthetic decoder, while the installed-cache
fixture exercises real browser CacheStorage, IndexedDB, and key persistence.
