import { useRouter } from 'expo-router';
import ClipboardCheck from 'lucide-react-native/icons/clipboard-check';
import FileCheck2 from 'lucide-react-native/icons/file-check';
import Plane from 'lucide-react-native/icons/plane';
import UsersRound from 'lucide-react-native/icons/users-round';
import {
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  View,
  type ColorValue,
} from 'react-native';

import { englishMessages, formatInstantDateTime } from '@/core/localization/date-time';
import { useManualRefresh } from '@/core/query/use-manual-refresh';
import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import { useReadiness } from '@/features/content/hooks/use-content';
import { useManagerAttendanceSessions } from '@/features/manager/hooks/use-manager-operations';
import { useTrips } from '@/features/trips/hooks/use-trips';
import { TripSwitcher } from '@/features/trips/ui/trip-switcher';
import type { LucideIcon } from 'lucide-react-native';

function Metric({
  icon: Icon,
  label,
  value,
  color,
  onPress,
}: {
  icon: LucideIcon;
  label: string;
  value: number;
  color: ColorValue;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${label}, ${value.toLocaleString()}`}
      onPress={onPress}
      style={({ pressed }) => [styles.metricPressable, pressed && styles.pressed]}>
      <GlassCard style={styles.metric}>
        <Icon color={color} size={22} />
        <Text style={styles.value}>{value.toLocaleString()}</Text>
        <Text style={styles.label}>{label}</Text>
      </GlassCard>
    </Pressable>
  );
}

export default function ManagerReadinessScreen() {
  const router = useRouter();
  const trips = useTrips();
  const manualRefresh = useManualRefresh();
  const readiness = useReadiness(trips.selectedTripId);
  const attendance = useManagerAttendanceSessions(trips.selectedTripId);
  const selectedTimeZone = trips.selectedTrip?.timeZone;

  return (
    <Screen
      bottomInset={104}
      contentStyle={styles.screen}
      scrollProps={{
        refreshControl: (
          <RefreshControl
            refreshing={manualRefresh.isRefreshing}
            onRefresh={() => void manualRefresh.refresh(
              () => Promise.all([trips.refetch(), readiness.refetch(), attendance.refetch()]),
            )}
          />
        ),
      }}>
      <PageHeader
        eyebrow="Group overview"
        title="Readiness"
        subtitle="Passenger documents and live attendance for the selected group."
        tone="manager"
      />
      <TripSwitcher trips={trips.trips} selectedTripId={trips.selectedTripId} onSelect={trips.selectTrip} />
      {readiness.isPending ? <ContentLoading label="Calculating readiness" /> : null}
      {readiness.isError ? (
        <ContentError message="Readiness is not available offline yet." onRetry={() => void readiness.refetch()} />
      ) : null}
      {readiness.data ? (
        <>
          <View style={styles.grid}>
            <Metric
              icon={UsersRound}
              label="Total passengers"
              value={readiness.data.passenger_count}
              color={colors.blueDeep}
              onPress={() => router.push('/(manager)/operations/passengers?mode=all')}
            />
            <Metric
              icon={FileCheck2}
              label="Visas"
              value={readiness.data.visas_available}
              color={colors.greenDeep}
              onPress={() => router.push('/(manager)/operations/passengers?mode=visa')}
            />
            <Metric
              icon={Plane}
              label="Flight tickets"
              value={readiness.data.tickets_available}
              color={colors.blueDeep}
              onPress={() => router.push('/(manager)/operations/passengers?mode=flight_ticket')}
            />
            <Metric
              icon={ClipboardCheck}
              label="Attendance"
              value={attendance.data?.items.length ?? 0}
              color={colors.greenDeep}
              onPress={() => router.push('/(manager)/operations/attendance')}
            />
          </View>
          <Text style={styles.updated}>
            {selectedTimeZone
              ? englishMessages.updatedOn(formatInstantDateTime(
                readiness.data.updated_at,
                { timeZone: selectedTimeZone },
              ))
              : englishMessages.dateUnavailable()} · version {readiness.data.version}
          </Text>
        </>
      ) : null}
      {!trips.selectedTripId && !trips.isPending ? (
        <ContentEmpty title="Select a group" message="Choose an explicitly assigned group to view its readiness summary." />
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.lg },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  metricPressable: { width: '47%' },
  metric: { minHeight: 132, borderRadius: radii.md, gap: spacing.xs },
  value: { color: colors.ink, fontSize: 23, fontWeight: '900', marginTop: spacing.sm },
  label: { color: colors.inkMuted, fontSize: 12, lineHeight: 17 },
  updated: { color: colors.inkMuted, fontSize: 11, textAlign: 'center' },
  pressed: { opacity: 0.72, transform: [{ scale: 0.98 }] },
});
