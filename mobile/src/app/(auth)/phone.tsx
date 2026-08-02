import { router } from 'expo-router';
import { useState } from 'react';

import { activateDemoSession } from '@/core/auth/session-service';
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
        await activateDemoSession('passenger');
        router.replace('/');
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
        ? 'Enter any value. This isolated emulator build opens local sample data without checking a real passenger record.'
        : 'Use the mobile number already registered with your passenger or WhatsApp record.'}>
      <TextField
        label="Mobile number"
        placeholder="+91 98765 43210"
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
        label={demoMode ? 'Open passenger demo' : 'Send verification code'}
        loading={loading}
        onPress={() => void submit()}
      />
    </AuthShell>
  );
}
