# Dashboard dependency remediation

This is the dashboard dependency follow-up to the manual source audit. It uses npm registry metadata, upstream release/advisory records and ordinary local verification. No Codex Security tool, production dataset, live business provider send, deployment or push was used.

## Reviewed updates

| Package | Before | After | Reason |
| --- | --- | --- | --- |
| `next` and matching `eslint-config-next` | 16.3.8 | 16.4.3 | Patched supported Next 16 release, including the fixes released in 16.4.1 and subsequent proxy/runtime corrections. Matching lint configuration retained. |
| `follow-redirects` | 1.16.0 | 1.16.1 | Minimum patch for the two reported credential-header stripping defects; exact override remains within Axios's declared range. |
| `zod` | 4.4.3 | 4.6.6 | Minimum patch for oversized constrained-collection validation resource use. |
| `vitest`, `@vitest/coverage-v8` and their matching internal packages | 4.1.11 | 4.1.12 | Minimum matching patch for manual/redirect mock registration and Windows traversal issues in the installed test tooling. |
| Transitive `vite` | 8.2.2 | 8.2.4 | Minimum patch for the reported editor command handling vulnerabilities. |
| `jsdom`'s overridden `undici` | 8.10.2 | 8.12.2 | Minimum patch for the reported TLS, redirect/cache and response-parser issues. npm hoisted the patched dependency to the root installation. |

Node **24.21.0**, npm **11.20.0**, React **19.2.4**, TypeScript and all unrelated versions remain unchanged. `tooling/toolchain.json` was not modified. Direct Next/Zod/Vitest/coverage/lint entries and the three security overrides use explicit versions; no audit ignore or `npm audit fix` was used.

The initial npm resolution incidentally advanced 20 unrelated Rolldown/binding/type, Chai and Picomatch records. Their dependency ranges are unchanged by the reviewed patches, so the previous reviewed records were retained, then npm resolved the lock again and a clean `npm ci` validated the resulting graph. The final lock has the same **633 records** as before: **24 package version changes**, the relocation of Undici (one removed path and one added path), and the root dependency-spec record. All other parsed lock records are identical. Exact deltas are in [frontend-dependency-deltas.json](frontend-dependency-deltas.json).

## Primary evidence

