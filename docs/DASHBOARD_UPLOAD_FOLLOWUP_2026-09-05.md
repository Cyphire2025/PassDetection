# PDF uploads, sidebar and dashboard copy — 5 September 2026

This follow-up addresses the reported local Rename/Distribution security-scanning error, the visible sidebar scrollbar, and unnecessary dashboard wording. The reviewed changes are published on `codex/dashboard-enterprise-20260905`; nothing was deployed to the VPS.

## Causes and corrections

The isolated review Compose file previously disabled document ingestion and malware scanning because it was created for visual review. `DocumentIngestionDisabledError` then fell through the shared PDF boundary's generic validation handler, incorrectly reporting a security rejection. That response did not establish that the user's PDFs contained malware.

- The local stack now enables ingestion with the pinned real ClamAV service, a persistent signature volume, a health-gated backend dependency, and a 10-second scanner deadline. The scanner runs unprivileged, drops Linux capabilities and exposes no host port.
- Starting the actual scanner exposed a root-owned temporary log mount. The mount now specifies ClamAV's UID 100/GID 101 and mode 0750 in both the local review file and shared deployment Compose. The Compose verifier protects this requirement. No production service was changed at runtime.
- Rename, Distribution verification, and Distribution upload distinguish disabled ingestion, missing configuration, temporary scanner/evidence failures, positive scan rejection, and unreadable/encrypted PDFs. Processing stays blocked when scanning cannot establish a clean result.
- ClamAV responses are read as bounded complete NUL-terminated frames across TCP fragments. Only the exact clean verdict is accepted; daemon/protocol errors are service failures rather than infection claims.
- The local storage configuration now signs browser-readable links at `http://127.0.0.1:59000`, with MinIO bound to loopback. Backend storage still uses the private Docker hostname. This repairs local document opening after upload without publishing the storage service on the LAN.

The sidebar hides only its own scrollbar while retaining scrolling. At the user's subsequent request, the bottom collapse control was removed and the desktop logo now toggles the persisted sidebar width, with an accessible action name, expanded state and keyboard operation. The mobile drawer retains its existing close controls. Collapsed links retain accessible names. Dashboard copy removes decorative header labels, redundant badges, self-promotional wording and technical implementation phrases; useful restrictions and workflow instructions remain. Synthetic display names now use Local Administrator, Local Review Workspace and Travel Review Group; login credentials were preserved. Document count labels use correct singular/plural forms.

## Verification

- Backend: **326 tests and 3 subtests passed** on Python 3.11, including 27 multipart HTTP cases across the three upload boundaries and 17 scanner protocol cases. Affected runtime/test Ruff checks and runtime mypy checks passed.
- Frontend: full zero-warning ESLint, TypeScript, **659 source contracts**, and **7 sidebar/settings/WhatsApp interaction tests** passed. The document count wording correction passed scoped zero-warning lint and full TypeScript. An existing contract's literal wording assertion was updated to retain its check for separate file/passenger counts; all 659 contracts passed again. Both final Docker runtime builds succeeded.
- Compose runtime contracts and working-tree whitespace checks passed.
- The subsequent logo-toggle adjustment passed all four existing sidebar/mobile-navigation interaction tests, scoped zero-warning ESLint, and the Docker production build including TypeScript.
- Real local API: **11 recorded checks passed** with ClamAV enabled. Native-text visa and ticket PDFs produced the correct passenger name and document types; Rename individual and ZIP downloads passed. Distribution verified both types at 0.97 confidence, completed staged upload/assignment, and returned byte-identical stored files. Clean malformed files and the harmless antivirus test signature were rejected in both workflow families.
- A real scanner outage/recovery rehearsal passed **four checks**: readiness returned 503; a clean Distribution PDF was blocked with 503 and `Retry-After: 30`; the scanner and API recovered to healthy/200; and the same PDF then verified and matched successfully. The scanner was restored in a finally-protected operation. Evidence: `outputs/dashboard-qa/pdf-upload-followup/outage-results.json`.
- Browser: Rename processed two synthetic PDFs with one visa, one flight ticket and zero rejections, producing `ASHA_MEHTA_VISA.pdf` and `ASHA_MEHTA_TICKET.pdf`. Distribution checked and accepted the synthetic visa, matched Asha Mehta, and completed Upload Accepted. The existing synthetic API assignment and browser upload are both visible in the test group; no provider message was sent.
- Browser copy review rendered all **17 main navigation destinations**, plus the Rename/Distribution subpages, without an observed application error. The reviewed browser session reported no warning/error console entries. This is a focused follow-up, not another full workflow audit of every nested route.
- Chrome sidebar verification: computed `scrollbar-width: none`, `overflow-y: auto`, content taller than the viewport, and wheel scrolling from 0 to approximately 262 pixels. The collapse button has no visible text; Enter collapses to 76 pixels and expands again. Screenshots were visually reviewed.

Chrome's extension denied automated file selection because file URL access was disabled. Chrome layout/sidebar checks succeeded; the actual browser file-upload flows were completed through the built-in browser using the same local dashboard. No extension permission was changed.

All upload fixtures are synthetic and isolated in `passdetection_ci_browser`. The user's 14 original PDFs were not supplied to this run, so these results do not assert their individual content or matching outcomes. Representative production OCR accuracy, real provider delivery and VPS readiness remain separate from these local checks.

Evidence is in `outputs/dashboard-qa/pdf-upload-followup/api-results.json`, `browser-results.json`, and `browser-*.png`, with backend regressions in `outputs/dashboard-qa/pdf-scanner-regression-311.log`. The guarded API runner is `scripts/qa/pdf_upload_followup.py`. The updated source/image fingerprint is recorded by `scripts/qa/dashboard_release_evidence.py` in `outputs/dashboard-qa/release-evidence.json`.
