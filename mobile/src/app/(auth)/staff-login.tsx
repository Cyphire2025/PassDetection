import { router } from 'expo-router';
import { useState } from 'react';

import { activateDemoSession, activateSession } from '@/core/auth/session-service';
import { demoStaffRole } from '@/core/demo/demo-credentials';
import { isDemoMode } from '@/core/demo/demo-mode';
import { PrimaryButton } from '@/design/components/primary-button';
import { TextField } from '@/design/components/text-field';
import { credentialLogin } from '@/features/auth/api/auth-api';
import { AuthError, authErrorMessage } from '@/features/auth/ui/auth-error';
import { AuthShell } from '@/features/auth/ui/auth-shell';

export default function StaffLoginScreen() {
  const demoMode = isDemoMode();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    if (demoMode ? !email.trim() || !password : !email.includes('@') || password.length < 8) {
      setError('Enter your account email and password.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      if (demoMode) {
        const role = demoStaffRole(email, password);
        if (!role) {
          setError('The demo email or password is incorrect. Use the demo account shown below.');
          return;
        }
        await activateDemoSession(role);
        router.replace('/');
      } else {
        await activateSession(await credentialLogin(email.trim(), password));
        router.replace('/(auth)/prepare');
      }
    } catch (caught) {
      setError(authErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell
      eyebrow="Trip operations"
      title={demoMode ? 'Sign in to the demo.' : 'Sign in to your assigned groups.'}
      description={demoMode
        ? 'Coordinator: coordinator@gmail.com · Client Manager: clientmanager@gmail.com · Password for both: Test@12345. This demo works offline with sample data.'
        : 'This sign-in is only for Client Managers and Coordinators. Dashboard staff continue to use the web dashboard.'}>
      <TextField
        testID="staff-email-input"
        label="Email"
        keyboardType="email-address"
        textContentType="username"
        autoComplete="email"
        autoCapitalize="none"
        value={email}
        onChangeText={setEmail}
        maxLength={254}
      />
      <TextField
        testID="staff-password-input"
        label="Password"
        secureTextEntry
        showPasswordToggle
        textContentType="password"
        autoComplete="current-password"
        value={password}
        onChangeText={setPassword}
        maxLength={256}
        returnKeyType="done"
        onSubmitEditing={() => void submit()}
      />
      <AuthError message={error} />
      <PrimaryButton
        testID="staff-sign-in"
        label="Sign in"
        loading={loading}
        onPress={() => void submit()}
      />
    </AuthShell>
  );
}
