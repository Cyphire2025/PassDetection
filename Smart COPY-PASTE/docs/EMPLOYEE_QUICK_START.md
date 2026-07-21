# Employee Quick Start

Smart COPY/PASTE lets you copy passenger data from Excel once, then fill browser
fields in any order. It stays in the Windows notification area until you
explicitly exit it.

## Before you start

- Use a saved Microsoft Excel workbook.
- Keep the header row and passenger rows in contiguous columns.
- Use one column for one meaning, such as `Surname`, `Given Name`, or
  `Passport No.`.
- Do not use real passenger data while learning. Use the local fixture and
  synthetic values first.

## 1. Save the header row once

1. Open the workbook and worksheet that contains the passenger table.
2. Select only the header cells. Do not select Excel's row number.
3. Press `Ctrl+Alt+H`.
4. Wait for the **Headers saved** notification and review any unknown or
   duplicate headers.

The header profile is associated with that saved workbook and worksheet. The
profile contains column meanings, not passenger values. You normally repeat
this step only after changing headers or using a different workbook or
worksheet.

If Excel cannot provide a stable workbook identity, Smart COPY/PASTE asks you
to select a header profile. It never chooses another file's profile merely
because the number of columns happens to match.

## 2. Copy passenger rows

1. Select one passenger row or several adjacent passenger rows.
2. Do not include the header row.
3. Press `Ctrl+Alt+C`.
4. Confirm the passenger count and active passenger in the notification or
   tray menu.

Passenger values remain in application memory only. Copying a new collection
replaces the active collection only through a visible action; it never silently
appends rows from another file.

## 3. Paste fields in any order

1. Open the target form in Chrome, Microsoft Edge, or Brave.
2. Click the field you intend to fill.
3. Press `Ctrl+Alt+V`.
4. Confirm that the expected value appears.

You can fill `Passport Number`, then `Surname`, then `Email`, or any other
order. Smart COPY/PASTE independently evaluates the focused field every time.
It does not advance through Excel columns sequentially.

If a field is unknown or ambiguous, Smart Paste does not guess. It opens the
field picker with related recommendations when available. You can also press
`Ctrl+Alt+P` to open the picker deliberately, search by passenger field or
Excel header, and select the correct value.

For a generic `Telephone number`, first use always requires confirmation—even
when only one related value was copied. The default recommendation list
contains only available Mobile Number and Landline Number values. Alternate
mobile, emergency phone, calling code, and unrelated passenger fields are not
generic recommendations. Select **Show all copied fields** only when you
intentionally need the full masked list.

Help such as `Include country code` still asks for the complete mobile or
landline number. It does not mean the separate Country Calling Code field. Only
a target that explicitly asks for a calling or dialing code uses that field.
These ordinary country-code phrases are not treated as authentication fields.

Pay attention to section headings. A generic-looking field in an
`Emergency`, `Previous`/`Former`/`Old`, or
`Alternate`/`Alternative`/`Secondary` section never receives the ordinary
current/primary value automatically. Confirm the specialized recommendation
when one exists; if it does not, complete the field manually.

When available, **Remember this choice for this browser window and app
session** is checked in the picker. Keep it checked to let the second
`Ctrl+Alt+V` on the exact unchanged field reuse your confirmed canonical
choice. Uncheck it to require confirmation next time. Clearing one passenger
keeps the choice only while another passenger remains. Clearing the only or
final passenger forgets it, as do Clear All, Windows lock, inactivity cleanup,
Exit, and restart. It is not saved as a website/domain rule.

An explicit target hint such as `UPPERCASE`, `lowercase`, `DD/MM/YYYY`, or
`digits only` may safely format the one outgoing value. The passenger data in
memory remains unchanged. An all-uppercase label without a format phrase does
not request uppercase output. Ambiguous or destructive conversions are blocked
for manual review. A negated instruction such as `Do not use capital letters`
or `Do not use DD/MM/YYYY` also stays manual; Smart COPY/PASTE does not apply
the opposite format.

## 4. Work with multiple passengers

| Action | Shortcut |
| --- | --- |
| Next passenger | `Ctrl+Alt+Right` |
| Previous passenger | `Ctrl+Alt+Left` |
| Open field picker | `Ctrl+Alt+P` |
| Pause or resume | `Ctrl+Alt+Space` |
| Clear active passenger | `Ctrl+Alt+X` |

