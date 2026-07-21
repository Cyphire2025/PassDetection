# Smart COPY/PASTE

Smart COPY/PASTE is a local-first Windows tray application for copying passenger
rows from Microsoft Excel once and pasting the correct value into a focused
browser field in any order.

The product name contains `/`, but Windows does not allow `/` inside one folder
name. The source directory is therefore named `Smart COPY-PASTE`.

V2 is deliberately deterministic. It uses configured aliases, bounded Windows
UI Automation metadata, ranked field recommendations, and an explicit picker.
It does not use AI, OCR, cloud processing, a browser extension, or automatic
full-form completion.

## Employee workflow

1. In a saved Excel workbook, select the header cells once and press
   `Ctrl+Alt+H`.
2. Select one or more passenger rows without the header and press `Ctrl+Alt+C`.
3. In Chrome, Microsoft Edge, or Brave, focus a form field and press
   `Ctrl+Alt+V`.
4. If the field cannot be identified safely, press `Ctrl+Alt+P` and choose the
   intended passenger field.
5. Use the tray menu or passenger hotkeys to switch, lock, pause, or clear the
   active passenger.

See [Employee quick start](docs/EMPLOYEE_QUICK_START.md) for the complete
workflow and safety guidance.

## V2 behavior

- Case, approved punctuation, `(required)`, and required asterisks do not stop
  an otherwise exact field match.
- A generic `Telephone number` never silently chooses the only phone value on
  first use. Its picker recommends exactly the available Mobile Number and
  Landline Number fields.
- Generic help such as `Include country code` still describes a complete phone
  number; it does not turn the target into a standalone country-calling-code
  field.
- Section qualifiers are safety-significant. `Emergency`,
  `Previous`/`Former`/`Old`, and `Alternate`/`Alternative`/`Secondary` prevent
  the corresponding base field from auto-pasting. A specialized candidate is
  offered for confirmation when available; otherwise the field remains manual.
- Authentication-secret fields are protected even when rendered as ordinary
  text or telephone inputs. One-time password/PIN, one-time-code, 2FA,
  two-factor, MFA, authentication, and authenticator-code metadata is blocked
  before matching, and the picker cannot override it. Benign `country code`
  passenger metadata is not part of this block.
- The picker option **Remember this choice for this browser window and app
  session** is checked when a safe signature is available. After confirmation,
  the same unchanged target can auto-resolve while a passenger session remains.
  Clearing one passenger preserves mappings when other passengers remain;
  clearing the only or final passenger clears them. Clear All, another cleanup
  boundary, app Exit, and restart also clear them. The mapping is never
  persisted and is not domain-aware.
- Explicit safe format hints can uppercase/lowercase text, render an
  unambiguous date mask, or remove phone separators while preserving leading
  zeroes. Visual capitalization alone never transforms a value. A recognized
  case, date, or phone format instruction that is negated fails closed for
  manual entry; the app never infers the opposite transformation.
- Clipboard source acquisition is offered only for a non-Excel source, exact
  Excel access unavailable, inspection timeout, or a foreground
  Excel-instance mismatch. Invalid or absent Excel selections, multiple areas,
  oversized ranges, merged cells, displayed `####`, and unknown Excel failures
  reject without a fallback prompt. For an allowed fallback, a clipboard
  sequence change during the read aborts the import.
- Browser insertion writes through the exact focused control's UI Automation
  `ValuePattern`. Immediately before every write, the app revalidates the same
  target, its semantic and protected/editable state, browser window, and
  focus. A captured target handle may live for up to 10 minutes, but it is
  never treated as authority without those fresh checks.
- Browser-field insertion does not use the Windows clipboard or a simulated
  `Ctrl+V` fallback. If the exact control cannot accept `ValuePattern`, nothing
  is inserted and the field must be completed manually.
- Focus/write work that has not begun its side effect is abandoned after three
  seconds and cannot run later. Once exact UI Automation `SetFocus` or
  `SetValue` has begun, the app waits for the provider instead of reporting a
  timeout that could be followed by a late write. A hung accessibility
  provider may require ending and restarting the app.
- Larger DPI-aware windows use responsive grids and working-area clamping.

Native/custom dropdowns, radios, native date inputs, date-picker widgets, and
domain-persistent website rules remain deferred until later control-specific
work or a browser extension.

## Default hotkeys

