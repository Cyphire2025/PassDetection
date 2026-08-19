import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { activateDemoSession, activateSession } from '@/core/auth/session-service';
import type { MobileRole } from '@/core/auth/types';
import { isDemoMode } from '@/core/demo/demo-mode';
import { PrimaryButton } from '@/design/components/primary-button';
import { TextField } from '@/design/components/text-field';
import { colors, radii, spacing } from '@/design/theme';
import { credentialLogin } from '@/features/auth/api/auth-api';
import { AuthError, authErrorMessage } from '@/features/auth/ui/auth-error';
import { AuthShell } from '@/features/auth/ui/auth-shell';

export default function StaffLoginScreen() {
  const demoMode = isDemoMode();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [demoRole, setDemoRole] = useState<Exclude<MobileRole, 'passenger'>>('client_manager');
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
        await activateDemoSession(demoRole);
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
      title={demoMode ? 'Choose an operations demo.' : 'Sign in to your assigned groups.'}
      description={demoMode
        ? 'Enter any email and password, then choose the role you want to inspect. No credentials leave this emulator.'
        : 'This sign-in is only for Client Managers and Coordinators. Dashboard staff continue to use the web dashboard.'}>
      {demoMode ? (
        <View style={styles.roleSection}>
          <Text style={styles.roleLabel}>Demo role</Text>
          <View accessibilityRole="radiogroup" style={styles.roleRow}>
            {(['client_manager', 'coordinator'] as const).map((role) => {
              const selected = role === demoRole;
              return (
                <Pressable
                  key={role}
                  accessibilityRole="radio"
                  accessibilityState={{ selected }}
                  onPress={() => setDemoRole(role)}
                  style={[styles.roleChoice, selected && styles.roleChoiceSelected]}>
                  <Text style={[styles.roleChoiceText, selected && styles.roleChoiceTextSelected]}>
                    {role === 'client_manager' ? 'Client Manager' : 'Coordinator'}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        </View>
      ) : null}
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
        label={demoMode ? `Open ${demoRole === 'client_manager' ? 'manager' : 'coordinator'} demo` : 'Sign in'}
        loading={loading}
        onPress={() => void submit()}
      />
    </AuthShell>
  );
}

const styles = StyleSheet.create({
  roleSection: { gap: spacing.sm },
  roleLabel: { color: colors.ink, fontSize: 14, fontWeight: '800' },
  roleRow: { flexDirection: 'row', gap: spacing.sm },
  roleChoice: {
    flex: 1,
    minHeight: 46,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: radii.pill,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceStrong,
    paddingHorizontal: spacing.md,
  },
  roleChoiceSelected: { borderColor: colors.green, backgroundColor: colors.greenSoft },
  roleChoiceText: { color: colors.inkMuted, fontSize: 13, fontWeight: '700' },
  roleChoiceTextSelected: { color: colors.greenDeep },
});
