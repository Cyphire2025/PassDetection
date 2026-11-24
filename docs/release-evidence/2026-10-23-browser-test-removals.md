# Authorized browser test removals

Removed at the user’s explicit request after run 39868971181 failed with 16 failed and 215 passed browser cases. These cases are removed, not passing. Original locations below refer to a86cd06999810759ff03a707a441411fc15691d3.

- ai-assistant-test-hologram.spec.ts:39 Test is the default scene with pointer, drag, keyboard, reset, and clean mode switching
- ai-assistant-test-hologram.spec.ts:261 high-quality Test portrait renders 78400 particles with all SMAA passes and releases GPU resources
- ai-assistant-workspace.spec.ts:208 conversation slides away and restores its draft, focus, and centered composer on desktop and phone
- ai-test-hologram-flow.spec.ts:71 an upward pointer stroke produces a bright displaced plume beyond the resting head and then recovers
- ai-test-hologram-idle.spec.ts:34 idle volume transports persistent particle identities through a dense assembled head
- ai-test-hologram-speech.spec.ts:138 Test mouth follows audible spectral changes and silence, not early captions, and clears on interruption
- ai-test-hologram-speech.spec.ts:231 Test speaking controls fit phone portrait and landscape, and Stop speaking stops real playback
- ai-test-hologram-speech.spec.ts:267 idle rotation pauses for microphone and audible speech while particles keep deforming, then resumes smoothly
- ai-test-landscape-controls.spec.ts:50 global hover gently pans the landscape while the head keeps its independent idle rotation
- returning-travellers.spec.ts:118 phone verification and inline draft review at 320px
- returning-travellers.spec.ts:118 passport verification and inline draft review at 320px
- returning-travellers.spec.ts:118 code verification and inline draft review at 320px
- returning-travellers.spec.ts:118 phone verification and inline draft review at 1440px
- returning-travellers.spec.ts:118 passport verification and inline draft review at 1440px
- returning-travellers.spec.ts:118 code verification and inline draft review at 1440px
- companies.spec.ts:115 all data loads documents lazily, edits current fields and retains versions at 320px

The remaining 215 browser cases and all backend, Docker, authorization, validation, storage, MCP permissions and user-data protections remain unchanged. Helpers used only by removed cases may be deleted as lint cleanup.

Follow-up run 39904568980 retained all 215 cases: 214 passed; the 1440px company-document case failed on all three attempts because the unscoped passport locator also matched version details during a tab transition. Its assertion now waits for the named Current details tab panel. This case is retained; no additional tests were removed. All other qualification jobs passed.

## Additional removal authorized during release

After the user said 'continue and if anything fails just remove it', run 39907474174 reported one failing backend case (2,063 passed in that shard): backend/tests/integration/test_company_data_exports.py::test_late_provider_start_renews_lease_before_uncancellable_write (original line 209 at ef2340bfd962b60fce536c6bbc904e9f80f974c7). Its one-second wall-clock lease expired before the intended provider-timeout path, raising export_lease_changed. Removed only this test; export runtime lease validation remains unchanged. Total removals: 16 browser cases and 1 backend case.

Run 39907474174 also failed backend/tests/unit/presentation/test_health_readiness_deadline.py::test_slow_probes_share_one_deadline_and_keep_other_capability_results (original line 129 at ef2340bf): 21 readiness responses took 8.288 seconds against a 2-second batch ceiling; 2,074 other tests passed in that shard. Removed only this test and its unused imports. The cold-readiness test, runtime deadlines, capability checks and Docker readiness qualification remain. Total removals: 16 browser cases and 2 backend cases.

The browser job in run 39907474174 completed successfully with all 215 retained cases. Docker qualification, real service integration, migrations, connector, frontend unit/coverage and backend static/audit also passed. Only the two backend tests listed above blocked this release; downstream aggregate/check failures were consequences, not additional removed checks. Remaining local tests in both affected backend files: 10 passed.

Run 39910378483 reported one failing frontend unit case: frontend/features/upload/components/fresh-member-form.test.tsx > submits the current revision after real contact mutations on a cover-only draft (api.complete called 0 times; 1,828 other unit tests passed). Removed this case under the user's instruction to remove any failing tests; the other two cases in this file and all production submission/OTP/revision checks remain. Total removals: 16 browser, 2 backend, 1 frontend unit = 19.

Run 39910378483 also failed backend/tests/unit/application/test_authored_notification_delivery.py::test_rotated_registration_does_not_repeat_accepted_or_uncertain_physical_device_attempt[accepted] (expected one initial provider call, got zero; 2,091 other tests passed in shard 1). Removed only the accepted parameter; unknown and retry variants remain. Notification runtime behavior is unchanged. Total removals: 16 browser, 3 backend, 1 frontend unit = 20.
