import { Redirect, router } from 'expo-router';
import { useState } from 'react';

import { activateSession } from '@/core/auth/session-service';
import { useSessionStore } from '@/core/auth/session-store';
import { PrimaryButton } from '@/design/components/primary-button';
import { TextField } from '@/design/components/text-field';
import { changeForcedPassword } from '@/features/auth/api/auth-api';
import { AuthError, authErrorMessage } from '@/features/auth/ui/auth-error';
import { AuthShell } from '@/features/auth/ui/auth-shell';

export default function ChangePasswordScreen() {
  const session = useSessionStore((state) => state.session);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!session) return <Redirect href="/(auth)/welcome" />;
  if (!session.principal.forcePasswordChange) return <Redirect href="/" />;

  async function submit() {
    if (newPassword.length < 12) {
      setError('Use at least 12 characters for your new password.');
      return;
    }
    if (newPassword !== confirmation) {
      setError('The new passwords do not match.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await activateSession(await changeForcedPassword(currentPassword, newPassword));
      router.replace('/');
    } catch (caught) {
      setError(authErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell
      eyebrow="Account activation"
      title="Choose a private password."
      description="Your temporary password can only open this activation screen. Trip information remains locked until it is changed.">
      <TextField
        label="Temporary or current password"
        secureTextEntry
        textContentType="password"
        value={currentPassword}
        onChangeText={setCurrentPassword}
        maxLength={256}
      />
      <TextField
        label="New password"
        secureTextEntry
        textContentType="newPassword"
        autoComplete="new-password"
        value={newPassword}
        onChangeText={setNewPassword}
        maxLength={256}
      />
      <TextField
        label="Confirm new password"
        secureTextEntry
        textContentType="newPassword"
        value={confirmation}
        onChangeText={setConfirmation}
        maxLength={256}
        returnKeyType="done"
        onSubmitEditing={() => void submit()}
      />
      <AuthError message={error} />
      <PrimaryButton label="Change password and continue" loading={loading} onPress={() => void submit()} />
    </AuthShell>
  );
}
