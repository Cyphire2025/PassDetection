# Release Checklist

## 1. Scope and source

- [ ] Release contains the V2 tray application only; browser extensions remain
      excluded.
- [ ] Working tree changes are reviewed and unrelated repository changes are
      untouched.
- [ ] Product version is set in `SmartCopyPaste.App.csproj`.
- [ ] Dependency versions and lock files are committed.
- [ ] No real passenger values, workbook paths, credentials, or secrets exist
      in source, fixtures, tests, logs, or artifacts.
- [ ] Known limitations and unsigned-artifact disclosure are current.

## 2. Bootstrap

From the project directory:

```powershell
cd "C:\Users\nipun\Desktop\PassDetection\Smart COPY-PASTE"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

- [ ] The script resolves .NET 10 from `PATH` or
      `%LOCALAPPDATA%\SmartCopyPasteDev\dotnet\dotnet.exe`.
- [ ] `dotnet --info` reports an x64 .NET 10 SDK.
- [ ] Restore succeeds.

## 3. Build and automated tests

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test-v2-fixture.ps1
```

- [ ] Release build has zero warnings and zero errors.
- [ ] Header normalization and collision tests pass.
- [ ] Clipboard parser shape and leading-zero tests pass.
- [ ] Header fingerprint/profile isolation tests pass.
- [ ] Deterministic matching and ambiguity regression tests pass.
- [ ] Mixed-case, required-marker, punctuation, and screenshot-derived
      compound-label tests pass.
- [ ] Generic phone matching returns only deterministic available
      primary-mobile/landline recommendations.
- [ ] One generic-telephone recommendation still returns
      `RELATED_CANDIDATE_REQUIRES_CONFIRMATION`; it does not auto-paste on first
      use.
- [ ] Emergency phone and calling code remain isolated from a generic
      full-number picker.
- [ ] Generic `Include country code` help and `Mobile number with country code`
      retain complete-number intent and never select
      `contact.country_calling_code`.
- [ ] Emergency, Previous/Former/Old, and Alternate/Secondary section-context
      tests block the base field, return `SECTION_CONTEXT_CONFLICT`, and offer
      only an available specialized candidate or manual completion.
- [ ] Explicit uppercase, lowercase, date-mask, and digits-only formatting
      tests pass; label capitalization alone does not transform a value.
- [ ] Negated case, date, and phone format instructions leave the source
      unchanged, return an unsafe/manual result, and never infer an inverse
      transformation.
- [ ] Runtime picker learning is exact-signature and memory-only; changed
      metadata and restart tests pass. Clear-one preserves mappings while
      another passenger remains; clearing the only/final passenger clears them.
- [ ] Picker self-test confirms the runtime-only remember control is checked
      when an exact signature is available.
- [ ] Automatic and picker-confirmed browser writes use the exact focused
      control's writable UI Automation `ValuePattern`.
- [ ] Final insertion revalidates the same element, browser process/window,
      focus, complete semantic metadata, protected/editable state, active
      passenger, and writable `ValuePattern`.
- [ ] A captured target handle is rejected after 10 minutes and is freshly
      revalidated on every earlier use.
- [ ] UI Automation focus/write work abandoned while queued or pre-commit at
      three seconds cannot execute a delayed side effect later.
- [ ] Once exact `SetFocus` or `SetValue` begins, the workflow waits for the
      provider to return instead of reporting a timeout while a late side
      effect remains possible.
- [ ] Missing/read-only `ValuePattern` fails without simulated typing or
      browser clipboard fallback.
- [ ] Native/custom dropdown and native date-input automation are not claimed
      by the V2 text-control test suite.
- [ ] One-time password/PIN, one-time-code, verification/authentication code,
      2FA/two-factor, MFA, TOTP, and authenticator metadata block text/tel
      controls before matching; saved mapping and picker paths cannot override.
- [ ] `Country code`, `Country calling code`, and `Include country code` are not
      falsely classified as authentication metadata.
- [ ] Multi-passenger atomic-session tests pass.
- [ ] Masking and diagnostic-redaction tests pass.
- [ ] Hotkey/settings validation tests prove that every gesture requires at
      least two of Ctrl/Alt/Shift, that Windows does not count, and that
      Windows-only, unmodified, and single-modifier chords fail with
      `HOTKEY_CHORD_UNSAFE`.
- [ ] Excel fallback-policy tests allow only not-Excel,
      `EXCEL_SELECTION_UNAVAILABLE`, `EXCEL_TIMEOUT`, and
      `EXCEL_FOREGROUND_INSTANCE_MISMATCH`; every other Excel failure rejects.
- [ ] Clipboard acquisition records the copied-selection sequence, rechecks it
      after reading, and rejects zero or changed sequence values before parsing.
- [ ] Test results contain no synthetic passenger values outside intentional
      test inputs.

## 4. Security verification

