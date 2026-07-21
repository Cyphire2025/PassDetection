# V2 Regression Matrix

This matrix converts the supplied portal and picker screenshots into V2 release
criteria. Use synthetic data only. A result passes only when evidence is
recorded against the exact build under test.

## Screenshot-derived requirements

The supplied screenshots establish three baseline problems:

- The 1917 x 641 portal uses compound labels, mixed capitalization,
  parentheses, punctuation, and required asterisks such as `Surname (Last
  name)`, `Middle and given name (First name)*`, `Sex*`, and `Re-enter Email*`.
- The 1341 x 977 picker for `Telephone number *` displays unrelated passenger
  fields. Its default recommendations must contain only available Mobile
  Number and Landline Number values.
- The 601 x 562 picker clips columns and actions. V2 deliberately uses a larger,
  responsive picker with a 820 x 600 logical-pixel default and a 700 x 500
  logical-pixel minimum.

All P0 rows must pass in current Chrome, Microsoft Edge, and Brave.

## Test profiles

Use canonical IDs rather than spreadsheet column position.

| Profile | Available fields | Purpose |
| --- | --- | --- |
| `S` screenshot-like | surname, given name, date of birth, gender, nationality, national ID, email, place of birth, passport number, and `contact.mobile` | Reproduces the reported picker with one related phone and many unrelated values. |
| `R` rich phone | all fields in `S`, plus `contact.alternate_mobile`, `contact.landline`, `contact.country_calling_code`, and `emergency.phone` | Proves generic telephone narrowing and isolation of specific phone semantics. |
| `N` no phone | all non-phone fields in `S`; no phone values | Tests the clearly identified searchable fallback. |
| `A` separate names | given name and middle name are separate copied columns | Ensures the compound portal label never silently concatenates values. |
| `Q` section-qualified | base and specialized pairs for current/old passport, current/previous nationality, primary/alternate email, primary/alternate mobile, and emergency phone/email | Proves section qualifiers cannot route a generic-looking field to its base canonical field. |

For a generic `Telephone number` target, the complete recommendation family is:

```text
contact.mobile
contact.landline
```

Only fields present and non-empty in the active passenger are recommended.
`contact.alternate_mobile`, `contact.country_calling_code`, and
`emergency.phone` are never generic telephone recommendations. They require
their own specific target metadata.

## Matching and normalization

| ID | Pri | Target metadata | Profile | Expected result | Evidence |
| --- | --- | --- | --- | --- | --- |
| MAT-01 | P0 | `Surname`, `SURNAME`, `surname`, and `sUrNaMe` through supported metadata sources | S | Same canonical ID and automatic outcome: `personal.surname`. | Unit theory plus fixture |
| MAT-02 | P0 | `SURNAME : *` | S | Ignore presentation punctuation and the required marker; auto-paste `personal.surname`. | `NORMALIZE-01` |
| MAT-03 | P0 | `pAsSpOrT nUmBeR : *` | S | Auto-paste `passport.number`. | `NORMALIZE-02` |
| MAT-04 | P0 | `E-mail Address (required):` | S | Auto-paste `contact.email`; `required` is presentation metadata. | `NORMALIZE-03` |
| MAT-05 | P0 | `Mobile No. (*)` | S | Auto-paste `contact.mobile`. | `NORMALIZE-04` |
| MAT-06 | P0 | `Surname (Last name)` | S | Both phrases resolve to `personal.surname`; no picker. | `LABEL-01` |
| MAT-07 | P0 | `Middle and given name (First name)*` | A | Resolve to copied `personal.given_name`; do not concatenate or substitute `personal.middle_name`. | `LABEL-02` |
| MAT-08 | P0 | `Date of birth *`, `Sex*`, `Nationality*`, and `Place of birth*` | S | Auto-paste their exact canonical fields. | `LABEL-03` to `LABEL-05`, `LABEL-09` |
| MAT-09 | P0 | `Identity Card` | S | Match `identity.national_id_number`, never passport. | `LABEL-06` |
| MAT-10 | P0 | `Email *` and `Re-enter Email*` | S | Both auto-paste `contact.email`; repeating either does not open a picker. | `LABEL-07`, `LABEL-08` |
| MAT-11 | P0 | `Religion*` when religion was not copied | S | No value is invented or pasted. | `LABEL-10` |
| MAT-12 | P0 | Accessible name `Passport Number` with AutomationId `applicationNumber` | S | Remain ambiguous; normalization does not erase the conflict. | Conflict unit test |

