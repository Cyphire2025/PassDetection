import { Redirect, router } from 'expo-router';
import { useEffect, useState } from 'react';

import { activateDemoSession, activateSession } from '@/core/auth/session-service';
import { isDemoMode } from '@/core/demo/demo-mode';
import { isDemoPassengerOtp, DEMO_OTP_CHALLENGE } from '@/core/demo/demo-credentials';
import { PrimaryButton } from '@/design/components/primary-button';
import { requestOtp, verifyOtp } from '@/features/auth/api/auth-api';
import { useAuthFlowStore } from '@/features/auth/state/auth-flow-store';
import { AuthError, authErrorMessage } from '@/features/auth/ui/auth-error';
import { AuthShell } from '@/features/auth/ui/auth-shell';
import { CountdownProgress } from '@/features/auth/ui/countdown-progress';
import { OtpCodeInput } from '@/features/auth/ui/otp-code-input';
import { isTripAvailability, TripAvailabilityNotice, type TripAvailability } from '@/features/auth/ui/trip-availability-notice';

export default function OtpScreen() {
  const demoMode = isDemoMode();
  const flow = useAuthFlowStore();
  const [code, setCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [availability, setAvailability] = useState<TripAvailability | null>(null);
  const [resendSeconds, setResendSeconds] = useState(flow.resendAfterSeconds);

  useEffect(() => {
    const timer = setInterval(() => {
      const availableAt = useAuthFlowStore.getState().resendAvailableAt;
      setResendSeconds(availableAt ? Math.max(0, Math.ceil((availableAt - Date.now()) / 1000)) : 0);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  if (!flow.challengeId) return <Redirect href="/(auth)/phone" />;
  if (availability) return <TripAvailabilityNotice status={availability} onBack={() => {
    flow.reset();
    router.replace('/(auth)/phone');
  }} />;

  async function submit() {
    if (!/^\d{6}$/.test(code)) {
      setError(demoMode ? 'Enter all six digits of the demo code: 123456.' : 'Enter the 6-digit verification code from WhatsApp.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      if (demoMode) {
        if (!isDemoPassengerOtp(flow.challengeId, flow.phoneNumber, code)) {
          setError('The demo verification code is 123456.');
          return;
        }
        await activateDemoSession('passenger');
        flow.reset();
        router.replace('/');
        return;
      }
      const result = await verifyOtp(flow.challengeId!, code, flow.phoneNumber);
      if (isTripAvailability(result.status)) {
        setAvailability(result.status);
        setCode('');
        return;
      }
      if (result.status === 'authenticated' && result.tokens) {
        await activateSession(result.tokens);
        flow.reset();
        router.replace('/(auth)/prepare');
        return;
      }
      flow.setClaims(result.claims);
      router.push('/(auth)/claim');
    } catch (caught) {
      setError(authErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  async function resend() {
    if (resendSeconds > 0) return;
    setLoading(true);
    setError(null);
    try {
      if (demoMode) {
        flow.setChallenge({ challengeId: DEMO_OTP_CHALLENGE, expiresInSeconds: 3600, resendAfterSeconds: 0 });
        setResendSeconds(0);
        setCode('');
        return;
      }
      const result = await requestOtp(flow.phoneNumber);
      flow.setChallenge({
        challengeId: result.challenge_id,
        expiresInSeconds: result.expires_in_seconds,
        resendAfterSeconds: result.resend_after_seconds,
      });
      setResendSeconds(result.resend_after_seconds);
      setCode('');
    } catch (caught) {
      setError(authErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell
      eyebrow="Verification"
      title={demoMode ? 'Enter the demo code.' : 'Check WhatsApp.'}
      description={demoMode ? 'Enter 123456 to open the sample passenger trip. This reusable code is checked on your device.' : 'If this number was submitted through your trip’s collection link, a 6-digit code will arrive on WhatsApp. After verification, we’ll check whether your trip is ready to open.'}>
      <OtpCodeInput
        value={code}
        disabled={loading}
        onChange={setCode}
      />
      <AuthError message={error} />
      <PrimaryButton testID="passenger-verify-otp" label="Verify" loading={loading} onPress={() => void submit()} />
      {resendSeconds > 0 ? (
        <CountdownProgress remaining={resendSeconds} total={Math.max(1, flow.resendAfterSeconds)} />
      ) : null}
      <PrimaryButton
        label={demoMode ? 'Reset demo code entry' : resendSeconds ? `Send another code in ${resendSeconds}s` : 'Send another WhatsApp code'}
        tone="secondary"
        disabled={resendSeconds > 0}
        onPress={() => void resend()}
      />
    </AuthShell>
  );
}
