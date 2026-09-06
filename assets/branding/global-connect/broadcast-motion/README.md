# WhatsApp broadcast motion

Three original SVG/CSS illustrations for Welcome, Passport Link and Reminder broadcasts. A central phone dispatches chat bubbles along four routes to generic recipient cards. The artwork uses Global Connect navy, blue and green, with no blur, video download or new animation dependency.

Open [preview.html](preview.html) for the animated artwork gallery, state controls and compact display examples. All names and counts in the gallery are illustrative. It does not connect to WhatsApp or send messages.

## Application placement

- **Composer:** Appears at the validated Send boundary while the full submission request is pending. The phone animates while submitting; outbound bubbles begin only in the sending state.
- **Broadcast page:** Compact artwork sits alongside the existing live activity counts and progress.
- **Other dashboard pages:** The same message variant appears inside the existing draggable floating activity box. Its original start time is preserved across navigation so it rejoins the same animation cadence.
- **Retries and resends:** The shared composer and sender registration preserve immediate feedback and the corresponding message variant.

The scene remains mounted across progress updates. It pauses for reconnection, terminal failure/uncertain outcomes and completion. Existing counts, errors, failure details, dismissal and batch polling remain authoritative. Sent does not imply delivered or read. Existing document and QR activity rows retain their presentation.

Offscreen or hidden-tab artwork pauses. Reduced-motion preferences show static artwork. No minimum duration or artificial result delay is introduced, and no personal recipient data appears inside the SVG.

## Editable source

- `frontend/features/whatsapp/components/whatsapp-broadcast-motion.tsx`
- `frontend/features/whatsapp/components/whatsapp-broadcast-motion.module.css`

From `frontend`, regenerate the standalone gallery with:

```powershell
node scripts/generate-broadcast-motion-preview.mjs
```

The generator uses the project's existing React and Vite tooling. The gallery uses CSS only; application lifecycle observers and route transitions are exercised separately through integration tests.

## Validation - 6 September 2026

- Production build and TypeScript passed.
- 29 focused React tests passed across composer behavior, real activity provider, routing, metadata and artwork lifecycle.
- Existing WhatsApp sender, tracker and polling contracts passed.
- Focused ESLint and diff whitespace checks passed.
- Artwork inspected at normal and phone viewport widths, including compact floating size and attention state, with no horizontal overflow in the gallery.
- The actual tracker was inspected in an isolated browser harness with compiled application CSS: inline-to-floating navigation, progress changes, failed/unknown outcomes, expanded failure details, and dragging at a 375px viewport passed. Default floating margins now match the drag boundary on narrow screens.
- Live provider sends and production deployment were not exercised. Workflow tests use synthetic activities and mocked API responses.
