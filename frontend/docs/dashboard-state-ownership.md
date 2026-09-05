# Dashboard state ownership

The dashboard keeps server records in React Query, temporary workflow state in the component or controller that owns the interaction, and non-sensitive presentation preferences in one versioned Zustand store. A visual refactor must not create a second copy of operational data or relax a route capability.

## Server records and repair

- Existing feature APIs, query keys, authorization and mutation contracts remain the source of operational truth. A settings edit carries the loaded `expected_updated_at` revision; a conflict preserves the draft and requires an explicit reload.
- `lib/hooks/use-live-history-feed.ts` gives notifications and the operations inbox an independently keyed live first page. Only that query polls or repairs on focus/reconnection. History loads when requested, retains at most five pages, and offers Return to latest. Identical records in the live head and history are rendered once. A filter or identity change cannot inherit a history cursor from a different scope.
- Marking notifications read explicitly invalidates the bounded historical view as well as the head so displayed read state catches up. That user action is distinct from periodic repair.
- Network and authorization failures are not successful empty data. Global search has separate pending, error and empty-success rendering, cancels superseded requests, and supports explicit retry.

## Selection and workflow state

- Searching, sorting, filtering, changing table pages and switching list presentation must preserve selected record IDs. Select visible/Select matching adds the visible subset to the existing selection; deselecting a checkbox removes only its record. Clear selection is the explicit whole-selection reset.
- Passport selection retains the record revision observed when it was selected. Bulk destructive or approval requests continue to use the backend revision checks, permitted-action gates and confirmation dialogs. A filtered-out record is still selected; its action is subject to current server authorization and revision validation.
- Successful deletion or completed workflow actions may remove their affected selections. File-picker replacement and changing an assignment's authoritative group are separate scope changes and may reset incompatible drafts.
- Do not persist passenger selections, passport records, document data, email content or search terms into the presentation-preference store.

## Component boundaries

- `passport-group-detail.tsx` composes the group controller, header, overview, import panel, selection toolbar, roster and dialogs. The controller's typed public surface is limited to fields used by those panels. Optional heavy editors retain dynamic imports.
- `message-activity-page.tsx` owns loading the message. Its operational brief, deadline decisions, proposal decisions, draft editor and feedback view are independent components. The feedback controller owns the revisioned correction form and mutations.
- `features/settings/dashboard-preferences.ts` persists only density, width, text size, reduced motion and sidebar collapse. `DashboardShell` applies those settings through data attributes. Accessibility preferences from the operating system still take precedence.

## Regression evidence

Interaction tests exercise six history pages followed by a new live item, one-request repair, identity-scoped history reset, search failure/retry/cancellation, selection retention through filtering and sorting, and preference persistence/reset. Source contracts follow the extracted module boundaries. Rendered local Docker review and provider/production checks remain separate evidence.
