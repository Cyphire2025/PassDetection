import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';

import { activateSession } from '@/core/auth/session-service';
import { PrimaryButton } from '@/design/components/primary-button';
import { TextField } from '@/design/components/text-field';
import { activateInvitation } from '@/features/auth/api/auth-api';
import { AuthError, authErrorMessage } from '@/features/auth/ui/auth-error';
import { AuthShell } from '@/features/auth/ui/auth-shell';

export default function InvitationActivationScreen() {
  const params = useLocalSearchParams<{ token?: string | string[] }>();
  const activationToken = typeof params.token === 'string' && params.token.length >= 32 && params.token.length <= 512
    ? params.token
    : null;
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (!activationToken) {
      setError('This activation link is invalid or has expired.');
      return;
    }
    if (password.length < 12) {
      setError('Use at least 12 characters for your new password.');
      return;
    }
    if (password !== confirmation) {
      setError('The passwords do not match.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const tokens = await activateInvitation(activationToken, password);
      await activateSession(tokens);
      router.replace('/(auth)/prepare');
    } catch (caught) {
      setError(authErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell
      eyebrow="Secure invitation"
      title="Activate your account."
      description="Choose a private password. The invitation is exchanged once and is never stored on this device.">
      <TextField
        label="New password"
        value={password}
        onChangeText={setPassword}
        secureTextEntry
        textContentType="newPassword"
        autoComplete="new-password"
        maxLength={256}
      />
      <TextField
        label="Confirm new password"
        value={confirmation}
        onChangeText={setConfirmation}
        secureTextEntry
        textContentType="newPassword"
        maxLength={256}
        returnKeyType="done"
        onSubmitEditing={() => void submit()}
      />
      <AuthError message={!activationToken ? 'This activation link is invalid or has expired.' : error} />
      <PrimaryButton label="Activate and continue" loading={loading} disabled={!activationToken} onPress={() => void submit()} />
    </AuthShell>
  );
}