Normalization is Unicode normalization form KC, case-invariant, bounded, and
deterministic. It removes presentation punctuation and standalone required
markers without discarding semantic words such as `application`, `emergency`,
`alternate`, or `country code`.

## Explicit safe formatting

Formatting runs after a safe canonical selection and affects only that paste
payload. The copied passenger value in memory remains unchanged.

| ID | Pri | Explicit target requirement | Synthetic source | Expected result |
| --- | --- | --- | --- | --- |
| FMT-01 | P0 | `Surname (UPPERCASE ONLY)` | `Sharma` | Paste `SHARMA`. |
| FMT-02 | P0 | Passport help text `UPPERCASE ONLY` | `z1234567` | Paste `Z1234567`. |
| FMT-03 | P0 | `Email address (lowercase only)` | `Rahul.Fixture@Example.INVALID` | Paste `rahul.fixture@example.invalid`. |
| FMT-04 | P0 | `Date of birth (DD/MM/YYYY)` | `29.04.2002` | Paste `29/04/2002`. |
| FMT-05 | P0 | Generic `Telephone number (digits only)` | `0012 345-678` | First confirm the chosen mobile/landline value; paste `0012345678` without losing leading zeroes. |
| FMT-06 | P0 | Label is `SURNAME *` with no format phrase | `McDonald` | Paste `McDonald` unchanged. Uppercase label characters are not a format request. |
| FMT-07 | P0 | Ambiguous `04.05.2002` or conflicting date masks | unchanged source | Refuse automatic conversion; require manual review. |
| FMT-08 | P0 | Destructive phone request such as `last 10 digits` or a phone extension combined with E.164 | unchanged source | Refuse automatic conversion; never silently discard digits or extension text. |
| FMT-09 | P0 | Native select, custom dropdown, autocomplete, radio, native date input, or date-picker control | any | Leave unchanged and report unsupported/manual. V2 does not claim native/custom dropdown or native date-input automation. |
| FMT-10 | P0 | `Do not use capital letters` or `Uppercase is not allowed` | `ab123` | Keep `ab123` unchanged and require manual review. A negated uppercase instruction does not authorize lowercase or unchanged auto-paste. |
| FMT-11 | P0 | `Do not use DD/MM/YYYY` | `2025-07-04` | Keep the source unchanged and require manual review; do not select another date mask. |
| FMT-12 | P0 | `Do not use E.164` or `Digits only are prohibited` | `+91 98765 43210` | Keep the source unchanged and require manual review; do not apply an inverse or alternate phone transform. |

Recognized instructions must be explicit accessible metadata phrases such as
`uppercase`, `lowercase`, `digits only`, `E.164`, or an unambiguous supported
date mask. CSS capitalization and a label merely written in uppercase do not
request transformation. Date parsing is culture-invariant and calendar-valid.
Digits-only formatting removes separators as text rather than parsing a number,
so leading zeroes survive. A recognized case, date, or phone instruction that
is negated fails closed. Negation never means “apply the opposite transform.”

## Telephone matching and recommendations