| Action | Shortcut |
| --- | --- |
| Capture and save header row | `Ctrl+Alt+H` |
| Smart Copy passenger row(s) | `Ctrl+Alt+C` |
| Smart Paste focused field | `Ctrl+Alt+V` |
| Open field picker | `Ctrl+Alt+P` |
| Next passenger | `Ctrl+Alt+Right` |
| Previous passenger | `Ctrl+Alt+Left` |
| Clear active passenger | `Ctrl+Alt+X` |
| Pause or resume | `Ctrl+Alt+Space` |

The shortcuts use Windows global-hotkey registration. Smart Paste never fires
from an unmodified `V` key or ordinary `Ctrl+V`. Every configurable shortcut
must use at least two of `Ctrl`, `Alt`, and `Shift`; the Windows key does not
count toward that minimum. A Windows-only or single-protective-modifier chord
is rejected as `HOTKEY_CHORD_UNSAFE`.

## Developer setup

The application targets .NET 10 on Windows x64. Windows 11 x64 is the primary
supported platform; Windows 10 is limited to Enterprise/LTSC editions still
supported by Microsoft and .NET 10. The scripts first use `dotnet` from `PATH`,
then fall back to:

```text
%LOCALAPPDATA%\SmartCopyPasteDev\dotnet\dotnet.exe
```

From PowerShell:

```powershell
cd "C:\Users\nipun\Desktop\PassDetection\Smart COPY-PASTE"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1
```

`bootstrap.ps1` can install the pinned SDK only when explicitly requested:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1 -InstallSdk
```

SDK installation and NuGet restore are development-time operations that may
need internet access. The built application performs no network calls at
runtime.

## Run locally

After a successful build:

```powershell
& .\src\SmartCopyPaste.App\bin\Release\net10.0-windows\win-x64\SmartCopyPaste.exe
```

The application starts in the Windows notification area. Closing a visible
window returns it to the tray. Only the tray menu's **Exit** action terminates
the process.

To run the headless executable smoke check:

```powershell
& .\src\SmartCopyPaste.App\bin\Release\net10.0-windows\win-x64\SmartCopyPaste.exe --self-test
```

## Build a shareable EXE

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\package.ps1
```

The package script runs restore, Release build, tests, self-contained
single-file publish, the published `--self-test`, and packaging. It creates:

```text
artifacts\release\v0.2.0\
  SmartCopyPaste-v0.2.0-win-x64.exe
  SmartCopyPaste-v0.2.0-win-x64.zip
  SHA256SUMS.txt
  release-manifest.json
```

The executable includes the .NET runtime and does not require .NET to be
installed on the recipient's computer.

The ZIP includes `EXE-SHA256.txt`; `install.ps1` validates it automatically
when both files remain together. The external `SHA256SUMS.txt` also covers the
ZIP itself.

`release-manifest.json` records the Git commit when available and the actual
source state used for the build. An untracked project is recorded as
`commit: "untracked"` with `sourceState: "untracked-source"`; a modified
tracked checkout is recorded as `sourceState: "dirty"`. The manifest also
records `sourceSha256` and `sourceFileCount` so an artifact can be tied to the
exact source-tree contents used for the build even when no clean commit
identifies them.

V2 artifacts are unsigned. Windows SmartScreen may show **Unknown publisher**.
Do not disable SmartScreen. Distribute the SHA-256 manifest through a trusted
channel and run the file only when its hash matches.

## Install or uninstall for the current Windows user

Install under `%LOCALAPPDATA%\Programs\SmartCopyPaste` and create a Start Menu
shortcut:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

Uninstall the application while preserving user configuration:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\uninstall.ps1
```

Remove user configuration as well:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\uninstall.ps1 -RemoveUserData
```

## Offline browser fixture

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-fixture.ps1
```

Then open [http://localhost:8765/browser-form.html](http://localhost:8765/browser-form.html)
in Chrome, Edge, or Brave. The page has no external dependencies and records
field events without recording entered values.

For V2 label, phone-narrowing, format-hint, ambiguity, runtime-learning, and
compact-picker checks, open
[http://localhost:8765/v2-regression-form.html](http://localhost:8765/v2-regression-form.html).
Validate its offline contract with:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-v2-fixture.ps1
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [V2 scope](docs/MVP_SCOPE.md)
- [Behavioral contracts](docs/CONTRACTS.md)
- [Security controls](docs/SECURITY_CONTROLS.md)
- [Known limitations](docs/KNOWN_LIMITATIONS.md)
- [Manual acceptance](docs/MANUAL_ACCEPTANCE.md)
- [V2 regression matrix](docs/V2_REGRESSION_MATRIX.md)
- [Release checklist](docs/RELEASE_CHECKLIST.md)
