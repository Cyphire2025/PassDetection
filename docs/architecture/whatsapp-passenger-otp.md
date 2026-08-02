# WhatsApp passenger OTP setup

The GC App passenger login uses the existing mobile challenge service and the
existing Meta WhatsApp Cloud API account. WhatsApp is only the delivery adapter:
the backend still owns code generation, keyed hashing, expiry, attempt limits,
resend cooldowns, abuse limits, passenger matching, and session issuance. There
is no SMS dependency and no OTP is written to application logs.

## Meta authentication template

Create or finish the template in WhatsApp Manager with these values:

| Meta field | Value |
| --- | --- |
| Template name | `verify_code_1` (or the exact approved name, then use that exact value in the environment) |
| Category | Authentication |
| Use case | Verification / Identity verification / Verify user |
| Language | English (US), with API code `en_US`, unless another translation is approved |
| Delivery | **Copy the code** for the initial release |
| Zero-tap terms | Not applicable for the initial copy-code template |
| Android package name | Not required for copy-code |
| App Signature Hash | Not required for copy-code |
| Add mobile number | Leave off unless product/legal review explicitly requires it |
| Add safety tips | Enable |
| Add code expiration | Enable and set to 5 minutes |
| Custom message validity period | Enable and set to 5 minutes |

The current React Native app does not yet implement Meta's native WhatsApp
authentication handshake/receiver. Selecting Zero-tap now would therefore create
a template whose primary experience the app cannot claim to support. Use Copy the
code: passengers receive the same six-digit code and paste or type it into the
existing OTP screen on both Android and iOS.

### Deferred one-tap / zero-tap upgrade

Only switch the approved template after the native Android handshake has been
implemented and tested in the production-signed application. At that point:

- choose One-tap autofill or Zero-tap autofill and accept the applicable terms;
- enter Android package name `com.globalconnects.groupcompanion`;
- enter the 11-character App Signature Hash generated from the certificate that
  signs the APK installed on the passenger's device;
- for Google Play App Signing, use the Play app-signing certificate, not the
  upload certificate;
- never use the repository debug keystore hash; and
- if directly distributed and Play-signed builds use different certificates,
  add each real production setup separately (Meta permits up to five apps).

The backend send payload remains the same. The native handshake and a controlled
physical-device verification are separate acceptance requirements; provider
fallback behavior is not a substitute for implementing them.

Meta fixes the authentication message body. The backend supplies the same
six-digit code to the body variable and the first OTP button variable:

```json
{
  "name": "verify_code_1",
  "language": {"code": "en_US"},
  "components": [
    {
      "type": "body",
      "parameters": [{"type": "text", "text": "<six-digit-code>"}]
    },
    {
      "type": "button",
      "sub_type": "url",
      "index": "0",
      "parameters": [{"type": "text", "text": "<same-six-digit-code>"}]
    }
  ]
}
```

This follows Meta's authentication-template contract. Template creation and the
general Cloud API transport are documented in Meta's official WhatsApp Business
Platform collection:

- <https://www.postman.com/meta/whatsapp-business-platform/request/6vkv46u/create-authentication-template-w-otp-copy-code-button>
- <https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api>

## Backend environment

Keep the provider disabled until the template shows `APPROVED`. Then configure:

```dotenv
MOBILE_OTP_PROVIDER=whatsapp
MOBILE_OTP_TTL_SECONDS=300
MOBILE_OTP_DELIVERY_TIMEOUT_SECONDS=10
MOBILE_OTP_RESEND_COOLDOWN_SECONDS=60
MOBILE_OTP_MAX_ATTEMPTS=5
MOBILE_OTP_PHONE_LIMIT_PER_HOUR=6
MOBILE_OTP_IP_LIMIT_PER_HOUR=30
MOBILE_OTP_REQUIRE_REDIS=true

WHATSAPP_ACCESS_TOKEN=<system-user token with whatsapp_business_messaging>
WHATSAPP_PHONE_NUMBER_ID=<Meta phone number ID, not the visible phone number>
WHATSAPP_API_VERSION=v25.0
WHATSAPP_OTP_TEMPLATE_NAME=verify_code_1
WHATSAPP_OTP_TEMPLATE_LANGUAGE=en_US
```

`WHATSAPP_ACCESS_TOKEN` is a secret and must be injected through the deployment
secret store. Do not place it in source control or paste it into support logs.
The API process fails configuration validation if WhatsApp OTP is selected while
the access token, phone-number ID, or authentication-template name is missing.

`MOBILE_OTP_DEVELOPMENT_CODE` is not used by the WhatsApp provider and should be
unset in production. Redis remains mandatory in production so OTP abuse limits
fail closed if the limiter is unavailable.

## Activation and verification

1. Submit the Meta template and wait for `APPROVED` for the exact language.
2. Keep the initial template on Copy the code; package name and signature hash
   are not required for this mode.
3. Deploy the backend with `MOBILE_OTP_PROVIDER=disabled` first.
4. Validate configuration and migrations, then set the provider to `whatsapp`
   and recreate the API service.
5. Send one controlled verification request to a dedicated test passenger that
   belongs to an explicitly GC App-enabled group.
6. Confirm delivery, manual code entry, expiry, cooldown, wrong-code limits,
   neutral responses for unknown phones, and copy-code behavior on Android and
   iOS.
7. Confirm logs and audit metadata contain only provider/error codes and opaque
   challenge IDs, never phone numbers or OTP values.

Rollback is configuration-only: set `MOBILE_OTP_PROVIDER=disabled` and recreate
the API service. Existing passenger, group, broadcast, and document data is not
modified.
