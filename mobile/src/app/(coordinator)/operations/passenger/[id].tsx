import { useLocalSearchParams } from 'expo-router';
import AlertTriangle from 'lucide-react-native/icons/triangle-alert';
import BadgeCheck from 'lucide-react-native/icons/badge-check';
import BedDouble from 'lucide-react-native/icons/bed-double';
import Contact from 'lucide-react-native/icons/contact';
import Soup from 'lucide-react-native/icons/soup';
import { StyleSheet, Text, View } from 'react-native';

import { ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import { useCoordinatorPassenger } from '@/features/coordinator/hooks/use-coordinator';
import { useCoordinatorTrips } from '@/features/coordinator/hooks/use-coordinator-trips';
import { OperationHeader } from '@/features/coordinator/ui/operation-header';

export default function CoordinatorPassengerDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const trips = useCoordinatorTrips();
  const detail = useCoordinatorPassenger(trips.selectedTripId, id ?? null);
  const passenger = detail.data?.passenger;

  return (
    <Screen contentStyle={styles.screen}>
      <OperationHeader title="Passenger details" subtitle={trips.selectedTrip?.name || 'Selected group'} />
      {detail.isPending ? <ContentLoading label="Loading passenger details" /> : null}
      {detail.isError ? (
        <ContentError
          message="These passenger details are not authorized or available on this device."
          onRetry={() => void detail.refetch()}
        />
      ) : null}
      {passenger ? (
        <>
          <View style={styles.identity}>
            <View style={styles.avatar}><Contact color={colors.greenDeep} size={32} /></View>
            <Text accessibilityRole="header" style={styles.name}>{passenger.display_name}</Text>
            <Text style={styles.employee}>{passenger.employee_code || 'Employee code not provided'}</Text>
          </View>
          <GlassCard style={styles.card}>
            <DetailRow
              icon={<BadgeCheck color={colors.greenDeep} size={21} />}
              label="Attendance"
              value={passenger.attendance_status.replaceAll('_', ' ')}
            />
            <DetailRow
              icon={<BedDouble color={colors.greenDeep} size={21} />}
              label="Room"
              value={passenger.room_number || 'Not assigned'}
            />
            <DetailRow
              icon={<Soup color={colors.greenDeep} size={21} />}
              label="Meal preference"
              value={passenger.meal_preference || 'Not recorded'}
            />
            {passenger.has_alert ? (
              <DetailRow
                icon={<AlertTriangle color={colors.warning} size={21} />}
                label="Important alert"
                value="Review with the operations team"
              />
            ) : null}
          </GlassCard>
        </>
      ) : null}
    </Screen>
  );
}

function DetailRow({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <View style={styles.row}>
      {icon}
      <View style={styles.rowText}>
        <Text style={styles.label}>{label}</Text>
        <Text style={styles.value}>{value}</Text>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.xl },
  identity: { alignItems: 'center', gap: spacing.sm },
  avatar: {
    width: 72,
    height: 72,
    borderRadius: 28,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.greenSoft,
  },
  name: { color: colors.ink, fontSize: 23, fontWeight: '900', textAlign: 'center' },
  employee: { color: colors.inkMuted, fontSize: 13, textAlign: 'center' },
  card: { gap: spacing.lg, borderRadius: radii.md },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  rowText: { flex: 1, gap: 3 },
  label: { color: colors.inkMuted, fontSize: 12, fontWeight: '700' },
  value: { color: colors.ink, fontSize: 15, fontWeight: '700', textTransform: 'capitalize' },
});
