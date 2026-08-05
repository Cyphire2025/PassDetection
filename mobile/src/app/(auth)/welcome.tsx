import { Redirect, router } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';

import { bootstrapApplicationSession } from '@/core/auth/application-bootstrap';
import { useSessionStore } from '@/core/auth/session-store';
import { PrimaryButton } from '@/design/components/primary-button';
import { colors, spacing } from '@/design/theme';
import { AuthShell } from '@/features/auth/ui/auth-shell';

export default function WelcomeScreen() {
  const session = useSessionStore((state) => state.session);
  const bootstrapErrorCode = useSessionStore((state) => state.bootstrapErrorCode);
  const [retrying, setRetrying] = useState(false);

  if (session) return <Redirect href="/" />;

  const retryBootstrap = async () => {
    if (retrying) return;
    setRetrying(true);
    await bootstrapApplicationSession();
    setRetrying(false);
  };

  return (
    <AuthShell
      centerContent
      showBrandLogo
      eyebrow="Group Companion"
      title="Your trip, ready when you are."
      description="Itinerary, personal QR, travel documents and important updates in one secure place.">
      {bootstrapErrorCode ? (
        <View accessibilityRole="alert" style={styles.recovery}>
          <Text style={styles.recoveryTitle}>Secure local access needs another try</Text>
          <Text style={styles.recoveryBody}>
            Your previous account data remains locked. Retry the secure session check, or sign in again below.
          </Text>
          <PrimaryButton
            disabled={retrying}
            label={retrying ? 'Checking secure session...' : 'Try secure session again'}
            tone="secondary"
            onPress={() => void retryBootstrap()}
          />
        </View>
      ) : null}
      <PrimaryButton label="Continue with phone number" onPress={() => router.push('/(auth)/phone')} />
      <PrimaryButton
        label="Client manager or coordinator"
        tone="secondary"
        onPress={() => router.push('/(auth)/staff-login')}
      />
      <Text style={styles.note}>
        Passenger document submissions continue through the secure links shared by your travel team.
      </Text>
    </AuthShell>
  );
}

const styles = StyleSheet.create({
  recovery: {
    gap: spacing.sm,
    padding: spacing.md,
    borderWidth: 1,
    borderColor: colors.warning,
    borderRadius: 18,
    backgroundColor: '#FFF9EA',
  },
  recoveryTitle: { color: colors.ink, fontSize: 15, fontWeight: '800' },
  recoveryBody: { color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
  note: { color: colors.inkMuted, fontSize: 13, lineHeight: 19, marginTop: spacing.xs },
});
