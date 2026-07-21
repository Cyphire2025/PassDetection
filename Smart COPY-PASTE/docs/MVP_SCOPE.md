# V2 Scope

## Included

- Windows 11 x64 tray application. Windows 10 x64 is supported only on
  Enterprise/LTSC editions that remain supported by both Microsoft and .NET 10.
- Single-instance lifecycle with explicit tray Exit.
- Global, no-repeat hotkeys for header capture, passenger capture, Smart Paste,
  picker, passenger navigation, clear-active, and pause/resume. Every configured
  chord requires at least two of Ctrl/Alt/Shift; Windows does not count toward
  that safety minimum.
- Header-once workflow for a saved Excel workbook and worksheet.
- Versioned, user-scoped header profiles with HMAC-derived workbook/worksheet
  keys and no persisted raw workbook paths. Header labels themselves are not
  encrypted.
- Deterministic tab-separated parsing for one or multiple passenger rows.
- Stable canonical field identifiers, built-in exact aliases, and reviewed
  manual/custom header mappings. V2 has no alias-administration screen.
- Ordered, memory-only multi-passenger session with explicit active passenger.
- Passenger locking, previous/next controls, clear-one, and clear-all.
- Best-effort Windows UI Automation inspection of Chrome, Microsoft Edge, and
  Brave standard editable text fields.
- Case-insensitive deterministic matching for approved decorated labels, with
  block, exact, ranked-recommendation, and manual-fallback outcomes.
- Generic Telephone recommendations limited to available primary mobile and
  landline values, with mandatory first-use confirmation. `Include country
  code` helper text remains complete-number intent rather than a standalone
  calling-code request.
- Section-qualified matching that blocks base/current fields under Emergency,
  Previous/Former/Old, and Alternate/Alternative/Secondary context, then offers
  only a specialized candidate or manual completion.
- Keyboard-accessible, larger DPI-aware picker with masked values, responsive
  columns, explicit **Show all copied fields**, and checked opt-in runtime
  memory.
- Bounded, exact-signature picker memory for the current browser window and app
  process only; no passenger value or raw signature metadata is persisted.
  Clearing one passenger preserves mappings while another remains, but clearing
  the final passenger clears them.
- Explicit safe output adaptation for case, unambiguous supported date masks,
  digits-only phones, and bounded international-phone formats. Negated format
  instructions fail closed and never imply the opposite transformation.
- Exact browser-field insertion through the focused control's UI Automation
  `ValuePattern`, after fresh target identity, semantic, focus, editable, and
  protected-state revalidation.
- Captured target handles retained for no more than 10 minutes and revalidated
  on every use; handle lifetime never grants permission to write.
- Three-second abandonment for queued or pre-commit focus/write operations,
  with a no-timeout wait after exact UI Automation `SetFocus` or `SetValue`
  begins so the app never reports failure while a late browser side effect is
  still possible.
- Explicit clipboard-based source acquisition, with guarded restore or clear,
  only when the source is not Excel or exact Excel inspection is unavailable,
  times out, or resolves to a different foreground Excel instance, and the
  employee confirms the fallback. The sequence is rechecked after reading and
  a mismatch aborts acquisition. Invalid/absent/multi-area/oversized/merged/
  `####`/unknown Excel selections reject without a fallback prompt.
  Browser-field insertion has no clipboard fallback.
- Sanitized diagnostics and a headless `--self-test`.
- Dependency-free offline browser fixture.
- Self-contained portable Windows x64 EXE and per-user install scripts.

## Safety rules

- Unknown or ambiguous fields do not receive automatic data.
- The app never advances passengers automatically.
- The app never submits, confirms, pays, continues, or clicks form buttons.
- Password, file-upload, native date, disabled, read-only, and CAPTCHA-like
  controls are blocked.
- Authentication-secret text/tel controls identified by one-time password/PIN,
  one-time-code, verification/authentication code, 2FA/two-factor, MFA, TOTP,
  or authenticator metadata are blocked before matching; the picker cannot
  override. Benign country-code passenger metadata remains unblocked.
- Passenger values are not written to application logs or persistent settings.
- Runtime behavior does not require or initiate network access.

## Deferred after manual V2 validation

- Chromium browser extension.
- Native Messaging and domain/path-aware field signatures.
- Persistent website/domain/account-specific remembered mappings.
- Rich DOM context, cross-frame coordination, and Shadow DOM inspection.
- Firefox and non-Windows support.
- Native and custom dropdown automation.
- Radio-button, checkbox, contenteditable, native date-input, and date-picker
  automation.
- Separate day/month/year insertion and portal-specific formatting.
- Country, nationality, and gender transformations; destructive phone
  rewrites; ambiguous date reinterpretation; and portal-specific name
  splitting/combining.
- Header/profile administration, import/export, and enterprise policy.
- Encrypted optional passenger persistence.
- Installer framework, automatic updates, enterprise deployment, and signed
  releases.
- Full-day automated desktop soak testing.

## V2 acceptance boundary

V2 is successful when an employee can:

1. save a workbook's headers once;
2. copy one or multiple passenger rows without the headers;
3. focus standard accessible browser text fields in any order;
4. paste correct values through deterministic exact matching or a safely
   narrowed picker;
5. confirm a generic telephone choice once, optionally reuse it for the exact
   unchanged runtime signature while a passenger session remains, and lose
   that choice after clearing the final passenger, cleanup, or restart;
6. apply only explicit safe output formatting without changing copied data;
7. switch and lock passengers without mixing data;
8. clear the session and exit from the tray; and
9. run the packaged EXE on a clean Windows 11 x64 user account without
   installing .NET.

V2 is not accepted if it guesses a materially different field, recommends
unrelated values for generic telephone, treats full-number country-code help as
a calling-code target, falls back to a base field inside qualified context,
keeps runtime mappings without an active passenger, persists passenger/runtime
mapping state to disk, applies an unsafe or inverse-from-negation format, leaves
an app-owned source-acquisition selection in the clipboard, uses the clipboard
as a browser insertion fallback, accepts an unsafe global shortcut, permits an
authentication-code field through automatic or picker paths, falsely blocks
benign country-code metadata as authentication, writes through a stale or
changed target, imports a clipboard selection after its sequence changes,
offers clipboard fallback for a non-allowlisted Excel failure, submits a form,
or silently switches passenger or header profile.