- [ ] Passenger rows are memory-only and absent after restart.
- [ ] Runtime-learned picker choices contain no passenger value, are not
      persisted, are absent after restart, and cannot remain after the final
      passenger is cleared.
- [ ] Header persistence contains no raw workbook path or passenger value.
- [ ] Unknown/conflicting fields cannot auto-paste.
- [ ] Password, file, disabled, read-only, submit, CAPTCHA-like, OTP/one-time
      PIN, 2FA, MFA, authentication-code, and authenticator-code controls are
      blocked, including through the picker.
- [ ] Native date inputs are blocked as unsupported/manual.
- [ ] Automatic and picker browser insertion leave an existing clipboard
      sentinel unchanged; the picker exposes no browser clipboard-fallback
      option.
- [ ] Clipboard-based source acquisition appears only for a non-Excel source,
      exact-access unavailable, timeout, or foreground-instance mismatch, after
      an explicit warning is accepted and a named header profile is selected.
- [ ] No-selection, multi-area, oversized, merged, displayed-`####`, and unknown
      Excel failures reject without a clipboard prompt.
- [ ] Sequence-guarded source-clipboard restore or clear preserves newer
      third-party updates, the post-read sequence check aborts unstable
      acquisition before import, and the warning discloses clipboard-history
      risk.
- [ ] Diagnostics pass the passport/email/phone sentinel scan.
- [ ] Explicit Exit releases hotkeys and clears sensitive state.
- [ ] Shortcut Settings refuses a chord without two of Ctrl/Alt/Shift and keeps
      the prior valid configuration.
- [ ] Fixture submit counter stays at zero during Smart Paste testing.
- [ ] Runtime network monitoring shows no app-initiated connections.

## 5. Manual acceptance

- [ ] Complete every P0 case in
      [MANUAL_ACCEPTANCE.md](MANUAL_ACCEPTANCE.md).
- [ ] Complete every P0 row in
      [V2_REGRESSION_MATRIX.md](V2_REGRESSION_MATRIX.md).
- [ ] Repeat browser fixture cases in Chrome, Microsoft Edge, and Brave.
- [ ] Repeat the V2 fixture at 100%, 125%, 150%, and 200% Windows display
      scale, including the picker at its declared minimum size.
- [ ] Save the required picker/window screenshots with resolution, scale,
      window size, and build hash.
- [ ] Verify the screenshot-like one-phone profile still requires first-use
      confirmation and renders one Mobile Number recommendation.
- [ ] Verify the rich profile renders exactly Mobile Number and Landline Number
      as generic telephone recommendations; alternate, emergency, calling code,
      and unrelated rows appear only after explicit **Show all copied fields**.
- [ ] Verify `PHONE-03` keeps `Include country code` as complete-number intent
      and never recommends Country Calling Code; it is not authentication
      protected.
- [ ] Verify every authentication/OTP text and telephone control in the basic
      fixture remains unchanged through automatic, picker, and remembered paths.
- [ ] Verify `QUALIFIER-01` through `QUALIFIER-06` recommend only specialized
      fields when present and never fall back to base fields when absent.
- [ ] Verify negated formatting in `FORMAT-07` stays manual and does not apply
      the opposite transform.
- [ ] Verify runtime learning on the same signature, a changed AutomationId,
      changed/conflicting metadata, unchecked remember, clear-one with another
      passenger remaining, clear-final, Clear All, and application restart.
- [ ] Verify exact `ValuePattern` insertion, stale/changed/protected target
      rejection, the 10-minute handle boundary, and an unchanged clipboard
      sentinel for automatic and picker paths.
- [ ] With controlled provider evidence, verify three-second pre-commit
      abandonment cannot act later and an already-started focus/write remains
      pending until completion. Record restart recovery for a simulated
      permanent provider hang.
- [ ] Verify the separate Excel/source clipboard-acquisition warning,
      four-state eligibility allowlist, invalid-selection rejection without a
      prompt, post-read sequence-race abort, and guarded restore/clear behavior.
      Do not treat this as a browser paste path.
- [ ] Verify logical default/minimum sizes: Main 1040 x 720 / 780 x 560; Picker
      820 x 600 / 700 x 500; Header mapping 920 x 680 / 700 x 500; Shortcut
      settings 760 x 620 / 700 x 520; Diagnostics 820 x 600 / 700 x 500.
- [ ] Complete a two-passenger random-order paste without a mixed value.
- [ ] Verify close-to-tray, pause/resume, explicit Exit, and restart behavior.
- [ ] Verify Shortcut Settings rejects `Shift+V` and `Ctrl+V`, accepts an unused
      two-modifier chord, and restores the default. Retain automated evidence
      for Windows-only rejection.
- [ ] Verify Windows-lock cleanup.
- [ ] Save the sanitized evidence record.

