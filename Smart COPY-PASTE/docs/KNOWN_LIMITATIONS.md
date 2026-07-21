# Known V2 Limitations

## Browser understanding

V2 has no browser extension. Windows UI Automation usually exposes an
accessible name, automation identifier, help text, and control type, but it
does not reliably expose:

- HTML `name`, `autocomplete`, or data attributes;
- the current domain or URL path;
- associated nearby text and section headings;
- cross-origin iframe content;
- closed Shadow DOM;
- framework component state; or
- stable website-specific signatures.

Consequently, some Chrome, Edge, and Brave fields require the explicit picker.
The checked remember option is process-memory only and is keyed to the current
browser process, window, and exact normalized accessibility signature. It
cannot identify a domain, URL, page, or account, never persists to disk, and is
preserved when one passenger is cleared only if another passenger remains.
Clearing the only/final passenger, Clear All, cleanup boundaries, Exit, or
restart forgets it. Durable domain-specific mappings remain deferred until a
browser extension.

When UI Automation exposes a usable section heading, the matcher treats
Emergency, Previous/Former/Old, and Alternate/Alternative/Secondary qualifiers
as safety context and blocks the base/current field. Some portals do not expose
that surrounding section reliably; those fields stay ambiguous/manual rather
than receiving a guessed base value.

## Supported controls

The reliable V2 path targets standard editable text controls with a writable UI
Automation `ValuePattern`. Native selects, custom dropdowns, radio buttons,
checkboxes, native date inputs, date pickers, contenteditable regions, and
split day/month/year controls are fixture coverage or future extension points,
not V2 automation.

Password, file-upload, hidden, disabled, read-only, submit, CAPTCHA-like, and
authentication-secret controls are intentionally unsupported. The latter
includes one-time password/PIN, one-time-code, verification/authentication
code, 2FA/two-factor, MFA, TOTP, and authenticator metadata even on text/tel
inputs; the picker cannot override the block. Ordinary country-code passenger
metadata is not treated as authentication.

## Formatting

V2 preserves copied cell text unless accessible target metadata explicitly
requests a supported safe transformation. Supported cases include invariant
uppercase/lowercase, unambiguous validated date masks, digits-only phone text,
and bounded international-phone compaction when the prefix is explicit.
Leading zeroes are preserved because phone values remain strings.

V2 refuses conflicting case/date/phone instructions, ambiguous source dates,
destructive requests such as dropping a country code or keeping only the last
digits, phone extensions that would be lost, and negated format instructions.
Negation does not select an inverse transform. It does not infer formatting
from visual capitalization, split or combine names, or transform country,
nationality, or gender representations.

Generic helper text such as `Include country code` describes a complete phone
number, not a separate calling-code field. Calling-code insertion requires an
explicit calling/dialing-code target.

## Excel source identity

The safest header-once path requires a saved Microsoft Excel workbook and
worksheet identity. An unsaved workbook, protected automation environment, or
non-Excel spreadsheet program may require explicit profile selection.

Moving or renaming a workbook intentionally produces a new fingerprint. This
avoids unsafe cross-file reuse but may require capturing its headers again.

## Clipboard interoperability

Browser-field insertion does not use the clipboard and has no simulated
`Ctrl+V` fallback. It writes only through the exact focused control's
`ValuePattern` after fresh target, semantic, focus, and protected-state
validation. A captured target handle expires after at most 10 minutes and is
still revalidated on every use.

The user-confirmed source-acquisition fallback is available only for a
non-Excel foreground source, exact Excel access unavailable, inspection
timeout, or foreground Excel-instance mismatch. A missing selection, multiple
areas, an oversized range, merged cells, displayed `####`, or an unknown Excel
failure must be corrected in Excel and never produces a fallback prompt.

For an allowed fallback, the app sends `Ctrl+C` to the still-foreground source
window, reads bounded tabular text, and rechecks the clipboard sequence after
the read. A mismatch discards the text and aborts before import. Cleanup
restores or clears only while the app still owns that sequence. Windows and
third-party clipboard managers operate outside the application's control and
may retain that source copy despite cleanup.

Some portals do not expose a writable UI Automation text value or reject
programmatic updates. V2 reports the failure, leaves the employee in control,
and does not bypass the portal.

## UI Automation provider availability

Queued or pre-commit focus/write work is abandoned after three seconds and is
gated so it cannot act later. Once exact UI Automation `SetFocus` or
`ValuePattern.SetValue` begins, however, Windows provides no safe cancellation
that can prove the provider will not complete afterward. Smart COPY/PASTE
therefore waits instead of reporting a timeout followed by a possible late
focus change or value write.

A hung browser accessibility provider can leave that workflow waiting and
block later UI Automation work. End and restart Smart COPY/PASTE before
continuing; if normal tray Exit cannot complete, end the process with Windows
Task Manager. Temporary passenger data is memory-only and must be copied again
after restart.

## Persistence

Passenger rows are never restored after application restart. Optional
encrypted passenger persistence is outside V2.

Header profiles and settings are current-Windows-user data. They do not roam
between computers or Windows accounts.

They are stored under `%LOCALAPPDATA%\SmartCopyPaste`. Default uninstall
preserves this directory; `uninstall.ps1 -RemoveUserData` deletes it only after
explicit confirmation.

## Platform and release

- Windows 11 x64 is the primary supported platform.
- Windows 10 x64 is limited to Enterprise/LTSC editions that remain supported
  by both Microsoft and .NET 10; ordinary Windows 10 22H2 is not a supported
  V2 target.
- Chrome, Microsoft Edge, and Brave are the supported Chromium browsers.
- No Firefox, macOS, Linux, or ARM64 build.
- No browser extension or Native Messaging host.
- No automatic updater or enterprise deployment package.
- No MSI/MSIX installer in V2; installation is a per-user PowerShell copy.
- The V2 executable is unsigned and may show a SmartScreen
  **Unknown publisher** warning.

Do not disable Windows security features to run the app. Verify the artifact's
SHA-256 hash and obtain it from the trusted project distributor.

## Display boundary

V2 uses larger DPI-aware windows, fill-width grids, and working-area clamping.
On unusually small work areas or extreme scaling, a window may become smaller
than its scaled logical minimum and use vertical scrolling so actions stay
reachable. Physical multi-monitor and 100%, 125%, 150%, and 200% scale checks
remain release gates.

## Product boundary

V2 is an employee-controlled, one-field-at-a-time assistant. It does not:

- complete a whole form;
- click navigation or payment controls;
- submit applications;
- bypass CAPTCHA or portal security;
- automatically advance passengers; or
- infer missing passenger data.
