import { Redirect, router } from 'expo-router';
import { useEffect, useState } from 'react';

import { activateSession } from '@/core/auth/session-service';
import { PrimaryButton } from '@/design/components/primary-button';
import { requestOtp, verifyOtp } from '@/features/auth/api/auth-api';
import { useAuthFlowStore } from '@/features/auth/state/auth-flow-store';
import { AuthError, authErrorMessage } from '@/features/auth/ui/auth-error';
import { AuthShell } from '@/features/auth/ui/auth-shell';
import { CountdownProgress } from '@/features/auth/ui/countdown-progress';
import { OtpCodeInput } from '@/features/auth/ui/otp-code-input';

export default function OtpScreen() {
  const flow = useAuthFlowStore();
  const [code, setCode] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resendSeconds, setResendSeconds] = useState(flow.resendAfterSeconds);

  useEffect(() => {
    const timer = setInterval(() => {
      const availableAt = useAuthFlowStore.getState().resendAvailableAt;
      setResendSeconds(availableAt ? Math.max(0, Math.ceil((availableAt - Date.now()) / 1000)) : 0);
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  if (!flow.challengeId) return <Redirect href="/(auth)/phone" />;

  async function submit() {
    if (!/^\d{6}$/.test(code)) {
      setError('Enter the 6-digit verification code from WhatsApp.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await verifyOtp(flow.challengeId!, code);
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
      title="Check WhatsApp."
      description="Enter the 6-digit code sent to the WhatsApp number you provided. We use the same response whether or not a trip is eligible.">
      <OtpCodeInput
        value={code}
        disabled={loading}
        onChange={setCode}
      />
      <AuthError message={error} />
      <PrimaryButton label="Verify" loading={loading} onPress={() => void submit()} />
      {resendSeconds > 0 ? (
        <CountdownProgress remaining={resendSeconds} total={Math.max(1, flow.resendAfterSeconds)} />
      ) : null}
      <PrimaryButton
        label={resendSeconds ? `Send another code in ${resendSeconds}s` : 'Send another WhatsApp code'}
        tone="secondary"
        disabled={resendSeconds > 0}
        onPress={() => void resend()}
      />
    </AuthShell>
  );
}
