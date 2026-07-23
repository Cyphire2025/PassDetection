# Android shell security decisions

- Production cleartext traffic is disabled at both manifest and network
  security configuration levels.
- Only the exact scheme, host, and effective port of the configured app URL may
  navigate inside the WebView. Cross-origin HTTPS links open in an Android
  browser; unsupported and insecure schemes are blocked.
- Production BuildConfig and the runtime policy are both locked to
  `https://tech.gctravels.com/coordinator`. Arbitrary build-property,
  environment, or script URL overrides are not supported.
- Safe Browsing is enabled. SSL errors are cancelled and shown as a native
  error; they are never bypassed.
- Mixed content, WebView file access, WebView content access, geolocation,
  multiple windows, and unsolicited JavaScript windows are disabled.
- JavaScript and DOM storage are enabled only because the trusted Next.js PWA
  requires them. There is no `addJavascriptInterface` bridge.
- Third-party cookies are disabled. Existing same-origin httpOnly
  authentication cookies continue to work.
- Web camera grants are restricted to the configured origin and to video only.
  The app does not request microphone permission.
- File chooser modes, MIME filters, returned URI schemes, and actual MIME types
  are checked. At most 20 content URIs are accepted per selection.
- Backups are disabled because WebView storage can contain authenticated and
  offline operational state.
- Release signing secrets are environment-only and never written into source
  or BuildConfig.

The separate `local` product flavor permits HTTP only for Android emulator or
loopback hostnames and has a distinct application ID. Scanner/PWA testing uses
`http://localhost` through `adb reverse`, which WebView treats as a trustworthy
loopback context. This flavor must never be sent to customers.
