Final reachable architecture: the primary portal now uses the lean error view directly. The conditionally unreachable legacy UploadFlow and its earlier extracted happy-path modules are retired. See legacy-upload-retirement-progress.md for the final architecture, current coverage and original-source manifests. Earlier checkpoint details below are historical.

# Current public upload browser migration and OTP fixes

Status: completed for the eleven mapped legacy scenarios. Runtime source is frozen; both existing browser spec files now target TravellerPortal → FreshFlow and the current private-draft APIs.

The former five contact cases and six recovery cases became twelve current tests. Missing and expired private drafts have separate checks. Negative assertions were preserved for invalid OTP, delivery failure and retry, expired/rejected proof, completed family member preservation, closure during recovery, transient private GET failure, AI extraction failure, and a lost document-upload response. No negative case was skipped, and production workflows were not changed to fit legacy screen ordering.

Two concrete current-app bugs were fixed:

1. The server increments draft.revision during OTP verification, but the form previously completed using its older revision. The accurate fixture first observed expected_revision 3 versus authoritative 4. The contact controller now reads the authoritative private draft after successful verification before exposing the proof to the form. The request signal still guards late completion. If that read fails, submission remains blocked.
2. A proof rejected by the server previously stayed shown as verified, with no direct re-verification action. The submission controller now invalidates only that proof object on the structured verification error. Entered details, member session, completed family state and final idempotency key remain intact. Renewed verification with the same backend proof row ID is accepted; a new ID is not assumed.

Contact and submission state were extracted into cohesive hooks rather than raising the existing view limits. FreshContact is 23 lines and FreshMemberForm 49 lines, down from 49 and 58. New contact/submission hooks are 46 and 32 lines. The four final current measurements and proposed ceilings are in fresh-contact-budget-candidates.json; parent owns integration and the strict budget hash.

Current backend contracts were traced before fixtures were finalized. A missing fresh draft starts empty through the actual start endpoint; the fixture does not invent a 404 start response. An expired existing draft returns claim_expired 410. Current Fresh validation and backend fresh_publication both require a successfully checked passport information page. The AI-failure scenario permits manual field edits but proves those edits cannot bypass that gate, then verifies a clear replacement and a needs_review result. The older legacy direct manual bypass was not added to the new workflow.

Verification:

- 12 migrated browser tests passed after final test-only missing-draft semantics refinement (31.3 seconds).
- A frozen-runtime 20-test run passed (59.6 seconds), including those twelve scenarios, four existing FreshFlow flows and four actual-route fallback cases. The current 12-test rerun follows the final test-only refinement.
- Four focused Vitest files,19 tests passed. Three new regressions cover authoritative revision after OTP, renewed same-ID proof after rejection with preserved fields/key, and blocked submission after a failed revision read.
- TypeScript and scoped ESLint passed. Existing frontend module budgets were not edited by this lane; both modified views remain below their prior ceilings.
- The desktop/mobile contact screenshots were produced with synthetic data. The 390 px screenshot was visually inspected; fields, verified status and submit control are readable without horizontal overflow.

The first migration run exposed the stale OTP revision. A later run had one Confirm-code timeout while runtime modules were edited during development; a fresh run with frozen runtime passed all 20. These earlier failures are retained as debugging history, not passing evidence. The old 11-case CI risk is now replaced by current passing tests in the same two files. Browser API responses remain isolated synthetic fixtures, so these receipts do not establish real provider, private storage, PostgreSQL, or VPS qualification.

Full current physical reads and SHA 256 s are in fresh-public-upload-reviewed-files.json (28 records). The updated passport-upload-review-pending.json remains conservative:141 of 209 passport/upload runtime files do not yet have matching full-source review evidence. Large camera/quality modules remain pending.

Changed paths after the previous validated checkpoint:

- frontend/features/upload/components/fresh-contact.tsx
- frontend/features/upload/components/fresh-member-form.tsx
- frontend/features/upload/hooks/use-fresh-contact.ts (new)
- frontend/features/upload/hooks/use-fresh-member-submission.ts (new)
- frontend/features/upload/components/fresh-member-form.test.tsx
- frontend/e 2 e/public-upload-contact-otp.spec.ts
- frontend/e 2 e/public-upload-recovery.spec.ts
- frontend/e 2 e/support/fresh-public-upload.ts (new)

Screenshot evidence:

- C:/Users/nipun/Desktop/PassDetection/.tmp/current-public-draft-browser-frozen/public-upload-contact-otp--2e39b-efore-submitting-on-desktop-chromium/current-contact-desktop.png
- C:/Users/nipun/Desktop/PassDetection/.tmp/current-public-draft-browser-frozen/public-upload-contact-otp--aa079-before-submitting-on-mobile-chromium/current-contact-mobile.png
