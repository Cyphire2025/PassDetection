import LogOut from 'lucide-react-native/icons/log-out';
import ShieldCheck from 'lucide-react-native/icons/shield-check';
import { StyleSheet, Text, View } from 'react-native';

import { useSessionStore } from '@/core/auth/session-store';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';

import { SafeSignOutButton } from './safe-sign-out-button';

export function ProfileScreen({
  eyebrow,
  showStorageCard = true,
}: {
  eyebrow: string;
  showStorageCard?: boolean;
}) {
  const session = useSessionStore((state) => state.session);

  return (
    <Screen bottomInset={104} contentStyle={styles.screen}>
      <PageHeader
        eyebrow={eyebrow}
        title={session?.principal.displayName || 'Profile'}
        subtitle="Privacy, sessions and offline storage on this device."
        tone={eyebrow === 'Coordinator' ? 'coordinator' : eyebrow === 'Client Manager' ? 'manager' : 'neutral'}
      />
      {showStorageCard ? (
        <GlassCard style={styles.card}>
          <View style={styles.row}>
            <ShieldCheck color={colors.greenDeep} size={24} />
            <View style={styles.rowText}>
              <Text style={styles.rowTitle}>Account-isolated storage</Text>
              <Text style={styles.rowDescription}>
                Offline files stay encrypted and remain isolated to this account on this device.
              </Text>
            </View>
          </View>
        </GlassCard>
      ) : null}
      <GlassCard style={styles.card}>
        <View style={styles.row}>
          <LogOut color={colors.danger} size={24} />
          <View style={styles.rowText}>
            <Text style={styles.rowTitle}>Sign out</Text>
            <Text style={styles.rowDescription}>
              Authentication is removed immediately. Encrypted offline documents remain available after you sign in to this account again.
            </Text>
          </View>
        </View>
        <SafeSignOutButton label="Sign out" />
      </GlassCard>
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.lg },
  card: { borderRadius: radii.md, gap: spacing.lg },
  row: { flexDirection: 'row', gap: spacing.md },
  rowText: { flex: 1, gap: spacing.xs },
  rowTitle: { color: colors.ink, fontSize: 16, fontWeight: '800' },
  rowDescription: { color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
});
