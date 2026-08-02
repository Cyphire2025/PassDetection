import { router } from 'expo-router';
import { StyleSheet, Text } from 'react-native';

import { PrimaryButton } from '@/design/components/primary-button';
import { colors, spacing } from '@/design/theme';
import { AuthShell } from '@/features/auth/ui/auth-shell';

export default function WelcomeScreen() {
  return (
    <AuthShell
      eyebrow="Group Companion"
      title="Your trip, ready when you are."
      description="Itinerary, personal QR, travel documents and important updates in one secure place.">
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
  note: { color: colors.inkMuted, fontSize: 13, lineHeight: 19, marginTop: spacing.xs },
});
