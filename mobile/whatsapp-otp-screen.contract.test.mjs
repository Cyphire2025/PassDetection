import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const otpScreen = readFileSync(new URL('./src/app/(auth)/otp.tsx', import.meta.url), 'utf8');

test('WhatsApp OTP screen has no SMS-specific autofill contract', () => {
  assert.match(otpScreen, /Check WhatsApp\./);
  assert.match(otpScreen, /6-digit code sent to the WhatsApp number/);
  assert.match(otpScreen, /Send another WhatsApp code/);
  assert.doesNotMatch(otpScreen, /sms-otp/);
});