| ID | Pri | Target and profile | Expected first use | Expected repeat or boundary |
| --- | --- | --- | --- |
| TEL-01 | P0 | Specific `Mobile Number *`, R | Auto-paste `contact.mobile`. | Never substitute landline or emergency phone. |
| TEL-02 | P0 | Generic `Telephone number *`, R | Picker defaults to exactly Landline Number and Mobile Number. The runtime-only remember checkbox is visible and checked. | After confirming one row with remember checked, the second unchanged-signature `Ctrl+Alt+V` auto-resolves that canonical field. |
| TEL-03 | P0 | Generic `Telephone number *`, S | Picker shows the one available Mobile Number. One related value still requires first-use confirmation. | Checked remember enables second unchanged-signature auto-paste. |
| TEL-04 | P0 | Generic `TELEPHONE / PHONE NUMBER *`, R | Default recommendations are exactly mobile and landline. | Alternate mobile, emergency phone, and calling code appear only after the user explicitly selects **Show all copied fields**; they are never marked Recommended. |
| TEL-05 | P0 | Generic telephone, S, remember unchecked before confirming | Paste only after confirmation. | Next unchanged-signature `Ctrl+Alt+V` opens the picker again. |
| TEL-06 | P0 | Specific `Alternate Phone No.*`, R | Auto-paste `contact.alternate_mobile`. | Never use primary mobile or landline. |
| TEL-07 | P0 | Specific `Emergency Contact Telephone *`, R | Auto-paste `emergency.phone`. | Never use an ordinary contact number. |
| TEL-08 | P0 | Specific `Country Calling Code (+) *`, R | Auto-paste `contact.country_calling_code`. | Never use a full phone number. |
| TEL-09 | P0 | Specific Mobile Number with only landline available | No automatic paste and no cross-kind recommendation. | Show a safe missing/manual result. |
| TEL-10 | P0 | Generic telephone, N | No automatic paste and no Recommended row. | The picker may expose the clearly identified full searchable fallback; choosing a value is deliberate user confirmation. |
| TEL-11 | P0 | Generic telephone with shuffled profile dictionary order | Same membership, rank, reason codes, and display order across runs. | No dictionary-order dependence. |
| TEL-12 | P1 | Search while recommendations-only mode is active | Search display name, Excel header, and canonical ID inside mobile/landline recommendations only. | Unrelated rows become searchable only after explicit **Show all copied fields**. Raw values are never searched. |
| TEL-13 | P0 | Generic `Telephone number` with help text `Include country code`, R | Treat the helper as full-number intent. Recommend exactly mobile and landline; never `contact.country_calling_code`. | Confirmation/runtime-memory rules remain the same as any generic telephone. Evidence: `PHONE-03`. |
| TEL-14 | P0 | `Mobile number with country code`, R | Keep the specific full-number semantic and recommend/match `contact.mobile`; never the standalone calling-code field. | A code value is used only when the target itself explicitly asks for the calling/dialing code. |
| TEL-15 | P0 | `Telephone number for calling` or another calling word without a code request | Never infer `contact.country_calling_code`. | Require a full-number candidate or manual confirmation. |

There is no first-use unique-candidate auto-paste for generic telephone. One
related value still requires confirmation. Automatic repeat is provided only by
the checked, exact-signature, memory-only choice described below.

## Section-qualified field safety

Section headings are bounded context, not decoration. The qualifiers
`Emergency`, `Previous`, `Former`, `Old`, `Alternate`, `Alternative`, and
`Secondary` prevent automatic use of a base passenger field when that base
field is section-sensitive.

| ID | Pri | Field and accessible section | Profile | Expected result | Evidence |
| --- | --- | --- | --- | --- | --- |
| SEC-01 | P0 | `Mobile number` in `Emergency Contact` | Q | Do not auto-paste `contact.mobile`. Recommend `emergency.phone` for confirmation when available. | `QUALIFIER-01` |
| SEC-02 | P0 | `Email` in `Emergency Contact` | Q | Do not auto-paste `contact.email`. Recommend `emergency.email` for confirmation when available. | Matcher theory |
| SEC-03 | P0 | `Passport number` in `Previous`, `Former`, or `Old passport information` | Q | Do not auto-paste `passport.number`. Recommend `passport.old_number` for confirmation when available. | `QUALIFIER-02`, `QUALIFIER-04` |
| SEC-04 | P0 | `Nationality` in `Previous` or `Former nationality` | Q | Do not auto-paste `personal.nationality`. Recommend `personal.previous_nationality` for confirmation when available. | `QUALIFIER-03` |
| SEC-05 | P0 | `Email` in `Alternate` or `Alternative Contact` | Q | Do not auto-paste `contact.email`. Recommend `contact.alternate_email` for confirmation when available. | `QUALIFIER-05` |
| SEC-06 | P0 | `Mobile number` in `Secondary Contact` | Q | Do not auto-paste `contact.mobile`. Recommend `contact.alternate_mobile` for confirmation when available. | `QUALIFIER-06` |
| SEC-07 | P0 | Any qualified section above when its specialized value is absent | Any | Never fall back to the available base field. Leave the target unchanged and require manual action. | Unit plus manual |

A specialized candidate remains a recommendation requiring confirmation unless
the direct target metadata itself independently provides a safe exact match.
Section context never authorizes substitution from the base field.

## Ambiguity and picker policy

