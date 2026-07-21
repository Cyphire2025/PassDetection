# Security Controls

This document records implemented V2 control requirements. It is not a
substitute for the separately maintained project threat model.

## Local-only processing

- Passenger parsing, matching, selection, and paste occur on the local Windows
  computer.
- The runtime has no analytics, telemetry, crash-upload, AI, OCR, cloud API, or
  update-check dependency.
- The offline fixture has no external scripts, fonts, images, or network calls.
- Internet access is needed only for optional developer SDK installation and
  NuGet restore.

## Passenger-data lifetime

- Active passenger collections are memory-only.
- Confirmed target-field mappings are bounded process-memory only and contain a
  hashed exact target signature plus canonical field ID, never a passenger
  value.
- Application restart begins without an active passenger.
- Clear-one, clear-all, Windows lock, sign-out, and application Exit are
  sensitive-data cleanup boundaries.
- Clear All, Windows lock/sign-out, inactivity cleanup, Exit, and restart clear
  runtime target mappings. Clear-one preserves mappings only when another
  passenger remains; removing the only or final passenger clears mappings so
  they cannot exist without an active session.
- Persisted header profiles contain header definitions, not passenger rows.

Managed-memory clearing reduces exposure but cannot prove immediate physical
RAM erasure. The process minimizes duplicate strings and retains values only
for the active session.

## Header-profile protection

- The raw workbook path is not stored or logged.
- A user-keyed HMAC derives opaque workbook and worksheet identity keys.
- Windows current-user data protection protects the random HMAC secret.
- `settings.json`, including its non-passenger header labels, is not encrypted.
- Another Windows user cannot transparently decrypt the profile.
- Corrupt, tampered, unknown-version, or undecryptable data fails closed.
- Profile selection never falls back to column-count guessing.

## Clipboard controls

- Exact Excel inspection reads the selected cells without using the clipboard.
- Clipboard-based source acquisition is offered only for a non-Excel foreground
  source, exact-access unavailable, inspection timeout, or foreground
  Excel-instance mismatch. It requires a warning, affirmative confirmation,
  and an explicitly selected header profile.
- No selection, multi-area selection, oversized selection, merged cells,
  displayed `####`, and unknown Excel failures reject without a fallback
  prompt.
- That fallback copies only the bounded tabular source selection long enough
  to parse it. The app warns that Windows or third-party clipboard history may
  retain the source application's copy.
- The clipboard sequence is recorded for the app-requested selection and
  rechecked immediately after the text read. Any change aborts before parsing
  or session mutation and discards the read text.
- Clipboard restoration uses the same ownership guard. A newer third-party
  clipboard update always wins; otherwise the prior supported text formats are
  restored or the app-owned selection is cleared.
- Browser-field insertion uses exact UI Automation `ValuePattern` and never
  places a passenger value on the clipboard.
- A failed browser insertion never escalates into clipboard access.

Users should avoid the optional source-acquisition fallback on systems with
unapproved third-party clipboard-history utilities because Smart COPY/PASTE
cannot control unrelated software.

## Field and form safety

- Exact deterministic evidence is required for automatic matching.
- Conflicting or insufficient evidence opens the field picker.
- A generic `Telephone number` requires first-use confirmation even when only
  one related value exists.
- Its default recommendations contain exactly available primary mobile and
  landline values. Alternate mobile, emergency phone, calling code, and
  unrelated fields are excluded unless the user explicitly selects
  **Show all copied fields**.
- Generic full-number help such as `Include country code` cannot classify the
  target as `contact.country_calling_code`; only explicit calling/dialing-code
  metadata can select that semantic.
- `Emergency`, `Previous`/`Former`/`Old`, and
  `Alternate`/`Alternative`/`Secondary` section qualifiers block the
  corresponding base/current field. Only a specialized candidate may be
  offered for confirmation; if it is absent, the target remains manual.
- The checked remember option is scoped to the exact browser process/window and
  normalized accessibility signature for this app process. It is not persisted
  and does not claim domain isolation.
- Password, file-upload, disabled, read-only, hidden, submit, and CAPTCHA-like
  controls are blocked.
- One-time password/PIN, one-time-code, verification/authentication-code,
  2FA/two-factor, MFA, TOTP, and authenticator metadata blocks text/tel controls
  before saved mappings, normal matching, or candidate ranking. The picker
  cannot override the block.
- `Country code`, `Country calling code`, and `Include country code` remain
  benign passenger metadata and are not authentication-protected.
- Native/custom dropdowns, radios, native date inputs, and date-picker widgets
  remain unsupported; text-field success is not treated as control-level
  coverage.
- One action inserts one value into one focused control.
- The app does not click buttons, submit forms, bypass validation, or advance
  workflow steps.
- A captured target handle may remain available for up to 10 minutes, but each
  insertion freshly revalidates exact element identity, browser
  process/window, focus, semantic metadata, protected/editable state, and a
  writable `ValuePattern`.
- A stale, changed, unfocused, protected, or unsupported target receives no
  value. The picker cannot bypass these checks.
- Focus/write operations that are queued or still pre-commit after three
  seconds are abandoned, and their gate prevents a later side effect.
