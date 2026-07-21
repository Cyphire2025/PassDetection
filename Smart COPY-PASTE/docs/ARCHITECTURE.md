# Architecture

## Goal

The V2 application is a Windows-only, local-first assistant that captures an
Excel header profile, parses passenger rows, and inserts one explicitly
selected passenger value into one focused field. It is not a full-form
automation engine.

## Projects

```text
SmartCopyPaste.Core
  Deterministic schemas, parsing, matching, session state, validation,
  redaction, and settings contracts.

SmartCopyPaste.App
  WinForms application lifecycle, tray UI, Windows hotkeys, Excel source
  inspection, exact UI Automation ValuePattern insertion, clipboard-isolated
  Excel fallback acquisition, and persistence.

SmartCopyPaste.Core.Tests
  Table-driven tests for deterministic core behavior.
```

The core project does not depend on WinForms, COM, the clipboard, or browser
state. Windows integrations are adapters around core contracts.

## Runtime components

### Tray host

A WinForms `ApplicationContext` owns the notification icon and menu. The main
thread is a single-threaded apartment so clipboard and WinForms operations run
on the correct Windows apartment. Closing a visible window hides it; the
explicit **Exit** command performs cleanup and ends the message loop.

### Hotkey host

The application registers global shortcuts through `RegisterHotKey` with
no-repeat behavior. Registration failures are visible and actionable. Hotkeys
are unregistered during shutdown. Settings validation requires every shortcut
to include at least two of `Ctrl`, `Alt`, and `Shift`; the Windows key does not
count, so Windows-only and single-protective-modifier chords fail closed as
`HOTKEY_CHORD_UNSAFE`.

### Excel source adapter

Header capture obtains a stable source identity from the active saved workbook
and worksheet when Excel makes it available. The application derives a
user-scoped, non-reversible header fingerprint; it does not persist the raw
workbook path.

If the source identity is unavailable, header-profile selection is explicit.
Column count alone is never sufficient to select a profile.

### Core parser and session

`TabularDataParser` parses Excel-style tab-separated text without numeric
coercion. A `HeaderTemplate` maps each column to a stable canonical field.
`PassengerSession` owns the ordered in-memory passenger collection, active
index, and lock state.

Passenger switching is explicit. A Smart Paste operation receives one atomic
snapshot of the active passenger so a concurrent switch cannot mix values.

### Focus inspection and matching

Windows UI Automation runs on a dedicated multithreaded-apartment worker for
Chrome, Microsoft Edge, and Brave. It captures bounded accessible name,
automation identifier, help text, placeholder, section heading, input type,
format hint, class/control type, enabled state, read-only state, password
status, browser process/window identity, and target bounds when available.

`FocusedFieldMatcher` applies case-invariant normalized aliases, approved
presentation-marker removal, conflict rules, and deterministic evidence
priorities. It also ranks related available fields for the picker. A generic
`Telephone number` ranks only `contact.mobile` and `contact.landline`; it never
silently chooses a sole related value on first use. Specific alternate-mobile,
emergency-phone, and calling-code metadata remain isolated. Generic help to
`Include country code` remains complete-number intent, not a standalone
calling-code target.

Section-heading evidence is a safety constraint. `Emergency`,
`Previous`/`Former`/`Old`, and
`Alternate`/`Alternative`/`Secondary` context blocks automatic use of the
corresponding base/current field. Ranking removes that base field and offers a
specialized candidate for confirmation when present; no specialized value
means manual completion rather than fallback.

Before either normal or saved-mapping resolution, protected-control
classification blocks authentication-secret metadata including one-time
password/PIN, one-time-code, verification/authentication code, 2FA/two-factor,
MFA, TOTP, and authenticator signals on text/tel controls. Candidate ranking
returns no rows, so the picker cannot override the block. Ordinary `country
code` passenger metadata remains unblocked.

A blocked, conflicting, weak, unknown, or generic telephone result cannot
auto-paste on first use. It opens the picker with related recommendations when
available.

Without the deferred browser extension, the app cannot reliably inspect HTML
DOM attributes, domain, path, iframe context, or nearby document text.

### Picker and runtime target memory

The picker uses a DPI-aware, resizable DataGrid with fill-width Passenger
field, Excel header, and masked Value preview columns. Recommendations are the
default view; **Show all copied fields** is an explicit broadening action.
Search matches display name, source header, and canonical ID, never raw values.

When a safe signature exists, **Remember this choice for this browser window
and app session** is checked by default. `SessionTargetMappingStore` hashes the
browser process name/ID, foreground window handle, control type, accessible
name, AutomationId, help text, class name, placeholder, and input type. It
stores only the confirmed canonical field ID in a bounded process-memory map.
Changed metadata, process, or window produces another signature. Clearing one
passenger preserves the map while another passenger remains; clearing the
only/final passenger discards it. Clear All, other cleanup boundaries, Exit,
and restart also discard it. It is never a domain-persistent website mapping.

### Target value adaptation

`TargetValueAdapter` runs only after canonical field selection. Explicit
accessible format hints may apply invariant case conversion, validated
unambiguous date rendering, digits-only phone formatting, or bounded
international compaction. It never mutates the passenger session.

Conflicting or destructive instructions, ambiguous dates, missing
international prefixes, and phone extensions that would be lost fail safe.
Uppercase label text alone is not an uppercase instruction. A recognized
case/date/phone instruction that is negated also fails safe with the source
unchanged; the adapter never infers the opposite transformation.

### Value insertion

The Windows app remains the source of truth. A high-confidence match or normal
picker selection uses the safely adapted payload with the exact focused
control's writable UI Automation `ValuePattern`. Browser-field insertion does
not synthesize typing and does not modify the clipboard.

