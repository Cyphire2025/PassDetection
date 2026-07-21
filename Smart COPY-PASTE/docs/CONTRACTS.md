# Behavioral Contracts

These contracts describe stable V2 behavior. Internal method signatures may
evolve, but weakening the safety properties requires an explicit product and
security review.

## Canonical field contract

`CanonicalFieldCatalog` owns stable identifiers and their exact aliases.
Visible labels are never storage identifiers.

Representative identifiers include:

```text
personal.title
personal.surname
personal.given_name
personal.middle_name
personal.full_name
personal.date_of_birth
personal.gender
personal.nationality
passport.number
passport.issue_date
passport.expiry_date
passport.place_of_issue
passport.country_of_issue
contact.email
contact.mobile
address.line1
address.city
address.state
address.postal_code
address.country
```

Normalization trims whitespace, applies invariant case normalization, replaces
underscores and hyphens with spaces, removes approved punctuation, and
collapses repeated spaces. Resolution is exact after normalization. Unknown
headers remain unknown.

Two source columns may not resolve to the same canonical identifier in one
template without explicit correction.

## Clipboard parser contract

`TabularDataParser` accepts Windows clipboard text in Excel-style
tab-separated form.

- Cells remain strings; leading zeroes are preserved.
- CRLF and LF row endings are accepted.
- Quoted tabs and line breaks are parsed according to tabular quoting rules.
- Interior empty cells are preserved.
- Completely empty trailing rows are ignored.
- Every passenger row must have exactly the template's column count.
- A copied header row is not silently treated as a passenger.
- An invalid parse returns actionable errors and leaves the existing session
  unchanged.

The parser supports two explicit modes:

1. header capture, producing a reviewed `HeaderTemplate`; and
2. passenger capture, applying exactly one selected template.

## Header profile contract

`HeaderTemplate` contains:

- schema version;
- ordered original headers;
- ordered canonical mappings or explicit unknown status;
- normalized header fingerprint; and
- non-sensitive creation/update metadata.

`WorkbookIdentityService` derives opaque workbook and worksheet keys through a
user-keyed HMAC of normalized source identity. Raw workbook paths and worksheet
data are not persisted or logged.

`HeaderFingerprint` is a separate, deterministic SHA-256 digest of the ordered,
normalized header labels. It detects header order/content changes; it is not a
workbook identifier and is not keyed.

Profile resolution follows this order:

1. exact current workbook/worksheet fingerprint;
2. explicit user-selected profile when source identity is unavailable; or
3. fail with no active profile.

Column count, workbook display name alone, and prior usage are not profile
selection evidence.

## Passenger session contract

`PassengerSession` contains an ordered collection, active index, and lock
state. It lives in memory only.

- The first copied passenger is active.
- Navigation requires an explicit action.
- Navigation does not wrap at collection boundaries.
- Locked sessions reject navigation.
- Smart Paste reads one immutable active-passenger snapshot.
- Replacing or clearing a session is visible.
- Restarting the application creates an empty session.

## Focused field contract

`FocusedFieldContext` is an immutable, bounded snapshot of UI Automation
metadata from supported Chrome, Microsoft Edge, or Brave standard editable
controls:

```text
accessible name
automation identifier
help text
placeholder
section heading
input type and format hint
control type
enabled/read-only/password state
browser process ID/window identity where available
```

Strings are length-limited and treated as untrusted. They are normalized but
never executed or interpreted as markup.

Protected-control classification runs before saved mappings, ordinary matching,
or candidate ranking. Password/file/disabled/read-only/CAPTCHA-like controls
and authentication-secret metadata such as one-time password/PIN,
`one-time-code`, verification/authentication code, 2FA/two-factor, MFA, TOTP,
or authenticator are blocked even on text/tel inputs. The picker cannot
override the result. `Country code`, `Country calling code`, and `Include
country code` are explicitly benign passenger metadata and are not blocked by
the authentication classifier.

`FocusedFieldMatcher` returns:

- canonical field, when identified;
- deterministic score and evidence reason;
- outcome: auto-paste, choose manually, or blocked; and
- a sanitized explanation.

`RankCandidates` returns a bounded, deterministic list containing only related
fields available in the active passenger. A generic `Telephone number` ranks
exactly available `contact.mobile` and `contact.landline` values. It excludes
alternate mobile, emergency phone, calling code, and unrelated categories.
Specific phone labels rank only their own canonical semantic. Generic helper
text such as `Include country code` remains complete-number intent and never
changes the target to `contact.country_calling_code`; that semantic requires an
explicit calling/dialing-code target.