- Once exact UI Automation `SetFocus` or `SetValue` begins, the workflow waits
  for the provider instead of returning an ambiguous timeout. Cleanup/session
  invalidation is serialized behind the in-flight commit. A provider hang is
  therefore an intentional availability tradeoff and may require restarting
  the app.

## Value-format safety

- Formatting runs only after canonical field selection and changes only the
  outgoing payload.
- Explicit uppercase/lowercase, validated unambiguous date masks, digits-only
  phone text, and explicit-prefix compact international formats are bounded
  safe cases.
- Uppercase label styling alone never transforms a value.
- Phone formatting operates on strings so leading zeroes are preserved.
- Conflicting hints, ambiguous/invalid dates, destructive country-code or
  last-digit requests, missing international prefixes, and extension-bearing
  phone values fail closed for manual review.
- Negated case, date, or phone format instructions fail closed with the source
  unchanged; negation never authorizes an inverse transformation.
- The original in-memory passenger value is never rewritten by formatting.

## Multi-passenger isolation

- Every paste reads one immutable snapshot of the active passenger.
- Passenger changes are explicit and visibly acknowledged.
- Locking prevents accidental navigation.
- No automatic next-passenger workflow exists.
- Header/profile changes cannot merge fields into an existing session.

## Input and configuration validation

- Clipboard cell counts, header uniqueness, canonical collisions, and maximum
  sizes are validated.
- UI Automation strings from Chrome, Edge, and Brave are bounded and treated as
  untrusted text.
- Configuration is data-only and cannot execute code, scripts, expressions, or
  commands.
- Unsupported versions and unexpected enum values are rejected.
- Every configurable global shortcut requires at least two of `Ctrl`, `Alt`,
  and `Shift`. The Windows key does not count; Windows-only, unmodified, and
  single-protective-modifier chords fail with `HOTKEY_CHORD_UNSAFE`.

## Logs and diagnostics

- Operational events use canonical identifiers and outcome codes.
- Passenger values, raw clipboard text, raw workbook paths, and secrets are
  forbidden in logs.
- Raw target labels, unhashed signature material, and runtime mapping hashes are
  forbidden in exported diagnostics.
- Normal UI errors omit stack traces.
- Exported diagnostics pass through `DiagnosticRedactor`.
- Release tests search diagnostics for known synthetic passport, email, and
  phone sentinels.

## Windows integration

- Daily use runs as the current user and does not require elevation.
- Installation is per-user under Local AppData.
- Protected settings and sanitized diagnostics are confined to
  `%LOCALAPPDATA%\SmartCopyPaste`.
- Start-with-Windows, when enabled, uses the current-user Run key.
- A single-instance boundary prevents two processes from owning the hotkeys or
  competing over clipboard state.
- Explicit Exit unregisters every hotkey and removes temporary state.

## Build and distribution

- Release publishing is self-contained, Windows x64, single-file, and
  untrimmed.
- Dependencies are version-pinned and restored through the .NET build process.
- Release artifacts include SHA-256 hashes and build metadata.
- `release-manifest.json` records `sourceState`, including `dirty` and
  `untracked-source`, plus `sourceSha256` and `sourceFileCount`; untracked or
  modified source is not mislabeled as a clean commit build.
- Local secrets, settings, passenger data, test results, and build caches are
  excluded from packages.

V2 executables are unsigned. SmartScreen may report **Unknown publisher**.
Users must not disable SmartScreen. Distributors should transmit the published
SHA-256 manifest through a trusted channel. Authenticode signing is required
before broadly presenting the application as a production release.

## Security verification gates

A release is blocked by:

- automatic paste into an unknown or conflicting field;
- first-use automatic paste into a generic telephone field;
- a generic telephone recommendation outside available primary mobile and
  landline values;
- classification of complete-number `Include country code` help as a
  standalone calling-code target;
- automatic base/current-field use under Emergency, Previous/Former/Old, or
  Alternate/Alternative/Secondary section context;
- reuse of a remembered choice for changed process/window/signature metadata or
  after a cleanup/restart boundary, or retention after the final passenger is
  removed;
- unsafe, implicit, destructive, or ambiguous value transformation;
- an inverse transformation inferred from a negated format instruction;
- any browser value inserted without fresh same-target, semantic, protected
  state, focus, and writable-`ValuePattern` validation;
- any browser insertion that falls back to the clipboard;
- any timed-out or cancelled pre-commit focus/write operation acting later;
- any already-started focus/write being reported as failed while its provider
  can still complete later;
- any cross-passenger value mix;
- passenger values in persistent files or diagnostics;
- an app-owned Excel fallback selection remaining on the clipboard after
  guarded cleanup;
- source acquisition accepting text after the clipboard sequence changes
  during its read;
- a clipboard fallback prompt after no-selection, multi-area, oversized,
  merged, `####`, or unknown Excel failure;
- Excel fallback restoration overwriting a newer third-party value;
- automatic submission or button activation;
- any one-time password/PIN, authentication/verification-code, 2FA, MFA, TOTP,
  or authenticator target offered by the picker or modified;
- authentication protection falsely applied to benign country-code metadata;
- acceptance or registration of a configurable shortcut without two of
  Ctrl/Alt/Shift;
- active hotkeys after Exit; or
- restoration of passenger data after restart.
