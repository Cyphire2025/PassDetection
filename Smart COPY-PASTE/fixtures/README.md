# Offline Browser Fixture

`browser-form.html` is a dependency-free page for manually validating V2
Windows UI Automation inspection and exact `ValuePattern` browser writes.
Browser insertion never uses the clipboard; the separate clipboard-based
source-acquisition fallback is only for explicitly confirmed tabular input when
the source is not Excel or Excel inspection is unavailable, times out, or
targets a different foreground Excel instance. No-selection, multi-area,
oversized, merged, displayed-`####`, and unknown Excel failures reject without
a prompt. A clipboard sequence change during the read aborts before import.

`v2-regression-form.html` is the screenshot-derived V2 fixture for decorated
Vietnam-form labels, case and punctuation normalization, phone-family
candidate narrowing, explicit value-format hints, runtime-only learning, and
materially ambiguous identifiers.

Start the local server from the project directory:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-fixture.ps1
```

Open:

- [Chrome, Edge, or Brave fixture URL](http://localhost:8765/browser-form.html)
- [V2 regression fixture URL](http://localhost:8765/v2-regression-form.html)

The fixture includes:

- standard labels and stable IDs;
- ARIA-only identification;
- weak and placeholder-only identifiers;
- conflicting passport/application metadata;
- passport versus visa and national-ID distinctions;
- unknown fields for the picker;
- protected password, file, disabled, read-only, hidden, CAPTCHA-like, one-time
  password/PIN, 2FA/two-factor, MFA, authentication, and authenticator-code
  text/tel controls whose picker cannot override the block;
- a field inserted dynamically after page load;
- future-control examples for native select and contenteditable;
- input/change/blur event monitoring; and
- a visible form-submit counter.

The V2 fixture adds:

- `Surname (Last name)`, `Middle and given name (First name)*`, and other
  supplied Vietnam-form label shapes;
- mixed-case and punctuation/required-marker variants;
- exact mobile, landline, alternate, emergency, and calling-code fields;
- a generic Telephone/Phone scenario that always requires first-use
  confirmation and recommends exactly the available primary mobile and
  landline fields;
- generic/full-number phone helper text such as `Include country code`, which
  must not turn the target into a standalone calling-code field and must not be
  mistaken for authentication-code metadata;
- isolation of emergency-phone and calling-code values from a generic
  full-phone-number picker;
- explicit uppercase, lowercase, date-mask, and digits-only format hints plus a
  control proving that uppercase label styling is not a transform request and
  a negated format instruction that must fail closed;
- a native dropdown and native date input that remain explicit
  unsupported/manual V2 cases;
- supporting section-group scenarios showing that Emergency,
  Previous/Former/Old, and Alternate/Secondary qualifiers block base fields and
  narrow to specialized candidates or manual confirmation without changing the
  frozen 34 machine-case IDs;
- checked runtime-only learning controls for unchanged, changed-identifier, and
  changed/conflicting UI Automation signatures; the second unchanged-signature
  action may auto-resolve; clearing one passenger preserves the mapping only
  while another remains, and clearing the final passenger or restarting
  forgets it;
- passport/application and generic ID/number ambiguity controls; and
- machine-readable `data-expected-*` attributes plus
  `window.smartCopyPasteV2Fixture.getCases()` for later browser automation.

The event monitor records event type, field identity, and value length. It does
not record the value itself.

The fixture prevents real form navigation. Its submit button increments the
visible counter after preventing the browser's submit action. During normal
Smart Paste acceptance the counter must remain zero.