The inspector retains a captured automation element behind an opaque target
token for at most 10 minutes. Every attempted write still performs fresh
same-target, browser process/window, focus, semantic metadata, editable and
protected-state, and writable-`ValuePattern` validation. A stale, changed,
unfocused, protected, or unsupported target is invalidated or rejected and
receives no value.

There is no picker or browser clipboard fallback. A portal control that cannot
accept an exact `ValuePattern` update remains manual.

`UiAutomationOperationGate` gives focus/write work three seconds to reach its
side-effect boundary. A timeout or cancellation while the operation is queued
or still validating abandons the gate; the worker cannot later call
`SetFocus`/`SetValue`. After either exact provider call begins, the caller
waits for it to return rather than timing out into an ambiguous state where a
value could appear later. `PasteCommitGuard` also serializes cleanup/session
invalidation with that in-flight side effect. This atomic-commit policy can
turn a hung accessibility provider into an availability failure that requires
restarting the app.

### Excel clipboard-acquisition fallback

Excel COM inspection is the normal source path. The clipboard prompt is
allowlisted only when the foreground source is not Excel or inspection reports
exact-access unavailable, timeout, or a foreground-Excel/COM-instance mismatch.
No selection, multiple areas, an oversized range, merged cells, displayed
`####`, and unknown Excel failures reject with corrective guidance and never
offer the prompt.

After confirmation, the service snapshots supported text formats and reads
bounded tabular text from the still-focused source. It records the selection's
clipboard sequence and rechecks it immediately after the read. A mismatch
aborts acquisition before parsing or session mutation and preserves the newer
owner's clipboard. A stable read restores the snapshot only while still owned;
if no snapshot exists, the app-owned selection is cleared. The warning notes
that clipboard-history software may retain the source application's copy. This
path never inserts browser values.

### Local persistence

Passenger values and runtime target mappings are memory-only. Persisted data
is limited to settings, header definitions, HMAC-derived source keys, and
non-sensitive operational metadata. Windows current-user data protection
protects the random HMAC secret, not the complete settings file. Header labels
in `settings.json` are readable by the current Windows user and are not
encrypted. Persisted objects carry an explicit schema version and fail closed
when validation or secret decryption fails.

Per-user configuration is stored under:

```text
%LOCALAPPDATA%\SmartCopyPaste\
  settings.json
  diagnostics\...
```

Diagnostics in this directory are sanitized. Passenger values are never
written there.

## Primary data flows

### Header-once flow

```text
Excel header selection
  -> Ctrl+Alt+H
  -> exact Excel selection inspection
     OR explicit clipboard source acquisition for an allowlisted source state
  -> normalize and validate headers
  -> derive HMAC workbook/worksheet keys
  -> save reviewed HeaderTemplate
```

### Passenger-copy flow

```text
Excel passenger row selection
  -> Ctrl+Alt+C
  -> resolve exact active HeaderTemplate
  -> parse and validate row widths
  -> create ordered PassengerSession in memory
  -> show active passenger status
```

### Smart-paste flow

```text
Focused browser control
  -> Ctrl+Alt+V
  -> UI Automation snapshot
  -> deterministic FocusedFieldMatcher
  -> high-confidence safe match
     OR exact runtime-memory match
     OR ranked picker confirmation
  -> read one value from atomic active-passenger snapshot
  -> explicit safe TargetValueAdapter
  -> fresh same-target, focus, semantic, and protected-state revalidation
  -> exact writable UI Automation ValuePattern update
```

## Failure behavior

- Invalid clipboard shapes do not alter the active passenger session.
- Missing or mismatched header profiles require explicit user action.
- Unknown or conflicting field evidence opens the picker.
- Generic telephone requires first-use confirmation even with one related
  value.
- `Include country code` on a full-number target never selects the standalone
  calling-code field.
- Qualified Emergency, old/previous, or alternate/secondary sections never
  fall back to a base/current field.
- Changed target signature cannot reuse a runtime-only remembered choice.
- Clearing the final passenger clears runtime target mappings; clearing one of
  several preserves them for the remaining session.
- Unsafe or ambiguous value adaptation does not paste.
- Protected or unsafe controls are blocked.
- Browser insertion failure leaves the target unchanged and never falls back to
  the clipboard.
- Queued or pre-commit focus/write work is abandoned after three seconds and
  cannot execute later; an already-started provider side effect is awaited to
  completion and may hang.
- Excel fallback acquisition restores or clears its clipboard selection only
  when sequence ownership is still valid; a sequence change during the read
  aborts import, and newer third-party data wins.
- Invalid Excel selection shapes/content and unknown Excel failures reject
  without offering clipboard acquisition.
- Normal user-facing errors are concise; detailed diagnostics are sanitized.

## Deployment shape

The app publishes as a self-contained, untrimmed, single-file Windows x64 EXE.
It requires no installed .NET runtime and no administrator rights for normal
use. Windows 11 x64 is the primary target; Windows 10 is limited to
Microsoft/.NET-supported Enterprise/LTSC editions. Per-user installation places
the executable under Local AppData and adds a Start Menu shortcut.

`release-manifest.json` records the available Git commit together with
`sourceState`, including explicit `dirty` and `untracked-source` states. It
also records `sourceSha256` and `sourceFileCount` for the source tree used to
produce the artifact, so an untracked or modified build is not presented as a
clean-commit build.

V2 uses per-monitor DPI scaling, responsive grids, larger default/minimum
windows, and working-area clamping. V2 does not include an installer framework,
updater, extension, native
messaging host, cloud service, or remote telemetry.