## 6. Publish and package

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\package.ps1
```

- [ ] Publish is `Release`, `win-x64`, self-contained, single-file, and
      untrimmed.
- [ ] Published EXE passes `--self-test`.
- [ ] Versioned EXE and ZIP names match the project version.
- [ ] ZIP contains the EXE, employee quick start, known limitations, and
      install/uninstall helpers plus the EXE checksum only.
- [ ] `SHA256SUMS.txt` contains hashes for both EXE and ZIP.
- [ ] `release-manifest.json` records version, commit, runtime identifier, UTC
      build time, and signature status.
- [ ] The manifest records the actual `sourceState`: `clean` or `dirty` for a
      tracked checkout, and `untracked-source` with `commit: "untracked"` when
      the project has no tracked files.
- [ ] `sourceSha256` is a non-empty deterministic source-tree digest and
      `sourceFileCount` is the positive count of files included in that digest.
- [ ] Release evidence does not describe a dirty or untracked build as a clean
      commit build.
- [ ] No PDB, `obj`, NuGet cache, user settings, logs, or test results are in
      the ZIP.

Inspect the results:

```powershell
Get-ChildItem .\artifacts\release\v0.2.0
Get-Content .\artifacts\release\v0.2.0\SHA256SUMS.txt
Get-AuthenticodeSignature .\artifacts\release\v0.2.0\SmartCopyPaste-v0.2.0-win-x64.exe
```

## 7. Clean-user verification

- [ ] Verify the SHA-256 hash before execution.
- [ ] Run on a clean non-admin Windows 11 x64 user or Windows Sandbox.
- [ ] If Windows 10 is checked, use only an Enterprise/LTSC x64 edition still
      supported by both Microsoft and .NET 10.
- [ ] Confirm no installed .NET runtime is needed.
- [ ] Install under Local AppData and launch from the Start Menu.
- [ ] Default uninstall preserves settings.
- [ ] `uninstall.ps1 -RemoveUserData` removes settings.
- [ ] No hotkey, process, shortcut, or Run-key entry remains after uninstall.

## 8. Distribution

- [ ] V2 is labeled Windows x64 preview software.
- [ ] Recipients receive the hash through a trusted channel.
- [ ] Recipients are told the EXE is unsigned and may show
      **Unknown publisher**.
- [ ] Documentation never instructs users to disable SmartScreen or antivirus.
- [ ] Authenticode signing is required before broad production distribution.

## Release blockers

Do not release if any of these occur:

- a value is pasted into the wrong or unknown field;
- values from two passengers are mixed;
- a passenger advances without explicit action;
- passenger data is written to disk or diagnostics;
- browser insertion uses simulated typing or the clipboard instead of the
  freshly revalidated exact `ValuePattern`;
- a stale, changed, unfocused, protected, expired, or non-`ValuePattern`
  browser target receives a value;
- pre-commit work acts after its three-second abandonment;
- an already-started exact focus/write is reported as timed out while its
  provider can still complete later;
- an app-owned Excel/source acquisition selection remains on the clipboard
  after guarded cleanup;
- clipboard source text is parsed after the sequence changes during its read;
- the clipboard fallback prompt is shown for no selection, multiple areas, an
  oversized range, merged cells, displayed `####`, or an unknown Excel failure;
- Excel/source acquisition restoration overwrites a newer clipboard value;
- a form is submitted or a protected control is modified;
- an OTP/one-time PIN, verification/authentication code, 2FA, MFA, TOTP, or
  authenticator control is offered in the picker or receives a value;
- benign country-code metadata is blocked as authentication metadata;
- a generic telephone default recommendation contains alternate mobile,
  emergency phone, calling code, or any unrelated field;
- `Include country code` on a complete-number target selects or recommends the
  standalone calling-code field;
- an explicit mobile, emergency-phone, or calling-code target receives a
  cross-kind phone value;
- Emergency, Previous/Former/Old, or Alternate/Secondary section context
  auto-pastes or recommends the base/current field;
- value formatting occurs without an explicit hint, changes the stored
  passenger value, drops leading zeroes, or guesses an invalid date;
- a negated format instruction causes any automatic or inverse transformation;
- a dropdown is changed despite being outside the V2 text-control contract;
- a native date input is changed despite being outside the V2 text-control
  contract;
- a learned picker choice is reused for changed/conflicting UI Automation
  metadata, survives process restart, or remains after the final passenger is
  cleared;
- a primary action, picker column, or selectable row is clipped at a required
  DPI/minimum-size check;
- a configurable global shortcut without two of Ctrl/Alt/Shift is accepted, or
  Windows is counted toward that minimum;
- hotkeys remain registered after Exit;
- passenger rows return after restart;
- the artifact requires elevation or an installed .NET runtime;
- the artifact hash or manifest does not match the packaged files;
- the manifest omits or misstates `sourceState`, `sourceSha256`, or
  `sourceFileCount`;
- an untracked or dirty source build is represented as a clean commit build.