| ID | Pri | Target | Expected result |
| --- | --- | --- | --- |
| AMB-01 | P0 | `Passport / Application Number *` | Never auto-paste; show only plausible identifier recommendations or a safe ambiguity result. |
| AMB-02 | P0 | `ID Number *` | Never infer passport versus national ID. |
| AMB-03 | P0 | `Reference No.*` | Unknown; never substitute a passport or copied identifier. |
| AMB-04 | P0 | `Number *` | Unknown; never infer from row order, prior picker selection, or numeric appearance. |
| AMB-05 | P0 | Conflicting strong UI Automation signals | Conflict blocks automatic paste even if only one conflicting field has a value. |
| AMB-06 | P0 | Password, file, read-only, disabled, submit, CAPTCHA-like, or unsupported control | Block before matching; the picker cannot override it. |
| AMB-07 | P0 | Picker remains open while focus or passenger generation changes | Reject the stale action and require focus/retry. |
| AMB-08 | P0 | One-time password/PIN, `one-time-code`, verification/authentication code, 2FA/two-factor, MFA, TOTP, or authenticator text/tel control | Block before saved mapping, normal match, or ranking. Return no picker candidates; neither picker nor remembered choice can override. |
| AMB-09 | P0 | `Country code`, `Country calling code`, or `Include country code` | Do not classify as authentication metadata. Continue through the explicit calling-code or full-number matching rules. |

Automatic paste is permitted only for:

1. one safe exact semantic match with an available value; or
2. a user-confirmed, remembered canonical choice for the exact unchanged
   runtime signature, after fresh protected-control, conflict, passenger, and
   focus checks.

## Exact browser insertion and source clipboard acquisition

| ID | Pri | Scenario | Expected result |
| --- | --- | --- | --- |
| INS-01 | P0 | Automatic match on a standard focused browser text field | Write the one bounded adapted value through that exact control's writable UI Automation `ValuePattern`; a clipboard sentinel remains unchanged. |
| INS-02 | P0 | Picker-confirmed match on a standard focused browser text field | After restoring focus, freshly revalidate and write through the same exact `ValuePattern`; the picker exposes no browser clipboard-fallback option. |
| INS-03 | P0 | Focus, browser window, element identity, runtime identity, or semantic metadata changes before the write | Reject and invalidate the stale target; insert nothing. |
| INS-04 | P0 | Enabled, read-only, password/protected, focusable, editable, control type, or writable-`ValuePattern` state changes before the write | Fresh inspection rejects the target; neither the picker nor remembered mapping bypasses the block. |
| INS-05 | P0 | Confirm a captured target after more than 10 minutes | Reject the expired handle. Before expiry, every use is still freshly revalidated; age alone never authorizes a write. |
| INS-06 | P0 | Portal control does not expose writable `ValuePattern` | Report safe failure/manual completion and leave the control unchanged. Never synthesize typing or escalate to `Ctrl+V`. |
| INS-07 | P0 | An allowlisted source state presents the clipboard warning and the user declines | Cancel without reading clipboard source data or altering the passenger session. |
| INS-08 | P0 | User confirms Excel/source clipboard acquisition with an explicit named header profile | Read only bounded selected tabular source text. Recheck the copied-selection sequence after the read and, only when stable, continue to parsing. Restore supported text formats or clear the app-owned selection only if the sequence is still owned. Warn that clipboard history may retain the source copy. |
| INS-09 | P0 | Another process changes the clipboard after the selection sequence is recorded but before the post-read check | Abort before parsing or session mutation, discard the read text, preserve the newer clipboard, and do not restore over it. |
| INS-10 | P0 | Focus/write work remains queued or pre-commit beyond the three-second deadline, then the provider/worker becomes available | Return safe failure. The abandoned operation gate prevents any later `SetFocus` or `SetValue`. |
| INS-11 | P0 | Exact UI Automation `SetFocus` or `SetValue` begins, then its provider blocks for longer than three seconds | Keep the workflow pending until the provider returns; never report a timeout while the side effect can still arrive late. A permanent provider hang is an availability failure requiring app restart. |
| INS-12 | P0 | Foreground source is not Excel, or inspection reports exact-access unavailable, timeout, or foreground Excel-instance mismatch | These four states are the complete clipboard-fallback allowlist. Show the warning and require an explicit named header profile plus affirmative confirmation. |
| INS-13 | P0 | Excel reports no selection, multiple areas, invalid/oversized dimensions, merged cells, displayed `####`, or any unknown failure | Reject with corrective guidance and leave the session unchanged. Never display the clipboard fallback prompt. |

Browser-field insertion and clipboard-based source acquisition are separate
trust paths. The latter is available only after explicit confirmation for the
four allowlisted source states above; selection-shape/content and unknown Excel
failures never enter that path.