The tray menu also provides **Lock Passenger**, **Next Passenger**,
**Previous Passenger**, **Clear Active Passenger**, and **Clear All Temporary
Data**.

Before every paste, verify the active passenger indicator. Smart COPY/PASTE
does not automatically advance to the next passenger. Lock the passenger when
working on a long or sensitive form.

## Tray behavior

- **Open Smart COPY/PASTE** opens the status window.
- Closing a window returns the application to the tray.
- **Pause** blocks Smart Paste without deleting the passenger collection.
- **Clear Active Passenger** removes the selected passenger. Runtime field
  choices remain if another passenger is still loaded, but are cleared when
  this removes the final passenger.
- **Clear All Temporary Data** removes every in-memory passenger and forgets
  runtime-only field choices.
- **Exit** clears temporary passenger data, releases the global hotkeys, and
  ends the process.

## Safe insertion and fallback behavior

Without a browser extension, Chrome, Edge, and Brave expose only Windows
accessibility metadata. Some fields therefore require the picker. V2 cannot
scope remembered choices by domain, URL, page, or account, so they stay in the
current browser window and app process only.

Browser values are inserted only through the exact focused control's Windows
UI Automation `ValuePattern`. Immediately before the write, Smart COPY/PASTE
rechecks the browser window, exact control, focus, semantic metadata, and
protected/editable state. A captured target handle can be retained for up to
10 minutes, but it is revalidated every time and never grants permission by
itself.

Browser insertion does not type keystrokes, change the clipboard, or offer a
normal-paste fallback. If the portal does not expose a writable standard text
control, no value is inserted; complete that field manually.

The app may offer a separate clipboard acquisition fallback only when the
foreground source is not Excel, exact Excel inspection is unavailable or times
out, or Excel's automation instance does not match the foreground Excel window.
Continue only after reviewing its warning and selecting the intended header
profile.

If Excel reports no selection, multiple separate areas, too many rows/columns,
merged cells, displayed `####`, or another unknown selection failure, correct
the range and retry. Smart COPY/PASTE rejects these states without offering the
clipboard prompt.

During an allowed fallback, the app rechecks the clipboard sequence immediately
after reading the selected text. If another program changed it, nothing is
imported. The app restores or clears its selection only while it still owns the
sequence, but Windows or third-party clipboard history may retain the source
application's copy. This fallback reads tabular source data; it never pastes a
passenger value into a browser field.

Smart COPY/PASTE never:

- guesses from a weak or contradictory field description;
- enters data into password, file-upload, native date, disabled, or
  CAPTCHA-like controls;
- enters data into one-time password/PIN, one-time-code, 2FA/two-factor, MFA,
  authentication-code, TOTP, or authenticator-code controls, even when they use
  ordinary text or telephone input types or the picker;
- claims automation for native/custom dropdowns, radios, native date inputs,
  or date-picker widgets;
- clicks Next, Continue, Pay, Confirm, or Submit;
- submits a form;
- advances passengers automatically;
- sends passenger data to a server.

## If something does not work

**No header profile is active**

Return to Excel, select the header cells, and press `Ctrl+Alt+H`.

**The copied row has the wrong number of columns**

Select the same columns used by the saved header profile. Include blank cells
inside the range when the passenger has no value.

**The field cannot be identified**

Keep the field focused, use the picker opened by Smart Paste or press
`Ctrl+Alt+P`, and choose the intended value. The larger picker is resizable and
DPI-aware; use its search box or `Ctrl+F` rather than shrinking it below the
declared minimum.

**A shortcut is unavailable**

Another application may have registered the same global shortcut. Exit that
application or choose another shortcut. Every configured shortcut must include
at least two of `Ctrl`, `Alt`, and `Shift`; the Windows key does not count.
Windows-only and single-modifier choices are rejected so routine typing and
navigation cannot trigger a global action.

**The visible window closed**

Look in the Windows notification area. Closing the window does not exit the
application.

**Smart Paste stays busy**

Do not keep pressing the shortcut. The app abandons UI Automation focus/write
work that has not begun within three seconds, but once Windows has started an
exact focus or value update it waits rather than risk a late write after a
timeout message. If the browser accessibility provider remains hung, end and
restart Smart COPY/PASTE; use Windows Task Manager if tray Exit cannot finish.
Then copy the synthetic/passenger rows again and verify the active passenger
before continuing.

## End of work

Use **Clear All Temporary Data**, then **Exit** from the tray. Passenger values
are not restored when the application starts again.
