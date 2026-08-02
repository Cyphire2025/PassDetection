import { Redirect, router } from 'expo-router';
import { useEffect, useState } from 'react';
import { StyleSheet, Text } from 'react-native';

import { activateSession } from '@/core/auth/session-service';
import { PrimaryButton } from '@/design/components/primary-button';
import { TextField } from '@/design/components/text-field';
import { colors } from '@/design/theme';
import { requestOtp, verifyOtp } from '@/features/auth/api/auth-api';
import { useAuthFlowStore } from '@/features/auth/state/auth-flow-store';
import { AuthError, authErrorMessage } from '@/features/auth/ui/auth-error';
import { AuthShell } from '@/features/auth/ui/auth-shell';

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
        router.replace('/');
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
      <TextField
        label="Verification code"
        placeholder="000000"
        keyboardType="number-pad"
        textContentType="oneTimeCode"
        value={code}
        onChangeText={(value) => setCode(value.replace(/\D/g, ''))}
        maxLength={6}
        returnKeyType="done"
        onSubmitEditing={() => void submit()}
      />
      <AuthError message={error} />
      <PrimaryButton label="Verify" loading={loading} onPress={() => void submit()} />
      <PrimaryButton
        label={resendSeconds ? `Send another code in ${resendSeconds}s` : 'Send another WhatsApp code'}
        tone="secondary"
        disabled={resendSeconds > 0}
        onPress={() => void resend()}
      />
      <Text style={styles.hint}>Codes expire quickly and stop working after repeated failed attempts.</Text>
    </AuthShell>
  );
}

const styles = StyleSheet.create({ hint: { color: colors.inkMuted, fontSize: 13, lineHeight: 19 } });
