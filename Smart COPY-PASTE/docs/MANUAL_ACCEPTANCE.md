# Manual Acceptance Test

Use synthetic values only. Do not use a real passenger or passport during
development acceptance.

## Preconditions

- Windows 11 x64 non-administrator user. A Microsoft/.NET-supported Windows 10
  Enterprise/LTSC x64 edition may be used as secondary coverage.
- Microsoft Excel with two saved workbooks.
- Current Chrome, Microsoft Edge, and Brave.
- Release build or packaged EXE.
- Fixture server running:

```powershell
cd "C:\Users\nipun\Desktop\PassDetection\Smart COPY-PASTE"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-fixture.ps1
```

- Browser open at
  [http://localhost:8765/browser-form.html](http://localhost:8765/browser-form.html).

Use these synthetic rows:

```text
Surname	Given Name	Passport No.	Date of Birth	Nationality	Email	Mobile Number
Sharma	Rahul	Z1234567	15/08/1998	Indian	rahul.fixture@example.invalid	0012345678
Verma	Priya	Y7654321	04/11/1995	Indian	priya.fixture@example.invalid	0098765432
```

## Core workflow

### MA-01 — First header capture

1. Select only the seven header cells in Workbook A.
2. Press `Ctrl+Alt+H`.
3. Confirm the header-success notification.
4. Select Rahul's seven value cells without the headers.
5. Press `Ctrl+Alt+C`.

Expected: one passenger is active, all seven cells are recognized, and leading
zeroes in the phone value remain intact.

### MA-02 — Header-once repeat

1. Clear all temporary passenger data but leave the app running.
2. Select Priya's row in the same worksheet without the header.
3. Press `Ctrl+Alt+C`.

Expected: the exact saved header profile is used without recapturing headers.

### MA-03 — Cross-file isolation

1. Create Workbook B with seven different headers but the same column count.
2. Select one data row and press `Ctrl+Alt+C`.

Expected: Workbook A's profile is not selected by width. The app requests an
exact or explicitly selected header profile.

### MA-04 — Invalid row width

1. In Workbook A, select only six of the seven cells.
2. Press `Ctrl+Alt+C`.

Expected: an actionable width error appears and the previously active
passenger session remains unchanged.

### MA-05 — Multiple passengers

1. Select both synthetic passenger rows without the header.
2. Press `Ctrl+Alt+C`.
3. Lock the active passenger.
4. Press `Ctrl+Alt+Right`.
5. Unlock and press `Ctrl+Alt+Right`.

Expected: two passengers load in order. Locking blocks the switch. Unlocking
switches visibly to passenger 2. No action automatically wraps or advances.

Press `Ctrl+Alt+X`. Expected: only passenger 2 is cleared, passenger 1 becomes
active, and the remaining collection is not discarded.

## Browser fixture

### MA-06 — Exact field matching in random order

With Rahul active, paste into fixture fields in this order:

1. Passport Number
2. Email Address
3. Surname
4. Given Name
5. Mobile Number

Expected: every field receives Rahul's corresponding value. The order is
irrelevant. The fixture event log records input-related events and value
lengths but not actual values.

### MA-07 — Ambiguous passport/application field

1. Focus **Application Number — conflicting metadata**.
2. Press `Ctrl+Alt+V`.

Expected: no automatic paste occurs. The picker or a safe ambiguity message
appears. Choosing `Passport Number` manually pastes only after confirmation.

### MA-08 — Unknown field

1. Focus **Unknown loyalty code**.
2. Press `Ctrl+Alt+V`.
3. Use `Ctrl+Alt+P`, search by canonical field or original header, choose a
   value, then press Enter.
4. Repeat and cancel with Escape.

Expected: unknown metadata never auto-pastes. Picker navigation, search, Enter,
and Escape work. Displayed sensitive values are masked.

### MA-09 — Protected controls

Attempt Smart Paste on:

- password;
- file upload;
- disabled input;
- read-only input;
- one-time password, one-time PIN, `autocomplete="one-time-code"`, verification
  code, 2FA, two-factor authentication, MFA, TOTP, authentication-code, and
  authenticator-code text/tel inputs; and
- CAPTCHA-like input.

Expected: all are blocked with a safe message. No picker selection overrides
the block. Then test the explicit Country Calling Code field and generic
`PHONE-03` help `Include country code`; neither is authentication-protected.
They continue through their normal calling-code or full-number matching rules.

### MA-10 — Dynamic field

1. Click **Add dynamic field** on the fixture.
2. Focus the newly inserted Passport Expiry Date field.
3. Trigger Smart Paste or the picker.

Expected: the field is inspected at trigger time. The app does not depend on a
page scan performed at startup.

### MA-11 — No submission

Complete every previous fixture case and inspect **Submit attempts**.

Expected: the counter remains `0` unless the tester explicitly clicks
**Fixture Submit**. Smart Paste never clicks the button or submits the form.

## Insertion, source clipboard acquisition, and lifecycle

### MA-12 — Exact target write and Excel/source clipboard acquisition

1. Copy `ORIGINAL_CLIPBOARD_SENTINEL` from Notepad.
2. Focus a standard fixture text field and complete automatic Smart Paste.
3. Repeat through the picker, then paste normally back into Notepad.

Expected: both browser writes use the exact focused control's UI Automation
`ValuePattern`. Notepad still receives `ORIGINAL_CLIPBOARD_SENTINEL`; browser
insertion never changes the clipboard and the picker has no clipboard-fallback
option.

Open the picker on a fixture field, leave it open for more than 10 minutes, and
then try to confirm. Repeat without waiting while changing focus or making the
target protected/read-only before confirmation.

Expected: the expired or changed target is rejected and nothing is inserted. A
captured handle can live for at most 10 minutes, but every write still requires
fresh exact-target, semantic, protected/editable-state, and focus validation.

Using controlled UI Automation provider test evidence, delay a focus/write
operation before its side effect begins for more than three seconds, then
release it. Separately, delay inside exact `SetFocus` or `SetValue` after the
side effect begins.

Expected: queued/pre-commit work returns a safe failure and cannot focus or
write when released later. Already-started provider work remains pending beyond
three seconds rather than reporting a failure that could be followed by a late
side effect; releasing the provider completes exactly that one commit. If the
provider remains hung, restart the app before further testing and recopy the
passenger data.

Using controlled source states, verify that the clipboard warning appears only
for:

1. a foreground source that is not Excel;
2. `EXCEL_SELECTION_UNAVAILABLE`;
3. `EXCEL_TIMEOUT`; and
4. `EXCEL_FOREGROUND_INSTANCE_MISMATCH`.

For one allowed state, select tabular source text, choose the intended named
header profile, accept the warning, and complete header/passenger capture.
Paste normally into Notepad afterward.

Expected: the source rows parse only after confirmation. The previous
restorable clipboard text returns, or the app-owned selection is cleared when
there was no snapshot. The warning correctly states that clipboard-history
software may retain the source application's copy.

Use controlled clipboard evidence to change the sequence after the app records
the copied selection but before its post-read sequence check.

Expected: acquisition aborts with **Nothing was imported** semantics; the text
read under the unstable sequence is never parsed and the active passenger
session is unchanged. The newer third-party clipboard value is preserved and
is not overwritten by snapshot restoration.

Finally, produce or simulate `EXCEL_NO_SELECTION`,
`EXCEL_MULTI_AREA_SELECTION`, `EXCEL_SELECTION_SIZE_INVALID`,
`EXCEL_MERGED_SELECTION`, `EXCEL_DISPLAY_VALUE_OBSCURED` (`####`), and an
unknown Excel failure.

Expected: each state rejects with corrective guidance and leaves the passenger
session unchanged. None displays the clipboard fallback prompt.

### MA-13 — Pause and resume

1. Press `Ctrl+Alt+Space`.
2. Focus a fixture field and press `Ctrl+Alt+V`.
3. Press `Ctrl+Alt+Space` again and retry.

Expected: paused state is visible and blocks paste; resumed state pastes
normally.

### MA-14 — Close versus Exit

1. Open the app window, then close it.
2. Verify the tray icon remains and Smart Paste still works.
3. Choose **Exit** from the tray.
4. Retry all Smart COPY/PASTE hotkeys.

Expected: closing hides the window. Exit removes the tray icon, releases the
hotkeys, clears temporary values, and terminates the process.

### MA-15 — Restart privacy

1. Restart the app after MA-14.
2. Trigger Smart Paste before copying any passenger.
3. Return to Workbook A and copy a row without recapturing its headers.

Expected: no passenger was restored. The saved header profile remains
available for the same workbook and worksheet.

### MA-16 — Windows lock

1. Copy the synthetic passengers.
2. Lock and unlock Windows.
3. Trigger Smart Paste.

Expected: the sensitive passenger session has been cleared according to the
configured lock policy.

### MA-16A - Configurable shortcut safety

1. Open **Shortcut Settings** from the tray.
2. Set Smart Paste to `Shift+V` and try to apply it.
3. Repeat with `Ctrl+V`.
4. Set Smart Paste to an otherwise unused two-protective-modifier chord such as
   `Ctrl+Shift+V` and apply it, then restore the default.

Expected: both single-modifier chords are rejected with guidance to use at
least two of Ctrl, Alt, and Shift. The valid two-modifier chord is accepted if
Windows has not already registered it. Automated settings evidence must also
show that Windows-only chords, including `Windows+V`, fail as
`HOTKEY_CHORD_UNSAFE`; the Windows modifier does not count toward the two.

## Package acceptance

### MA-17 — Clean-user portable run

On a clean non-admin Windows 11 x64 user or Windows Sandbox:

1. Verify the EXE hash against `SHA256SUMS.txt`.
2. Run the EXE without installing .NET.
3. Complete MA-01, MA-06, MA-14, and MA-15.

Expected: one EXE starts without elevation or an installed .NET runtime.
Unsigned V2 may display SmartScreen **Unknown publisher**; do not disable
SmartScreen.

### MA-18 — Per-user install and uninstall

1. Run `scripts\install.ps1`.
2. Start the app from the Start Menu shortcut.
3. Run `scripts\uninstall.ps1`.
4. Repeat with `-RemoveUserData`.

Expected: installation is under Local AppData, requires no elevation, and
creates one Start Menu shortcut. Default uninstall preserves settings; the
explicit data-removal option deletes them.

## V2 matching and picker acceptance

Open
[http://localhost:8765/v2-regression-form.html](http://localhost:8765/v2-regression-form.html)
in Chrome, Edge, and Brave. Use the case IDs in
[V2_REGRESSION_MATRIX.md](V2_REGRESSION_MATRIX.md) when recording evidence.

For rich-phone tests, capture this additional synthetic header row and value
rows in a separate workbook profile:

```text
Surname	Given Name	Passport No.	National ID Number	Email	Mobile Number	Alternate Mobile Number	Landline Number	Country Calling Code	Emergency Contact Phone
Sharma	Rahul	Z1234567	TEST-NID-0001	rahul.fixture@example.invalid	0012345678	0011122233	0022334455	+91	0044556677
Verma	Priya	Y7654321	TEST-NID-0002	priya.fixture@example.invalid	0098765432	0099887766	0033445566	+91	0066778899
```

For format-hint tests, use these two synthetic rows:

```text
Surname	Passport No.	Email	Date of Birth	Landline Number
Sharma	z1234567	Rahul.Fixture@Example.INVALID	29.04.2002	0012 345-678
McDonald	y7654321	Priya.Fixture@Example.INVALID	04.11.1995	0098 765-432
```

For section-qualified tests, use this synthetic profile:

```text
Passport No.	Old Passport Number	Nationality	Previous Nationality	Email	Alternate Email	Mobile Number	Alternate Mobile Number	Emergency Contact Phone	Emergency Contact Email
Z1234567	OLD-Z12345	Currentland	Formerland	rahul.fixture@example.invalid	rahul.alt@example.invalid	0012345678	0011122233	0044556677	emergency.fixture@example.invalid
```

For the missing-specialized check, copy another row under the same headers with
ordinary Passport, Nationality, Email, and Mobile Number values but leave every
Old/Previous/Alternate/Emergency cell blank.

### MA-19 - Mixed case and presentation punctuation

With the screenshot-like profile active, paste into `NORMALIZE-01` through
`NORMALIZE-04`.

Expected: all four fields paste automatically. Changing only case, colons,
periods, parentheses, or required asterisks produces the same canonical match
and does not open the picker.

### MA-20 - Screenshot-derived portal labels

Paste into `LABEL-01` through `LABEL-09` in random order, then retry each field.
Attempt `LABEL-10` with no copied Religion column.

Expected: surname, given name, date of birth, sex/gender, nationality, national
ID, email, confirmation email, and place of birth resolve to their intended
fields without a recurring picker. `LABEL-10` remains empty and the application
does not invent a religion value. The compound given-name label does not paste
the separately copied middle name or concatenate fields.

### MA-21 - One related telephone value still requires confirmation

Use the original screenshot-like profile, which contains one mobile number and
no landline. Focus `PHONE-02`, then `PHONE-03`, and Smart Paste each twice.

Expected: first use opens a picker containing only Mobile Number, even though it
is the sole related value. **Remember this choice for this browser window and
app session** is visible and checked. Confirm Mobile Number, clear the target,
and press `Ctrl+Alt+V` again on the unchanged control; the second action
auto-resolves the remembered field. Leading zeroes remain intact. Repeat once
with remember unchecked; the next action must ask again. `PHONE-03` help says
`Include country code`; it still represents a complete phone number and never
recommends Country Calling Code.

### MA-22 - Rich phone semantics and narrowed candidates

Activate the rich-phone profile.

1. Paste into specific targets `PHONE-01`, `PHONE-04`, `PHONE-05`, and
   `PHONE-06`.
2. For generic `PHONE-02` and `PHONE-03`, inspect the default recommendation
   rows before confirming.
3. Select **Show all copied fields** and inspect the broadened list.
4. Search for `passport`, `email`, and a substring present only in one raw
   phone value.

Expected: specific mobile, alternate-mobile, emergency-phone, and calling-code
targets paste their corresponding values. On first use, generic Telephone does
not treat landline as an exact automatic match: the default view
shows exactly the available Mobile Number and Landline Number recommendations,
with runtime-only remember checked. Alternate mobile, calling code, emergency
phone, names, identifiers, dates, and email are not Recommended. They may
appear, masked, only after explicit **Show all copied fields**. Raw-value
searches never return a row. In particular, the `Include country code` helper
on `PHONE-03` does not change its mobile/landline recommendation family.

### MA-23 - Missing and cross-kind phone safety

Create a synthetic profile with a landline but no mobile, then focus
`PHONE-01`. Next activate a profile with no phone values and test `PHONE-02`
and `PHONE-03`.

Expected: an explicit mobile target never receives the landline. A profile
with no compatible phone value produces no automatic paste or Recommended
choice. The picker may expose its clearly identified full searchable fallback;
any selection requires deliberate confirmation.

### MA-24 - Material identifier ambiguity

Attempt Smart Paste on `AMBIGUOUS-01` through `AMBIGUOUS-04`.

Expected: no field is populated automatically. Passport/application and ID
ambiguity stays limited to plausible identifier choices; Reference and bare
Number are treated as unknown. No choice is made from spreadsheet order or a
previous picker selection.

### MA-24A - Section-qualified field safety

Activate the section-qualified profile and attempt Smart Paste on
`QUALIFIER-01` through `QUALIFIER-06`.

Expected: no base/current field auto-pastes. Emergency Contact narrows phone to
`emergency.phone`; Previous/Former/Old context narrows passport or nationality
to `passport.old_number` or `personal.previous_nationality`; and
Alternate/Secondary Contact narrows email or mobile to
`contact.alternate_email` or `contact.alternate_mobile`. Each specialized
candidate requires deliberate confirmation unless the target's own direct
metadata independently creates a safe exact match. The diagnostic reason for
the blocked base match is `SECTION_CONTEXT_CONFLICT`.

Activate the row whose specialized cells are blank and repeat all six controls.
Expected: every target stays unchanged for manual completion. An available base
Passport, Nationality, Email, or Mobile value is never offered as a substitute.

### MA-25 - Explicit value-format hints

Activate the first format-hint row and paste into `FORMAT-01` through
`FORMAT-04`. For generic `FORMAT-05`, choose Landline Number in the narrowed
picker and keep runtime-only remember checked.

Expected:

- uppercase-only surname becomes `SHARMA`;
- uppercase-only passport becomes `Z1234567`;
- explicitly lowercase email becomes
  `rahul.fixture@example.invalid`;
- `29.04.2002` becomes `29/04/2002`; and
- digits-only telephone becomes `0012345678`, preserving both leading zeroes.

The copied values shown in the main application remain unchanged. Clear
`FORMAT-05` and repeat on the unchanged signature; the remembered Landline
Number is formatted and pasted automatically.

### MA-26 - No implicit formatting or native-control claim

Activate the second format-hint row and paste into `FORMAT-06`, then attempt
Smart Paste on all three controls in `FORMAT-07`.

Expected: the all-uppercase label `SURNAME *` receives `McDonald` unchanged.
Label styling alone does not request uppercase output. The Passport Number help
`Do not use capital letters` fails closed: the field stays unchanged for manual
review and the app does not infer lowercase or any inverse transform. The
native nationality dropdown and native date input also stay unchanged and
receive a clear unsupported/manual outcome; V2 does not claim native/custom
dropdown or native date-input automation.

### MA-27 - Runtime-only picker learning

With the rich-phone profile active:

1. Copy both rich-phone passenger rows. Focus `LEARN-01`, invoke Smart Paste,
   and choose Mobile Number.
2. Clear the target, keep focus on the same control, and press `Ctrl+Alt+V`
   again.
3. Clear the active passenger while the other rich-phone passenger remains,
   clear `LEARN-01`, and press `Ctrl+Alt+V` again on that unchanged target.
4. Clear the final passenger, recopy one rich-phone passenger, clear
   `LEARN-01`, and press `Ctrl+Alt+V` again.
5. Focus `LEARN-02`, whose visible label is the same but AutomationId differs.
6. Focus `LEARN-03`, whose visible label is the same but AutomationId indicates
   emergency phone.
7. Return to `LEARN-01`, click **Change LEARN-01 signature**, clear the target,
   and press `Ctrl+Alt+V`.
8. Click **Reset LEARN-01 signature**, restart the application, recopy the
   synthetic passenger, and retry `LEARN-01`.

Expected: the first choice is manual; the second unchanged-signature action
auto-resolves Mobile Number because the runtime-only remember checkbox was
checked. Clearing one passenger preserves that exact mapping while another
passenger remains, so step 3 auto-resolves the remaining passenger's Mobile
Number after all fresh checks. Clearing the final passenger clears the mapping,
so step 4 opens the picker. `LEARN-02` does not inherit it. `LEARN-03` and
changed metadata do not reuse it; both are freshly evaluated, including their
emergency signal. After restart, the reset ambiguous target opens the picker
again. Repeat with remember unchecked and verify the same unchanged target asks
again. No learned choice is written to settings or described as a per-domain
rule.

### MA-28 - Picker focus and session revalidation

1. Open the narrowed picker on `PHONE-03`.
2. Before confirming, switch the active passenger.
3. Repeat while moving browser focus to another field.
4. Repeat while clearing the active passenger.

Expected: all three stale selections are rejected. The application asks the
tester to focus and retry; it never pastes from the old passenger or into the
old target.

### MA-29 - Larger picker and keyboard

Open the narrowed picker at its 820 x 600 logical-pixel default, then resize it
to its 700 x 500 logical-pixel declared minimum at 100% scale.

Expected: focused-field context, search, recommendation status, all three
fill-width columns, the runtime-only remember checkbox, Paste, and Cancel
remain usable. No browser clipboard-fallback control is present. There is no
horizontal scrollbar for normal content.
Search receives initial focus; Down and arrow keys navigate; Enter pastes;
Escape cancels; Ctrl+F returns to search. Widening the picker gives the columns
the extra width. The old clipped 601-pixel-wide layout is not the V2 minimum.

### MA-30 - DPI and working-area matrix

Repeat the window checks below. Sign out and back in when Windows requests it
after a display-scale change.

| Scale | Minimum environment | Required evidence |
| --- | --- | --- |
| 100% | 1366 x 768 | Main window and every dialog at documented default and minimum size |
| 125% | 1366 x 768 | Main window and narrowed picker at default and minimum size |
| 150% | 1366 x 768 | Main window and narrowed picker at default and minimum size |
| 200% | 1920 x 1080 | Main window and every dialog at default and minimum size |

Expected: windows remain inside the monitor working area; text and controls do
not overlap; primary and cancel actions remain reachable; the picker never
clips columns or hides selectable rows. Verify placement with a target near
each screen edge and on a secondary monitor when available.

### MA-31 - V2 privacy and masking

With the rich-phone profile active, open the narrowed and explicit full
pickers, cancel them, generate a sanitized diagnostic report, then Exit and
restart.

Expected: picker values are masked; phone previews reveal at most the last four
digits; unrelated rows are not selectable in recommendations-only mode and
appear only after explicit **Show all copied fields**; raw-value search does not
work; the fixture log contains lengths but no values; diagnostics contain no
passenger values, workbook path, target label, or signature material;
runtime-learned mappings contain only hashed signatures plus canonical IDs and
do not survive restart.

## Evidence record

Record:

```text
Application version:
EXE SHA-256:
Manifest commit:
Manifest sourceState:
Manifest sourceSha256:
Manifest sourceFileCount:
Windows version:
Excel version:
Chrome version:
Edge version:
Brave version:
Tester:
Date:
Cases passed:
Cases failed:
Display scale(s):
Display resolution(s):
Picker screenshot path(s):
Sanitized diagnostic report path:
```

Any wrong-field paste, cross-passenger paste, unexpected submission, passenger
value in diagnostics, an unrelated field marked as a generic telephone
recommendation, full-number country-code help treated as a calling-code field,
qualified-section fallback to a base field, inverse transform from a negated
instruction, mapping retained without an active passenger, unsafe configurable
shortcut, OTP/PIN/2FA/MFA/authenticator control offered or modified, benign
country-code metadata authentication-blocked, clipped primary action, persisted
runtime learning, browser clipboard fallback, stale-target write, or Excel
acquisition after a post-read sequence change, non-allowlisted Excel fallback
prompt, or clipboard cleanup failure blocks release.
