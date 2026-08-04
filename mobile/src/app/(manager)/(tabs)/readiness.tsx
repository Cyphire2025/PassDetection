import AlertTriangle from 'lucide-react-native/icons/triangle-alert';
import BedDouble from 'lucide-react-native/icons/bed-double';
import CircleCheckBig from 'lucide-react-native/icons/circle-check-big';
import Plane from 'lucide-react-native/icons/plane';
import Soup from 'lucide-react-native/icons/soup';
import UsersRound from 'lucide-react-native/icons/users-round';
import { RefreshControl, StyleSheet, Text, View, type ColorValue } from 'react-native';

import { useManualRefresh } from '@/core/query/use-manual-refresh';
import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import { useReadiness } from '@/features/content/hooks/use-content';
import { useTrips } from '@/features/trips/hooks/use-trips';
import { TripSwitcher } from '@/features/trips/ui/trip-switcher';
import type { LucideIcon } from 'lucide-react-native';

function Metric({ icon: Icon, label, value, color }: { icon: LucideIcon; label: string; value: number; color: ColorValue }) {
  return (
    <GlassCard style={styles.metric}>
      <Icon color={color} size={22} />
      <Text style={styles.value}>{value.toLocaleString()}</Text>
      <Text style={styles.label}>{label}</Text>
    </GlassCard>
  );
}

export default function ManagerReadinessScreen() {
  const trips = useTrips();
  const manualRefresh = useManualRefresh();
  const readiness = useReadiness(trips.selectedTripId);

  return (
    <Screen
      bottomInset={104}
      contentStyle={styles.screen}
      scrollProps={{
        refreshControl: (
          <RefreshControl
            refreshing={manualRefresh.isRefreshing}
            onRefresh={() => void manualRefresh.refresh(
              () => Promise.all([trips.refetch(), readiness.refetch()]),
            )}
          />
        ),
      }}>
      <PageHeader eyebrow="Group overview" title="Readiness" subtitle="Summary-first operational status without personal document access." tone="manager" />
      <TripSwitcher trips={trips.trips} selectedTripId={trips.selectedTripId} onSelect={trips.selectTrip} />
      {readiness.isPending ? <ContentLoading label="Calculating readiness" /> : null}
      {readiness.isError ? (
        <ContentError message="Readiness is not available offline yet." onRetry={() => void readiness.refetch()} />
      ) : null}
      {readiness.data ? (
        <>
          <GlassCard style={styles.hero}>
            <UsersRound color={colors.blueDeep} size={26} />
            <View style={styles.heroText}>
              <Text style={styles.heroValue}>{readiness.data.passenger_count.toLocaleString()}</Text>
              <Text style={styles.heroLabel}>passengers in this group</Text>
            </View>
          </GlassCard>
          <View style={styles.grid}>
            <Metric icon={CircleCheckBig} label="Passports complete" value={readiness.data.passports_complete} color={colors.greenDeep} />
            <Metric icon={CircleCheckBig} label="Visas available" value={readiness.data.visas_available} color={colors.greenDeep} />
            <Metric icon={Plane} label="Tickets available" value={readiness.data.tickets_available} color={colors.blueDeep} />
            <Metric icon={AlertTriangle} label="Need attention" value={readiness.data.items_needing_attention} color={colors.warning} />
            <Metric icon={BedDouble} label="Rooms assigned" value={readiness.data.rooms_assigned} color={colors.blueDeep} />
            <Metric icon={Soup} label="Meals confirmed" value={readiness.data.meals_confirmed} color={colors.greenDeep} />
          </View>
          <Text style={styles.updated}>Updated {new Date(readiness.data.updated_at).toLocaleString()} · version {readiness.data.version}</Text>
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
  hero: { flexDirection: 'row', alignItems: 'center', gap: spacing.lg, backgroundColor: 'rgba(221,243,252,0.82)' },
  heroText: { flex: 1 },
  heroValue: { color: colors.ink, fontSize: 28, fontWeight: '900' },
  heroLabel: { color: colors.inkMuted, fontSize: 13 },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  metric: { width: '47%', minHeight: 132, borderRadius: radii.md, gap: spacing.xs },
  value: { color: colors.ink, fontSize: 23, fontWeight: '900', marginTop: spacing.sm },
  label: { color: colors.inkMuted, fontSize: 12, lineHeight: 17 },
  updated: { color: colors.inkMuted, fontSize: 11, textAlign: 'center' },
});
