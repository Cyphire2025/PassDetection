# Upload controller separation and behavior qualification

This is dashboard-only work. The HTTP request shapes, storage credentials, single/family workflow and native clients remain compatible. The final release evidence is collected in [frontend-phase2-evidence.json](frontend-phase2-evidence.json); the original audit remains unchanged.

## Ownership and invariants

`use-upload-operation.ts` provides synchronous admission and a discriminated operation reducer shared by document persistence, extraction retries, replacement and final submission. A new generation is admitted only after the current operation finishes or is cancelled. Token changes and unmount abort the current generation. An older promise's cleanup cannot release a newer operation, and cancelled results cannot change the current screen. These are behavioral guards, not a claim that React state alone cancels an already accepted server request.

`use-upload-documents.ts` owns file preparation, server persistence, extraction progress, resume, retry and replacement. Single-mode recovery writes its opaque credential before uploading, then writes the acknowledged submission ID before extraction. Family mode places the acknowledgement in the member's current in-memory state before extraction; **family recovery across a page reload is not claimed**. Extraction failure preserves a saved result for manual review or retry. Retry fills missing extracted fields while preserving current manual edits. Replacement rotates the credential only after the discard endpoint acknowledges the old saved upload.

`use-upload-submission.ts` owns review submission and server failures. The shared pure validator applies the same configured-field policy to single and family records. Each family response updates its member before the next request is attempted; a subsequent retry skips completed members and preserves per-member verified contacts. Expired contact proof reopens verification. Both delayed submission results and a delayed link-status error are fenced by the current operation generation.

`family-upload-state.ts` and `use-upload-family.ts` own count drafts, normalized member counts, selection and member patches. Resizing preserves retained member identity and credentials; reducing the count clamps the selected index. Functional updates merge with the current member instead of a stale extraction snapshot. `upload-review-panels.tsx` owns review rendering and delegates mutations through typed callbacks.

## Measured checks

The focused boundary run passes **71 tests in eight files**. It exercises concurrent clicks, unmount/token-change/cancellation, saved-upload failure and resumption, late acknowledgements, family extraction cancellation, preservation of manual fields, replacement failure, proof expiry, partial family submission and retry, configured-field validation, member resize/selection and actual rendered field callbacks. Twenty-five upload source contracts also pass; the complete Node contract suite has 707 passing cases. Source assertions support structural checks and are not counted as substitutes for the behavioral tests.

All eight new modules are explicitly included in the coverage configuration. Their measured focused coverage is **96.72% lines, 82.35% branches, 93.63% functions and 91.90% statements**. Existing per-file thresholds remain 75% lines/functions, 74% statements and 50% branches. No threshold was lowered to accommodate extraction. The full frontend suite is the release gate; its final run is recorded separately.

The upload parent decreased from 1,809 lines / maximum function complexity 67 before this extraction to **746 / 50**. The document controller is 445 / 39, submission controller 169 / 26, review panels 291 / 15, and the pure validation module 108 / 17. All new owners have explicit size/complexity ratchets, and the parent ceiling was reduced. These are still substantial workflows; the result is bounded responsibility and direct behavior tests, not a claim that every component is small or that the entire upload flow is one formally verified state machine.

## Evidence limits

The focused controller run used Node24.15.0/npm11.12.1 before the maintained toolchain handoff. Final frontend gates use the independently hash-verified portable Node24.21.0/npm11.20.0 and are versioned in the final receipt. Local JSDOM tests do not establish physical camera behavior, mobile performance, screen-reader usability or a successful production deployment. The three-engine production-image qualification remains a separate acceptance step.