Exact strong evidence is required for first-use automatic paste. Conflicting
strong evidence, weak tokens, unknown fields, generic telephone, and materially
ambiguous terms such as `number` cannot auto-paste. Generic telephone requires
confirmation even when only one related value exists.

Section headings are safety-significant. `Emergency`,
`Previous`/`Former`/`Old`, and
`Alternate`/`Alternative`/`Secondary` qualifiers return
`SECTION_CONTEXT_CONFLICT` rather than auto-pasting the corresponding
base/current field. Candidate ranking removes that base field and offers the
specialized canonical field for confirmation when available. If the
specialized value is absent, the target remains manual; the base field is never
used as a substitute.

The following pairs have explicit regression protection:

- passport number versus application number;
- passport number versus visa number;
- passport number versus booking reference;
- passport number versus national ID;
- passport number versus employee ID.

## Picker and runtime-memory contract

When related candidates exist, the picker starts in recommendations-only mode.
**Show all copied fields** is the only UI action that broadens it to the full
masked profile. Search uses display name, original Excel header, and canonical
ID; it never searches raw passenger values.

When a focused target has a safe signature, the picker displays **Remember this
choice for this browser window and app session**, checked by default. The user
may uncheck it.

`SessionTargetMappingStore`:

- hashes normalized browser process name/ID, foreground window handle, control
  type, accessible name, AutomationId, help text, class name, placeholder, and
  input type;
- stores only a canonical field ID under that hash;
- is bounded to 256 process-memory entries;
- never stores passenger values or raw signature metadata;
- never writes mappings to settings or diagnostics;
- requires an exact unchanged signature for reuse;
- survives clearing one passenger only while at least one other passenger
  remains; and
- is cleared when the only/final passenger is removed, by Clear All, and by
  process cleanup/Exit, and is necessarily empty after restart.

A changed browser process/window or signature metadata cannot reuse a mapping.
A remembered canonical ID missing from the active passenger produces a missing
value, not a substitute. Protected-control, conflict, focus, and passenger
generation checks still run before insertion.

V2 has no domain/URL/page/account identity and therefore no persistent
per-website mapping contract.

## Value-adaptation contract

`TargetValueAdapter` receives the selected canonical field, immutable copied
value, and focused-field metadata. It may alter only the outgoing paste payload
when an explicit target requirement is safe:

- invariant uppercase or lowercase;
- a supported, unambiguous, calendar-valid date mask;
- digits-only phone text without numeric conversion; or
- compact international/E.164 phone text when the source prefix is explicit.

It never changes the passenger session. Visual label capitalization alone is
not a case instruction. Conflicting hints, ambiguous source dates, destructive
country-code removal/last-digit requests, missing international prefixes, and
phone extensions that would be discarded return unsafe/manual outcomes.
Leading zeroes remain intact. A recognized case, date, or phone instruction
that is negated also returns an unsafe/manual outcome with the original value;
negation never authorizes an inverse transformation.

Native/custom dropdowns, radio buttons, checkboxes, contenteditable controls,
native date inputs, and date-picker widgets are outside this text-paste
contract.

## Value insertion contract

Normal automatic paste and picker-confirmed paste write the bounded outgoing
value to the exact focused browser control through UI Automation
`ValuePattern.SetValue`. The browser insertion path does not synthesize typing,
place a passenger value on the clipboard, or offer a `Ctrl+V` clipboard
fallback.

The target token retains its UI Automation handle for at most 10 minutes. That
lifetime is only an implementation bound, not authorization to write. Before
every insertion the app freshly requires:

1. the token and expected field snapshot still describe the same target;
2. the supported browser process, process ID, foreground window, runtime
   identity, and complete semantic metadata still match;
3. the exact automation element is still focused;
4. a fresh inspection still reports an enabled, keyboard-focusable, editable,
   non-password, non-protected control;
5. the current control still exposes a writable `ValuePattern`; and
6. pause, active-passenger generation, and selected-value checks still pass.

Any failed check invalidates or rejects the target and inserts nothing. The
employee must focus the intended standard text field and retry or complete an
unsupported field manually.

Focus restoration and value insertion use a three-second side-effect start
deadline. If a queued operation has not reached commit, or validation has not
completed, by that deadline, its operation gate is abandoned. The UI
Automation worker checks the gate before `SetFocus` or `SetValue`, so abandoned
work cannot act later.

Once exact UI Automation `SetFocus` or `ValuePattern.SetValue` has actually
begun, timeout and cancellation no longer cause the caller to return while the
provider may still complete the side effect. The workflow waits for the
provider call to finish, and passenger/session invalidation is serialized
behind that in-flight commit. This intentionally trades availability for an
unambiguous result: a hung accessibility provider can stall the workflow and
may require ending and restarting the app.