The [Next 16.4.3 release](https://github.com/vercel/next.js/releases/tag/v16.4.3) records the supported backports, including the proxy runtime correction. Upstream advisories identify 16.4.1 as patched for [SVG image optimization](https://github.com/vercel/next.js/security/advisories/GHSA-2464-fhr4-w9xw), [Server Actions resource use](https://github.com/vercel/next.js/security/advisories/GHSA-p3m5-59mp-jv5r) and [typed-array cache serialization](https://github.com/vercel/next.js/security/advisories/GHSA-673q-mjm6-r5xr).

The maintainer's [follow-redirects advisory](https://github.com/follow-redirects/follow-redirects/security/advisories/GHSA-q3jh-wrc6-jgq8) identifies 1.16.1 as patched. The [Zod 4.6.6 release](https://github.com/colinhacks/zod/releases/tag/v4.6.6) includes collection-size checks before element parsing. The [Vitest 4.1.12](https://github.com/vitest-dev/vitest/releases/tag/v4.1.12), [Vite 8.2.4](https://github.com/vitejs/vite/releases/tag/v8.2.4) and [Undici 8.12.2](https://github.com/nodejs/undici/releases/tag/v8.12.2) upstream releases confirm the development-tool patches.

[frontend-dependency-registry-evidence.json](frontend-dependency-registry-evidence.json) preserves exact registry versions, runtime engines, peer/dependency ranges and distribution integrity values for the eight directly reviewed package/version pairs. A local check compared every pair against both the final lock integrity and installed package version; all matched. The Next, Vitest, Vite and Undici runtime requirements accept the reviewed Node 24.21.0 runtime.

## Verification

Version-matched bundled Next documentation was read before and after the upgrade for Proxy, CSP nonce propagation, dynamic rendering, route handlers and Vitest. Existing `proxy.ts` request/response CSP forwarding and the root layout's request-time rendering match that contract. No application code or configuration migration was required.

Completed checks so far:

- `npm ci --no-fund`: passed, exit 0 confirmed in npm's local command log.
- `npm ls --depth=0`: passed with the patched direct packages and matched Vitest/coverage versions.
- `npm audit --omit=dev --json`: **zero vulnerabilities**. Original findings remain in the before artifact; patched result is [frontend-dependency-audit-after.json](frontend-dependency-audit-after.json).
- `npm audit --json`: **zero vulnerabilities** after the additional test-tool patches. [Full patched audit](frontend-dependency-audit-all-after.json); [intermediate tooling findings](frontend-dependency-audit-tooling-before.json).
- `npm run type-check`: passed, including Next route generation and `tsc --noEmit`.
- `npm run lint`: passed.
- `node node_modules/vitest/vitest.mjs run --maxWorkers=1 --pool=threads`: **230 files / 1,554 tests passed** in 348.48 seconds. Includes Proxy/CSP, auth, upload/recovery, Zod schema, shared download and isolation coverage. [Complete output](frontend-dependency-vitest-final.txt).

- `npm run build`: passed on Next 16.4.3, including the MediaPipe CSP binding check, optimized compilation, route generation and strict TypeScript build. [Build output](frontend-dependency-build-final.txt).
- Initial production browser run: **eight checks passed** against `next start`: cookie login/logout, rejected refresh, lower-privilege direct-link denial, fresh draft resume at 320/1440 px, independent family drafts, interrupted completion without duplication, and unique response nonces matching rendered framework scripts. [Output](frontend-dependency-browser-next-start.txt). That launcher emitted Next's standard standalone-output warning; the completed final run below closes that launcher limitation.

The required CI coverage command passed with every configured per-file threshold unchanged: **230 files / 1,554 tests**, 358.98 seconds; **93.77% statements, 87.77% branches, 94.89% functions and 97.23% lines**. Shared modal focus return has 100% statements/functions/lines and 70% branches; keyboard boundary has 94% statements, 92.22% branches, 100% functions and 97.46% lines. No thresholds or behavior tests were changed. [Coverage output](frontend-dependency-coverage.txt), [per-file summary](frontend-dependency-coverage-summary.json). An initial PowerShell launch through `npm.ps1` lost the unquoted `--` separator and let npm consume the worker options. Its child command used default workers; that run was stopped and is not counted. The corrected Windows equivalent is `npm.cmd run test:unit:coverage "--" "--maxWorkers=1" "--pool=threads"`; the actual Vitest child command was verified to contain `--coverage --maxWorkers=1 --pool=threads`.

The build explicitly overrides API origins to the loopback fixture so existing local environment files cannot select a real backend for these checks. Browser API requests use synthetic fixtures; no real provider send is possible in these checked flows. The final standalone run passed **nine checks in 26.3 seconds**: the seven existing authentication/fresh-traveller journeys, a real HTTP rewrite check for `/api/v1/`, `/oauth/mcp/` and `/mcp/native-transfers/`, and request-specific nonces matching actual framework scripts. The rewrite fixture explicitly emits a sentinel upstream header and no-store policy; the Next response must preserve both plus the backend status/body. An earlier extra header assertion assumed the existing realtime fixture already emitted no-store on its 404 response; that fixture did not. The test fixture was corrected to define the upstream contract, without changing application code. The final repeat passed all nine checks. [Standalone browser output](frontend-dependency-browser.txt), [structured results](frontend-dependency-browser.json).

The generated standalone directory received public/static assets in the same arrangement as the production Dockerfile. `next`, `react` and `react-dom` resolution was verified to remain inside that emitted directory, avoiding a false pass through parent-checkout modules. This qualifies the emitted Windows runtime under Node 24.21.0; the Linux container and VPS deployment remain separate CI/release checks.

Final `npm audit --omit=dev --json` and `npm audit --json` both passed with zero findings after the clean install and browser checks. `npm run maintainability:check` passed for all 124 currently budgeted modules. Supporting agent ai_extraction added exact package/lock release-policy bindings against both fixed baseline commits and reported 13 strict release tests plus nine subtests passing. No package/lock changes followed those bindings.

The package/lock bytes are frozen for subsequent source review. Root owns final combined verification after other source work freezes; these results establish this dependency-upgrade checkpoint rather than later source changes.
