# Processing motion

Four original vector motion scenes for the passport link and document workflows. Open `preview.html` in a browser to view all four. The preview is a self-contained illustration gallery, not a live processing session.

| Scene | Application use |
| --- | --- |
| Passport | Passport preparation, secure upload and AI extraction, including resumed work and stored-image retries |
| Analysis | The full PDF check operation in the document distribution workspace, including each batch upload |
| Rename | The full combined Analyze And Rename operation, including each batch upload |
| Distribution | The full accepted-document upload/matching operation, preparing the delivery preview, and queueing document messages |

The live components are authored as SVG and CSS in `frontend/components/shared/processing-motion.tsx` and `processing-motion.module.css`. They remain sharp at different sizes without a video download or a new animation dependency. No real passport, passenger or document data is embedded in the illustrations.

Animation is decorative. Existing status labels, progress counters, results, failure guidance and delivery confirmation remain authoritative. The API combines analysis and renaming, so no fictional intermediate phase was introduced. Queueing messages does not imply that they have been delivered.

The application mounts the scene as soon as the corresponding operation begins and keeps the same scene mounted across upload, processing and subsequent batch transitions until the operation settles. Passport preparation and saved-image retry requests also show artwork immediately. Status text still distinguishes preparation, upload and extraction. Offscreen and hidden-tab scenes pause; reduced-motion preferences display still artwork. Animations never add a minimum waiting period or delay results. The gallery is a standalone CSS preview and does not include the application's visibility observer.

## Validation — 6 September 2026

- 18 focused motion tests passed across passport extraction, document processing and motion lifecycle behavior, including scene identity across batch transitions and immediate retry feedback.
- 21 existing upload interaction tests and 58 existing targeted upload/document contracts passed.
- Focused ESLint, production build, TypeScript and diff whitespace checks passed.
- Artwork gallery inspected in the browser at desktop and phone width, with no horizontal overflow at phone width.
- Reduced-motion fallback verified in the CSS source; not exercised through an OS preference change.
- Real AI extraction and provider delivery were not invoked for this visual change. Workflow tests use synthetic records and mocked API boundaries.

The preview is generated directly from the current component and CSS using the local QA helper `outputs/processing-motion-preview/build.cjs`.
