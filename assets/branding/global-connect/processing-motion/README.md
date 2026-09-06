# Processing motion

Four original vector motion scenes for the passport link and document workflows. Open `preview.html` in a browser to view all four. The preview is a self-contained illustration gallery, not a live processing session.

| Scene | Application use |
| --- | --- |
| Passport | Saved passport pages awaiting AI extraction, including resumed work and stored-image retries |
| Analysis | Active PDF checks in the document distribution workspace |
| Rename | Server processing during the combined Analyze And Rename operation |
| Distribution | Accepted-document matching/saving, preparing the delivery preview, and queueing document messages |

The live components are authored as SVG and CSS in `frontend/components/shared/processing-motion.tsx` and `processing-motion.module.css`. They remain sharp at different sizes without a video download or a new animation dependency. No real passport, passenger or document data is embedded in the illustrations.

Animation is decorative. Existing status labels, progress counters, results, failure guidance and delivery confirmation remain authoritative. The API combines analysis and renaming, so no fictional intermediate phase was introduced. Queueing messages does not imply that they have been delivered.

The application mounts the scene only during the corresponding pending operation. Offscreen and hidden-tab scenes pause; reduced-motion preferences display still artwork. Animations never add a minimum waiting period or delay results. The gallery is a standalone CSS preview and does not include the application's visibility observer.

## Validation — 6 September 2026

- 16 new tests passed across passport extraction, document processing and motion lifecycle behavior.
- 15 existing upload interaction tests and 38 existing targeted upload/document contracts passed.
- Focused ESLint, production build, TypeScript and diff whitespace checks passed.
- Artwork gallery inspected in the browser at desktop and phone width, with no horizontal overflow at phone width.
- Reduced-motion fallback verified in the CSS source; not exercised through an OS preference change.
- Real AI extraction and provider delivery were not invoked for this visual change. Workflow tests use synthetic records and mocked API boundaries.

The preview is generated directly from the current component and CSS using the local QA helper `outputs/processing-motion-preview/build.cjs`.