## Runtime-only picker memory

The picker displays **Remember this choice for this browser window and app
session**. It is checked by default when a safe signature can be created; the
user may uncheck it before confirming.

The one-way signature includes browser process name and process ID, foreground
window handle, control type, accessible name, AutomationId, help text, class
name, placeholder, and input type. Text components are normalized. The mapping
stores only the canonical field ID, is bounded in memory, and is never written
to settings or diagnostics.

| ID | Pri | Scenario | Expected result |
| --- | --- | --- | --- |
| LRN-01 | P0 | First Smart Paste on generic `LEARN-01` | Show mobile/landline recommendations and the checked runtime-only remember control. Confirming stores the selected canonical ID for that exact signature. |
| LRN-02 | P0 | Second `Ctrl+Alt+V` on unchanged `LEARN-01` | Auto-resolve the remembered field if the active passenger contains it and all fresh checks pass. |
| LRN-03 | P0 | Same visible label on `LEARN-02`, but different AutomationId | Open the picker again. Label-only equality is insufficient. |
| LRN-04 | P0 | Change LEARN-01 accessible name after learning | Do not reuse the mapping; evaluate the new signature. |
| LRN-05 | P0 | `LEARN-03` has the same label but an emergency-phone AutomationId | Do not reuse the ordinary telephone choice; fresh conflict/specific-semantic handling wins. |
| LRN-06 | P0 | Switch passenger or focus while the picker is open | Reject the stale selection. Memory never bypasses snapshot/focus checks. |
| LRN-07 | P0 | Unchanged signature, but active passenger lacks the remembered field | Return missing value; do not substitute another phone field. |
| LRN-08 | P0 | Pause Smart Paste | Memory remains in process but cannot bypass pause. After resume, only the exact signature may reuse it. |
| LRN-09 | P0 | Clear All, inactivity timeout, Windows lock/sign-out, explicit Exit, app restart, or clearing the final passenger | Mapping is cleared; first use after a new passenger is copied requires confirmation again. |
| LRN-10 | P0 | Same human label in another browser process/window, including Chrome versus Edge versus Brave | Treat it as a different signature and require confirmation. |
| LRN-11 | P0 | Remember checkbox is unchecked | Complete the selected paste but store no mapping; repeat opens the picker. |
| LRN-12 | P0 | Clear one active passenger while at least one other passenger remains | Remove that passenger but preserve runtime mappings for the still-active session. Reuse still requires the exact unchanged target and all fresh checks. |
| LRN-13 | P0 | Clear the only or final remaining passenger | Clear runtime mappings with the empty session. Recopying a passenger does not revive the prior choice. |

Without an extension, V2 cannot identify domain, URL, page, or account. It does
not provide or claim persistent per-website learning.

## Larger responsive UI

Logical sizes before DPI scaling are:

| Window | Default | Declared minimum |
| --- | --- | --- |
| Main | 1040 x 720 | 780 x 560 |
| Field picker | 820 x 600 | 700 x 500 |
| Header mapping | 920 x 680 | 700 x 500 |
| Shortcut settings | 760 x 620 | 700 x 520 |
| Diagnostics | 820 x 600 | 700 x 500 |

All windows use per-monitor DPI scaling, responsive grids, and working-area
clamping. On a work area smaller than the scaled minimum, the app may clamp the
window further and expose vertical scrolling; primary actions must remain
reachable.

| ID | Pri | Environment | Pass criteria |
| --- | --- | --- | --- |
| UI-01 | P0 | 100%, 125%, and 150% on 1366 x 768 | Every window stays inside the work area. Labels, status, checkboxes, grids, and actions do not overlap. |
| UI-02 | P0 | 200% on 1920 x 1080 | Window is clamped to the work area; primary actions remain keyboard reachable and vertical scrolling works if required. |
| UI-03 | P0 | Picker at 700 x 500 logical minimum | Focused-field card, search, status, grid headers, runtime-only remember option, Paste, and Cancel remain usable. No browser clipboard-fallback control is present. No horizontal scrollbar is needed for normal content. |
| UI-04 | P0 | Picker at 820 x 600 default | The clipped 601-pixel-wide layout is replaced by three fill-width columns and readable spacing. |
| UI-05 | P0 | Picker widened and reduced to minimum repeatedly | Columns consume available width without recreating the large blank region or clipped fixed columns. |
| UI-06 | P0 | Keyboard-only picker | Search has initial focus; Down enters results; arrows navigate; Enter pastes; Escape cancels; Ctrl+F returns to search. |
| UI-07 | P0 | Target near every monitor edge, taskbar, and secondary monitor | Picker remains wholly within the target monitor working area. |
| UI-08 | P0 | TEL-02 through TEL-04 at every required scale | Recommendations-only mode exposes only available mobile/landline rows to search and keyboard selection. |
| UI-09 | P1 | Long source headers and translated-style labels at 200% | Text does not paint over adjacent controls; truncation remains accessible. |
| UI-10 | P1 | Main window at minimum with two passengers | Active passenger, lock/pause state, navigation, clear, and options remain understandable. |

