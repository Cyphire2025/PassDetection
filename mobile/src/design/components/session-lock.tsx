import * as LocalAuthentication from 'expo-local-authentication';
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { logoutSession } from '@/core/auth/session-service';
import { useSessionStore } from '@/core/auth/session-store';
import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { colors, spacing } from '@/design/theme';

export function SessionLock() {
  const unlock = useSessionStore((state) => state.unlock);
  const [message, setMessage] = useState('Unlock to continue to your trip.');
  const [authenticating, setAuthenticating] = useState(false);

  async function authenticate() {
    setAuthenticating(true);
    try {
      const result = await LocalAuthentication.authenticateAsync({
        promptMessage: 'Unlock Group Companion',
        cancelLabel: 'Cancel',
        disableDeviceFallback: false,
      });
      if (result.success) unlock();
      else setMessage('Your trip stayed locked. Try again when you are ready.');
    } finally {
      setAuthenticating(false);
    }
  }

  return (
    <Screen scroll={false} contentStyle={styles.content}>
      <GlassCard style={styles.card}>
        <View style={styles.lockMark} accessibilityElementsHidden>
          <Text style={styles.lockGlyph}>●</Text>
        </View>
        <Text accessibilityRole="header" style={styles.title}>
          Trip locked
        </Text>
        <Text style={styles.message}>{message}</Text>
        <PrimaryButton label="Unlock" loading={authenticating} onPress={() => void authenticate()} />
        <PrimaryButton label="Sign out and clear this device" tone="secondary" onPress={() => void logoutSession()} />
      </GlassCard>
    </Screen>
  );
}

const styles = StyleSheet.create({
  content: { justifyContent: 'center' },
  card: { gap: spacing.lg },
  lockMark: {
    width: 56,
    height: 56,
    borderRadius: 28,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.greenSoft,
  },
  lockGlyph: { color: colors.greenDeep, fontSize: 24 },
  title: { color: colors.ink, fontSize: 28, fontWeight: '800' },
  message: { color: colors.inkMuted, fontSize: 16, lineHeight: 23 },
});