## Excel clipboard-acquisition fallback contract

Exact Excel selection access is the normal source path. Clipboard acquisition
is an explicit allowlist, not a response to every Excel error. A warning may be
offered only when the foreground source is not Excel or exact Excel inspection
returns `EXCEL_SELECTION_UNAVAILABLE`, `EXCEL_TIMEOUT`, or
`EXCEL_FOREGROUND_INSTANCE_MISMATCH`.

`EXCEL_NO_SELECTION`, `EXCEL_MULTI_AREA_SELECTION`,
`EXCEL_SELECTION_SIZE_INVALID`, `EXCEL_MERGED_SELECTION`,
`EXCEL_DISPLAY_VALUE_OBSCURED` (`####`), and every unknown Excel failure reject
the operation with corrective guidance. They never display the clipboard
fallback prompt.

After affirmative employee confirmation, the fallback uses the explicitly
selected header profile, snapshots restorable clipboard text formats, sends
`Ctrl+C` to the still-foreground source window, and reads only bounded tabular
text. It records the sequence for the app-requested selection and rechecks the
clipboard sequence immediately after reading. If the sequence changed during
the read, acquisition aborts before parsing or session mutation, the read text
is discarded, and no restore may overwrite the newer clipboard owner.

For a stable read, cleanup:

1. restores the snapshot only if the clipboard sequence still belongs to this
   operation;
2. preserves a newer third-party clipboard update; or
3. clears the app-owned selection when no restorable snapshot exists.

The warning states that Windows or third-party clipboard history may retain
the source application's copy. This acquisition fallback is never available
as a browser-field insertion method.

## Responsive window contract

All primary V2 forms use per-monitor DPI scaling, responsive grids, keyboard
navigation, and working-area clamping. Logical default/minimum sizes are:

| Window | Default | Minimum |
| --- | --- | --- |
| Main | 1040 x 720 | 780 x 560 |
| Picker | 820 x 600 | 700 x 500 |
| Header mapping | 920 x 680 | 700 x 500 |
| Shortcut settings | 760 x 620 | 700 x 520 |
| Diagnostics | 820 x 600 | 700 x 500 |

If the scaled minimum exceeds the monitor work area, the form clamps to that
area and uses scrolling rather than placing primary actions off-screen.

## Hotkey contract

| Gesture | Action |
| --- | --- |
| `Ctrl+Alt+H` | Capture/Save Headers |
| `Ctrl+Alt+C` | Smart Copy Passenger Row(s) |
| `Ctrl+Alt+V` | Smart Paste |
| `Ctrl+Alt+P` | Open Field Picker |
| `Ctrl+Alt+Right` | Next Passenger |
| `Ctrl+Alt+Left` | Previous Passenger |
| `Ctrl+Alt+X` | Clear Active Passenger |
| `Ctrl+Alt+Space` | Pause/Resume |

`AppSettings`, `HotkeyGesture`, and `SettingsValidator` reject duplicate,
modifier-only, unsupported, reserved, unsafe, or unregistrable gestures. Every
configured gesture must contain at least two protective modifiers from
`Ctrl`, `Alt`, and `Shift`; the Windows modifier does not count. Windows-only,
unmodified, and single-protective-modifier gestures fail with
`HOTKEY_CHORD_UNSAFE`. A failed global registration never degrades into an
application-wide keyboard hook.

## Diagnostics contract

`SensitiveDataMasker` masks values shown in previews. `DiagnosticRedactor`
removes passenger values from diagnostic messages.

`SanitizedDiagnosticReport` may contain:

- application and operating-system versions;
- shortcut registration states;
- parser/matcher outcome codes;
- canonical field identifiers;
- evidence category;
- non-sensitive error type; and
- configuration/schema versions.

It must not contain passenger values, clipboard content, raw workbook paths,
raw target labels/signature material, raw window text containing passenger
values, or cryptographic key material.

## Versioning contract

Persisted configuration and release artifacts use explicit semantic versions.
Unsupported future versions fail closed. Migration code must validate the full
object before replacing a known-good configuration.

Each release manifest records the Git `commit` when available and an explicit
`sourceState`. A project with no tracked files records `commit: "untracked"`
and `sourceState: "untracked-source"`; a tracked checkout with changes records
`sourceState: "dirty"`. The manifest also records `sourceSha256` and
`sourceFileCount` for the source tree used to build the artifact. These fields
preserve provenance but do not misrepresent untracked or dirty source as a
clean commit build.

V2 has no desktop-extension communication contract because the browser
extension is intentionally deferred.