Capture each window at 100% and 200%, plus picker screenshots at 125% and 150%.
Record resolution, scale, actual window size, browser, and build hash.

## Privacy and masking

| ID | Pri | Scenario | Expected result |
| --- | --- | --- | --- |
| PRIV-01 | P0 | Any picker row | Raw passenger values never appear. Phone shows at most the last four digits; names, identifiers, dates, and email local parts follow their field-specific masks. |
| PRIV-02 | P0 | Generic telephone picker | Default recommendations contain only available mobile/landline rows. Other copied fields remain masked and become visible only through explicit **Show all copied fields**. |
| PRIV-03 | P0 | Search for text present only in a raw passenger value | No match. Search uses display name, Excel header, and canonical ID only. |
| PRIV-04 | P0 | Fixture input/change/blur/submit monitor | Log case ID, event, element identity, and value length only. |
| PRIV-05 | P0 | Diagnostics after matching, picker, memory, formatting, and paste | No passenger value, raw workbook path, raw target label, or signature material is logged. Reason codes and canonical IDs are allowed. |
| PRIV-06 | P0 | Runtime memory lifecycle | Signature is a one-way hash; mapping contains a canonical ID only and is not persisted. It may survive clear-one only while another passenger remains and is cleared with the final passenger. |
| PRIV-07 | P0 | Explicit source clipboard acquisition in an allowlisted source state | Only bounded selected tabular source text crosses the clipboard. A post-read sequence mismatch aborts before import. Guarded restore/clear never overwrites a newer third-party value, and browser insertion never uses this path. |
| PRIV-08 | P1 | Screen sharing | Masked previews distinguish choices without reveal-on-hover. |

Any raw passenger value in the picker, diagnostics, fixture log, persisted
settings, or release evidence is a release blocker.

## Automation and evidence

Minimum V2 evidence:

- Existing Core/App tests cover decorated labels, two-field telephone ranking,
  first-use confirmation, full-number country-code help, section qualifiers,
  session signature and clear-final boundaries, negated/safe formatting,
  two-protective-modifier hotkeys, Excel-fallback allowlisting and post-read
  sequence stability, exact `ValuePattern` insertion revalidation, responsive
  picker behavior, and Brave support.
- `scripts/test-v2-fixture.ps1` passes.
- Every case in `MANUAL_ACCEPTANCE.md` passes in Chrome, Edge, and Brave where
  browser behavior is involved.
- Physical 100%, 125%, 150%, and 200% DPI evidence is recorded.
- Original header/copy/paste workflow cases remain green as V2 regression
  coverage.
- Package evidence records `sourceState`, including `dirty` or
  `untracked-source` when applicable, and non-empty `sourceSha256` plus a
  positive `sourceFileCount`.

Use:

```text
PASS
FAIL
BLOCKED-ENVIRONMENT
NOT-RUN
```

`BLOCKED-ENVIRONMENT` and `NOT-RUN` are not passes.

## Frozen-integration verification status

The current V2 source includes deterministic candidate ranking, the larger
DataGrid-based picker, exact-signature process-memory mappings, explicit safe
value adaptation, exact focused-control `ValuePattern` writes with fresh
revalidation, a 10-minute maximum target-handle lifetime, responsive window
clamping, three-second pre-commit abandonment, wait-to-completion after a UI
Automation side effect begins, and Chrome/Edge/Brave process support. Browser
clipboard fallback is absent; shared clipboard use is limited to explicitly
confirmed source acquisition in the four allowlisted source states, with a
post-read sequence check before import. Invalid or unknown Excel-selection
failures never prompt. This QA track has statically validated the fixture
contract. Physical browser, monitor, DPI, provider-stall, and packaged-artifact
acceptance remain release gates until their evidence is recorded.
