import Mail from 'lucide-react-native/icons/mail';
import Phone from 'lucide-react-native/icons/phone';
import UserRound from 'lucide-react-native/icons/user-round';
import { StyleSheet, Text, View } from 'react-native';

import { logoutSession } from '@/core/auth/session-service';
import { useSessionStore } from '@/core/auth/session-store';
import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import { OperationHeader } from '@/features/coordinator/ui/operation-header';

export default function CoordinatorProfileScreen() {
  const principal = useSessionStore((state) => state.session?.principal ?? null);
  return (
    <Screen contentStyle={styles.screen}>
      <OperationHeader title="Profile" subtitle="Coordinator account" />
      <View style={styles.identity}>
        <View style={styles.avatar}><UserRound color={colors.greenDeep} size={34} /></View>
        <Text accessibilityRole="header" style={styles.name}>{principal?.displayName || 'Coordinator'}</Text>
        <Text style={styles.role}>Coordinator</Text>
      </View>
      <GlassCard style={styles.details}>
        {principal?.phoneNumber ? (
          <View style={styles.detailRow}>
            <Phone color={colors.greenDeep} size={20} />
            <View style={styles.detailText}>
              <Text style={styles.label}>Phone</Text>
              <Text selectable style={styles.value}>{principal.phoneNumber}</Text>
            </View>
          </View>
        ) : null}
        {principal?.email ? (
          <View style={styles.detailRow}>
            <Mail color={colors.greenDeep} size={20} />
            <View style={styles.detailText}>
              <Text style={styles.label}>Email</Text>
              <Text selectable style={styles.value}>{principal.email}</Text>
            </View>
          </View>
        ) : null}
        {!principal?.phoneNumber && !principal?.email ? (
          <Text style={styles.unavailable}>No additional contact details are available for this account.</Text>
        ) : null}
      </GlassCard>
      <PrimaryButton label="Sign out" tone="danger" onPress={() => void logoutSession()} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.xl },
  identity: { alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.md },
  avatar: {
    width: 78,
    height: 78,
    borderRadius: 30,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.greenSoft,
  },
  name: { color: colors.ink, fontSize: 25, fontWeight: '900', textAlign: 'center' },
  role: { color: colors.inkMuted, fontSize: 14, fontWeight: '700' },
  details: { gap: spacing.lg, borderRadius: radii.md },
  detailRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  detailText: { flex: 1, gap: 3 },
  label: { color: colors.inkMuted, fontSize: 12, fontWeight: '700' },
  value: { color: colors.ink, fontSize: 15, fontWeight: '700' },
  unavailable: { color: colors.inkMuted, fontSize: 13, lineHeight: 19, textAlign: 'center' },
});
