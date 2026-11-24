# Group artwork review and implementation

Status: implemented and locally verified. Release contract integration is assigned to the extraction/release agent.

## Completed behavior

- Banner images render without overlays, blur, or image filters. Header/status surfaces, icon backgrounds and header action boxes are transparent while a banner is available.
- Edit background persists a private image per group. A fixed image layer covers the workspace and top header outside the sidebar, with bounds updated on layout/viewport resize rather than on scroll.
- Background artwork makes group cards, metrics, toolbar and empty-state surfaces transparent. Menus, dialogs and form controls retain their interactive surfaces. Missing/failed images restore normal surfaces.
- Both image editors offer drag positioning, horizontal/vertical keyboard-operable sliders and zoom. Cropping occurs once on explicit Save. Blob URLs and decoded bitmaps are released.
- Existing image version checks freeze the opened edit version across background query refreshes. Tenant/role authorization, malware validation, metadata removal, private no-store reads, CSRF and durable cleanup compensation apply to backgrounds as to banners.
- Migration 0142 adds one nullable private background key after unchanged0141. Downgrade refuses to discard populated references.

## Verification

- Backend workspace branding and guarded-downgrade tests: 6 passed.
- Crop geometry unit tests: 4 passed.
- Playwright workspace branding: 6 passed, including fixed bounds, sidebar exclusion, drag/zoom, reload/removal, mobile overflow, stale edits and existing logo/group creation workflows. Final styling retest: 2 passed.
- Targeted ESLint, TypeScript noEmit, Ruff and branding metadata/routes mypy: passed.
- Desktop/mobile/banner/editor screenshots reviewed under .tmp/branding-ui/.
- React best-practices checklist applied: focused components, event-driven image processing, bounded canvas output, no scroll-time React rendering, cleanup of observers/listeners/resources, accessible labels and existing modal keyboard/focus boundaries.

## Limits

Screenshots use synthetic intercepted APIs; they do not establish real PostgreSQL/object-store or deployed VPS qualification. Original image bytes remain sanitized by the established image security pipeline. With transparent surfaces and no image overlay, text contrast necessarily depends on the selected artwork; muted artwork text is darkened and the editor permits choosing a clearer area. The background editor now uses the actual right-pane viewport aspect when opened, including the header and excluding the sidebar, so saving an adjusted image shows the selected area on that viewport. Other viewport proportions still cover responsively and can show a different crop.

## Inspected paths

- frontend/features/branding/api/branding-images.api.ts
- frontend/features/branding/components/group-banner.tsx
- frontend/features/branding/components/group-banner-action.tsx
- frontend/features/branding/components/group-image-dialog.tsx
- frontend/features/branding/components/group-workspace-background.tsx
- frontend/features/branding/components/image-position-editor.tsx
- frontend/features/branding/components/image-upload-field.tsx
- frontend/features/branding/image-crop.ts
- frontend/features/branding/image-crop.test.ts
- frontend/features/passports/components/passport-group-detail.tsx
- frontend/features/passports/components/passport-group-header-panel.tsx
- frontend/features/passports/components/passport-group-readiness.tsx
- frontend/features/passports/components/passport-group-overview-panel.tsx
- frontend/features/passports/components/passport-group-roster-panel.tsx
- frontend/features/passports/components/passport-group-selection-toolbar.tsx
- frontend/features/passports/components/use-passport-group-controller.tsx (branding/fallback wiring)
- frontend/features/passports/api/upload-links.api.ts (group metadata)
- frontend/types/passport.types.ts (group metadata)
- frontend/components/shared/workspace-ui.tsx
- frontend/components/shared/empty-state.tsx
- frontend/components/ui/card.tsx
- frontend/components/ui/modal-keyboard-boundary.ts
- frontend/components/layout/dashboard-shell.tsx
- frontend/components/layout/header.tsx
- frontend/app/globals.css
- frontend/e2e/workspace-branding.spec.ts
- backend/app/presentation/api/v1/routes/branding_images.py
- backend/app/presentation/api/v1/branding_metadata.py
- backend/app/infrastructure/storage/branding_urls.py
- backend/app/infrastructure/repositories/client_group_repository.py (branding mapping)
- backend/app/application/dtos/client_group_dtos.py (branding mapping)
- backend/app/domain/entities/entities.py (group branding fields)
- backend/app/infrastructure/database/models.py (group branding fields)
- backend/app/presentation/api/v1/schemas/client_group_schemas.py (group response)
- backend/app/presentation/api/v1/schemas/passport_schemas.py (group response)
- backend/alembic/versions/0141_workspace_branding.py
- backend/alembic/versions/0142_group_background.py
- backend/tests/integration/test_workspace_branding.py
- backend/tests/unit/infrastructure/test_group_background_migration.py
- backend/scripts/workspace_branding_release.py (release binding handoff)

Final independent visual pass identified opaque lazy-loading skeleton panels on mobile. Those loading surfaces now become transparent with artwork; metric helper labels wrap and remain fully visible. Desktop/mobile screenshot geometry, local TypeScript and113-module maintainability checks passed after the final changes.

Final crop-alignment pass: replaced the fixed1.6 background crop aspect with the actual right-pane viewport ratio on editor open. Preview width is bounded to52dvh while retaining that ratio, so mobile portrait crops fit in the editor. Added3React regressions for390x844/1192x1000 backgrounds and the wide banner; these plus4crop geometry tests pass. All6branding browser journeys passed again with explicit desktop/mobile crop-to-background aspect assertions and a mobile preview-height assertion. Inspected C:/Users/nipun/Desktop/PassDetection/.tmp/branding-ui/group-background-editor-mobile.png; the crop frame is bounded and controls remain inside the scrollable modal.
