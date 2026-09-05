# Upload link configuration

Implemented locally on 5 September 2026.

## Staff configuration

Create Upload Link, Edit Upload Link, and the group's trip-details editor share the same collection settings. Sections follow this order: group details, Visa Photo, Passport, Travel Preferences, Professional Details, and Miscellaneous. New links do not collect Notes; existing stored notes are preserved when other settings are edited.

Visa Photo and Passport each have an enable switch and a compulsory checkbox. Their enabled collection methods are alternatives: one enabled method satisfies the document requirement. Visa Photo exposes live capture and photo upload independently. Passport exposes the existing front/back live scanner and device uploads independently.

Device passport uploads select from front cover, back cover, personal details page, and address details page. Personal and address details pages are selected by default. The traveller upload screen presents only selected pages in that order. If Passport is optional, travellers may skip it entirely; when they choose to upload passport pages, the selected page set must be complete.

Travel Preferences groups Base City and domestic/international airports. Professional Details groups Staff Code, Agent/Employee Code, Agency/Dealership Name, and Designation. Staff Code retains its existing behavior. The other code and organisation fields accept configurable display labels. New traveller forms do not show an Agent/Employee type selector.

Miscellaneous groups Meal Preference, custom questions, and custom details. Each enabled data field and each custom definition has an independent compulsory setting. Qualifier relationships retain their existing selection workflow and may also be optional.

## Traveller and staff behavior

- Passport device uploads have a dedicated screen with illustrative samples, replacement/removal controls, selected-file previews, and a 2 MiB limit per original image. Server-side validation enforces the limit before image decoding.
- Camera capture retains its existing front/back sequence, processing, and passport verification rules.
- Document-free, Visa Photo-only, and cover-only single/family submissions create durable records. OCR is skipped when no personal-details page was collected. Such records remain for staff review and are not automatically marked passport-verified.
- A stored passport personal-details image still has to pass the existing verification gate before final submission, even when the collection setting is optional.
- Review previews use bounded 220 × 300 portrait and 360 × 230 landscape boxes with `object-fit: contain`. Private preview requests retain upload-session or staff authorization.
- Cover images are persisted, privately retrievable, included in ZIP exports, and included in durable deletion cleanup.
- Editable professional-field labels are saved with the final submission for later staff display.
- Trip summaries show the saved field labels and actual Required/Optional/Disabled states. Editing older links preserves the effective airport selection behavior until that question is explicitly disabled.
- Preview decode failures have a retry action. Passport field highlights align with the fitted image inside each fixed frame. Family uploads and polling preserve the separate single-traveller record when switching modes.
- The public entry header shows the group's saved Departure Date and Return Date beneath its name. Date-only values use explicit UTC formatting to retain the saved calendar day; missing or invalid legacy dates are omitted independently.
- The Visa Photo upload screen includes a neutral SVG illustration on a white background, with a SAMPLE label and a 70–80% framing guide. The illustration remains beside the traveller's selected-file preview on wider screens and above it on phones. The example is drawn in `visa-photo-sample.tsx`; no photorealistic sample asset is used.
- Some HEIC/TIFF variants cannot be previewed by the browser. They keep their existing upload support and display an explicit preview-unavailable message; browser-decodable formats preview immediately.

## Database and compatibility

Apply Alembic revision `0090_upload_configuration` before serving this code. It adds nullable `client_groups.upload_configuration`, `passport_submissions.passport_cover_s3_key`, and `passport_submissions.passport_back_cover_s3_key` columns. The migration follows `0089_revoke_legacy_refresh` and preserves the existing merged migration ancestry.

A null configuration preserves legacy link defaults. Updating unrelated group details without a configuration preserves existing settings. Older custom definitions that omit `required` retain compulsory behavior. Readiness defaults and Compose configuration expect revision 0090; existing backend/worker containers must be recreated to pick up revised environment defaults.

The migration's forward SQL was generated successfully without connecting to a database. The migration was then applied successfully to the existing isolated local PostgreSQL review database. This release candidate is published on the feature branch for review; no production deployment was performed for this task.

## Verification recorded

- Full backend unit suite: 2,617 passed, 4 skipped, and 126 subtests passed.
- Subsequent readiness/rehearsal/configuration checks: 23 passed, including rejection of the preceding schema revision.
- Final full frontend unit suite: 187 passed across 48 files.
- Frontend Node contract suite: 658 passed. The traveller subset was rerun after the final extraction: 215 passed.
- The 15 traveller React/API tests passed after the final preview/state fixes. The final settings/summary fixes passed 14 focused tests and 13 related contracts.
- Backend mypy passed across 541 source files; frontend TypeScript passed.
- Backend Ruff and frontend ESLint passed. Module budgets passed without increasing limits (65 backend modules and 24 frontend modules).
- Migration topology, offline migration SQL generation, and rendered development/production Compose contracts passed.
- The optimized Next.js production build passed, including TypeScript, page generation, and route compilation. It ran alongside the development server using Next.js 16's separate production and development output directories.
- Fourteen real HTTP integration checks passed against local PostgreSQL, MinIO, and ClamAV: saved settings, required/optional fields, idempotent final submission, invalid methods, the original-image size limit, cover storage/promotion, and private public/staff previews. Evidence: `outputs/upload-configuration-http/20260905T135536-b9240b/results.json`. The reusable harness is `scripts/qa/upload_configuration_http_smoke.py`.
- Desktop/mobile browser scenarios for the create/edit dialogs are defined in `frontend/e2e/upload-link-configuration.spec.ts`; browser execution was not performed because the user requested manual inspection without computer skills.
- Backend tests ran with the installed local Python 3.13 environment; these do not substitute for production-runtime, provider, or physical-camera verification.

## Local preview state

The Next.js development server runs with live reload at `http://localhost:3000`, using the local API target `http://127.0.0.1:8000`. The login page, upload-link route, public upload route, and API proxy returned HTTP 200.

Docker Desktop was subsequently started manually by the user. The existing `passdetection-audit` PostgreSQL, Redis, MinIO, and ClamAV services are running, with the current backend source and migrations mounted from this checkout. Uvicorn watches the source for changes. API liveness and readiness returned HTTP 200, including compatible schema 0090, available security Redis, object storage, and malware scanning.

The local override lives in the ignored `outputs/local-upload-dev/compose.override.yml` file. To restart these services from the repository root:

```powershell
docker compose -f docker-compose.audit.yml -f outputs/local-upload-dev/compose.override.yml up -d --no-build db redis minio clamav backend
```

The existing local review environment has synthetic accounts and data. External AI/provider credentials are not configured there; automatic passport recognition and provider verification still need a separately configured environment. This does not prevent configuration, upload-size validation, private cover storage, or document-free submission checks.

The retained synthetic groups are named with the prefix **Upload Settings Local Review**. Their public links are recorded in the HTTP evidence report. For manual configuration review, the existing seeded administrator is `enterprise.browser.admin@example.test`. The ignored `outputs/local-upload-dev/local-review-login.html` helper contains the public test-fixture password and calculates its current MFA code locally when opened in a browser; no account/security settings were changed.
