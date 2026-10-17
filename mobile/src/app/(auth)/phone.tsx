import { router } from 'expo-router';
import { useState } from 'react';

import { DEMO_OTP_CHALLENGE, isDemoPassengerPhone } from '@/core/demo/demo-credentials';
import { isDemoMode } from '@/core/demo/demo-mode';
import { PrimaryButton } from '@/design/components/primary-button';
import { TextField } from '@/design/components/text-field';
import { requestOtp } from '@/features/auth/api/auth-api';
import { useAuthFlowStore } from '@/features/auth/state/auth-flow-store';
import { AuthError, authErrorMessage } from '@/features/auth/ui/auth-error';
import { AuthShell } from '@/features/auth/ui/auth-shell';

export default function PhoneScreen() {
  const demoMode = isDemoMode();
  const [phone, setPhone] = useState(useAuthFlowStore.getState().phoneNumber);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    const normalizedInput = phone.trim();
    if (demoMode ? normalizedInput.length === 0 : !/^\+?[0-9 ()-]{8,24}$/.test(normalizedInput)) {
      setError('Enter the mobile number used for your trip, including country code.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      if (demoMode) {
        if (!isDemoPassengerPhone(normalizedInput)) {
          setError('Use the demo passenger number +919876543219.');
          return;
        }
        useAuthFlowStore.getState().setPhoneNumber(normalizedInput);
        useAuthFlowStore.getState().setChallenge({ challengeId: DEMO_OTP_CHALLENGE, expiresInSeconds: 3600, resendAfterSeconds: 0 });
        router.push('/(auth)/otp');
        return;
      }
      const result = await requestOtp(normalizedInput);
      useAuthFlowStore.getState().setPhoneNumber(normalizedInput);
      useAuthFlowStore.getState().setChallenge({
        challengeId: result.challenge_id,
        expiresInSeconds: result.expires_in_seconds,
        resendAfterSeconds: result.resend_after_seconds,
      });
      router.push('/(auth)/otp');
    } catch (caught) {
      setError(authErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell
      eyebrow="Passenger access"
      title={demoMode ? 'Open the passenger demo.' : 'Let’s find your trip.'}
      description={demoMode
        ? 'Use +919876543219, then enter the demo code 123456. No WhatsApp message or internet connection is needed.'
        : 'Use the WhatsApp number you entered when submitting your details through your trip’s collection link.'}>
      <TextField
        testID="passenger-phone-input"
        label="Mobile number"
        placeholder={demoMode ? '+919876543219' : '+91 98765 43210'}
        keyboardType="phone-pad"
        textContentType="telephoneNumber"
        autoComplete="tel"
        value={phone}
        onChangeText={setPhone}
        maxLength={32}
        returnKeyType="done"
        onSubmitEditing={() => void submit()}
      />
      <AuthError message={error} />
      <PrimaryButton
        testID="passenger-send-otp"
        label={demoMode ? 'Continue to demo code' : 'Send verification code'}
        loading={loading}
        onPress={() => void submit()}
      />
    </AuthShell>
  );
}
