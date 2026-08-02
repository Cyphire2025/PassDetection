import LogOut from 'lucide-react-native/icons/log-out';
import Mail from 'lucide-react-native/icons/mail';
import MapPin from 'lucide-react-native/icons/map-pin';
import Phone from 'lucide-react-native/icons/phone';
import UserRound from 'lucide-react-native/icons/user-round';
import { StyleSheet, Text, View } from 'react-native';

import { logoutSession } from '@/core/auth/session-service';
import { useSessionStore } from '@/core/auth/session-store';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { colors, spacing } from '@/design/theme';
import { useTrips } from '@/features/trips/hooks/use-trips';

function initials(value: string): string {
  return value
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('') || 'P';
}

export default function PassengerMoreScreen() {
  const session = useSessionStore((state) => state.session);
  const trips = useTrips();
  const name = session?.principal.displayName || 'Passenger';

  return (
    <Screen bottomInset={104} contentStyle={styles.screen}>
      <View style={styles.profile}>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{initials(name)}</Text>
        </View>
        <Text accessibilityRole="header" style={styles.name}>{name}</Text>
        <View style={styles.roleRow}>
          <UserRound color={colors.greenDeep} size={17} />
          <Text style={styles.role}>Passenger</Text>
        </View>

        <View style={styles.details}>
          {session?.principal.phoneNumber ? (
            <View style={styles.detailRow}>
              <Phone color={colors.inkMuted} size={18} />
              <Text style={styles.detailText}>{session.principal.phoneNumber}</Text>
            </View>
          ) : null}
          {session?.principal.email ? (
            <View style={styles.detailRow}>
              <Mail color={colors.inkMuted} size={18} />
              <Text style={styles.detailText}>{session.principal.email}</Text>
            </View>
          ) : null}
          {trips.selectedTrip ? (
            <View style={styles.detailRow}>
              <MapPin color={colors.inkMuted} size={18} />
              <Text style={styles.detailText}>
                {[trips.selectedTrip.name, trips.selectedTrip.destination].filter(Boolean).join(' · ')}
              </Text>
            </View>
          ) : null}
        </View>
      </View>

      <View style={styles.signOut}>
        <LogOut color={colors.danger} size={22} />
        <Text style={styles.signOutNote}>Sign out of this passenger account</Text>
      </View>
      <PrimaryButton label="Sign out" tone="danger" onPress={() => void logoutSession()} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.lg, alignItems: 'stretch' },
  profile: { alignItems: 'center', gap: spacing.sm, paddingTop: spacing.xl, paddingBottom: spacing.xl },
  avatar: { width: 88, height: 88, borderRadius: 44, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.greenSoft, borderWidth: 1, borderColor: colors.border, marginBottom: spacing.sm },
  avatarText: { color: colors.greenDeep, fontSize: 30, fontWeight: '900', letterSpacing: 1 },
  name: { color: colors.ink, fontSize: 27, lineHeight: 33, fontWeight: '900', textAlign: 'center' },
  roleRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  role: { color: colors.greenDeep, fontSize: 13, fontWeight: '800' },
  details: { alignItems: 'center', gap: spacing.sm, paddingTop: spacing.lg, maxWidth: 360 },
  detailRow: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: spacing.sm },
  detailText: { flexShrink: 1, color: colors.inkMuted, fontSize: 14, lineHeight: 20, textAlign: 'center' },
  signOut: { flexDirection: 'row', justifyContent: 'center', alignItems: 'center', gap: spacing.sm, paddingTop: spacing.xl },
  signOutNote: { color: colors.inkMuted, fontSize: 13 },
});
