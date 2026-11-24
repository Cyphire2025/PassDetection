# Passport extraction review and cleanup

Status: implementation and focused/shared regression verification complete.

## Findings and changes

- The deployed worker already reads passport images directly through Gemini. The local OCR service was never constructed by production wiring and its constructor injection was deliberately unused. Removed that dormant dependency and its obsolete test mocks.
- Removed 51 unused local passport OCR files: image preparation, MRZ image detection/reading/correction, ROI fallback and placeholder extractors, local extraction cache/confidence scoring, benchmark machinery, and tests exclusively exercising those removed implementations. The exact removal manifest is `extraction-removed-files.json`. Dependency reachability was checked across application, scripts, tests and qualification runners; deletion is not a claim that every line of each obsolete module received a security audit.
- Retained the saved TD3 MRZ checksum parser because returning-traveller acceptance actively uses it to validate historical evidence. Removed its unused OCR-recovery algorithms while preserving the actual saved-evidence parsing behavior. New regression coverage checks valid identity extraction and rejection of corrupted evidence. Historical database fields, accepted provenance, published migrations and AI MRZ visual evidence remain compatible.
- Removed unused local MRZ/ROI tuning settings and example values. Existing server environment keys remain tolerated by the settings model's `extra=ignore`; no production credentials, environment files or deployment identities were changed by this cleanup. The later, directly related PassportEye dependency removal regenerated reviewed locks and removed19runtime/18development orphan packages with no retained package version or hash changes; see `ocr-dependency-removal.json`.
- Removed obsolete local-OCR memory workloads and the MRZ normalizer import from runtime qualification. Existing AI serialization, PDF OCR, image validation and ECR workloads remain. Tesseract stays available because visa/ticket PDF OCR still actively uses it.
- Updated the public scan-again endpoint's documentation summary to identify its AI behavior. The complete API snapshot was regenerated and reviewed alongside branding. Its final integration update changes only `/info/description` from local MRZ wording to Global Connects Dashboard and AI extraction; title/version and request/response/security contracts are unchanged in that metadata update.

## Verification

- Full backend Ruff: passed; changed extraction/release sources also passed with the matching `.venv`.
- Full backend mypy: passed, 1,143 source files.
- Backend module quality budgets: passed, 130 modules.
- Architecture boundaries: passed.
- Focused passport processing, saved evidence, returning-traveller acceptance and legacy approval tests: 124 passed, 7 subtests passed (49.78 seconds).
- Shared PDF resources, document matching and AI-priority regressions: 100 passed, 4 subtests passed (0.50 seconds).
- Updated runtime/memory probe Python compilation and changed-source whitespace checks: passed.
- Final combined extraction, saved-traveller evidence, PDF/priority and release regression rerun using matching `.venv`: 259 passed, 11 subtests passed (72.73 seconds). Earlier isolated passes used `.venv311`; neither environment was modified.
- Container runtime and cgroup memory qualification were updated but have not been run in this Windows session. No external provider calls or production data used.

## Reviewed source paths

These paths received focused source/dependency review relevant to this extraction change. Other unrelated backend features are outside this agent's reviewed coverage.

- `backend/app/infrastructure/processing/worker_runtime.py`
- `backend/app/application/use_cases/passports/process_passport_submission_job_use_case.py`
- `backend/app/application/interfaces/passport_extraction.py`
- `backend/app/application/interfaces/mrz_parser.py`
- `backend/app/infrastructure/ocr/td3_mrz_parser.py`
- `backend/app/infrastructure/travellers/draft_runtime.py`
- `backend/app/infrastructure/travellers/draft_extraction.py`
- `backend/app/application/travellers/accepted_source.py`
- `backend/app/core/config/settings.py`
- `backend/app/presentation/api/v1/routes/passport_routes/public_upload.py`
- `backend/tests/unit/application/test_passport_processing_reliability.py`
- `backend/tests/unit/application/test_traveller_accepted_source.py`
- `backend/tests/unit/infrastructure/test_saved_mrz_validation.py`
- `scripts/qa/qualify_runtime_image.py`
- `scripts/qa/probe_bounded_memory.py`
- `scripts/qa/qualify_bounded_memory.py`
- `.env.example`
