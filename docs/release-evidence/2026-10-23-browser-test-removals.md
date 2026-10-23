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
