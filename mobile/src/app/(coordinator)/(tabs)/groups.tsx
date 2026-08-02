import CalendarDays from 'lucide-react-native/icons/calendar-days';
import ChevronRight from 'lucide-react-native/icons/chevron-right';
import MapPinned from 'lucide-react-native/icons/map-pinned';
import UsersRound from 'lucide-react-native/icons/users-round';
import { useLocalSearchParams } from 'expo-router';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { StatusPill } from '@/design/components/status-pill';
import { colors, radii, spacing } from '@/design/theme';
import { useCoordinatorTrips } from '@/features/coordinator/hooks/use-coordinator-trips';

export default function CoordinatorGroupsScreen() {
  const trips = useCoordinatorTrips();
  const { notice } = useLocalSearchParams<{ notice?: string }>();
  return (
    <Screen bottomInset={104} contentStyle={styles.screen}>
      <PageHeader
        eyebrow="Coordinator"
        title="Assigned trips"
        subtitle="Operational access is limited to your current assignments."
      />
      {notice === 'select-group' && !trips.selectedTripId ? (
        <GlassCard style={styles.notice}>
          <Text accessibilityRole="alert" style={styles.noticeText}>Select a group to continue.</Text>
        </GlassCard>
      ) : null}
      {trips.isPending ? <ContentLoading label="Loading assigned trips" /> : null}
      {trips.isError ? <ContentError message="No assigned trip is available offline." onRetry={() => void trips.refetch()} /> : null}
      {trips.trips.map((trip) => {
        const selected = trip.id === trips.selectedTripId;
        return (
          <Pressable
            key={trip.id}
            accessibilityRole="radio"
            accessibilityState={{ selected }}
            onPress={() => trips.selectTrip(trip.id)}
            style={({ pressed }) => pressed && styles.pressed}>
            <GlassCard style={[styles.card, selected && styles.selected]}>
              <View style={styles.heading}>
                <View style={styles.icon}><UsersRound color={colors.greenDeep} size={23} /></View>
                <View style={styles.headingText}>
                  <Text style={styles.title}>{trip.name}</Text>
                  <Text style={styles.subtitle}>{trip.destination || 'Destination pending'}</Text>
                </View>
                <ChevronRight color={colors.inkMuted} size={20} />
              </View>
              <View style={styles.metaRow}>
                <MapPinned color={colors.greenDeep} size={16} />
                <Text style={styles.meta}>{trip.destination || 'Location pending'}</Text>
                <CalendarDays color={colors.greenDeep} size={16} />
                <Text style={styles.meta}>{trip.travelDate || 'Dates pending'}</Text>
              </View>
              {selected ? <StatusPill label="Selected group" tone="good" /> : null}
            </GlassCard>
          </Pressable>
        );
      })}
      {!trips.isPending && !trips.isError && trips.trips.length === 0 ? (
        <ContentEmpty title="No assigned trips" message="Ask operations staff to enable Coordinator access and assign this account." />
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.lg },
  card: { borderRadius: radii.md, gap: spacing.md, backgroundColor: colors.white },
  selected: { borderColor: colors.green, borderWidth: 2, backgroundColor: colors.white },
  notice: { padding: spacing.md, borderColor: colors.green },
  noticeText: { color: colors.greenDeep, fontSize: 14, fontWeight: '800' },
  pressed: { opacity: 0.7 },
  heading: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  icon: { width: 44, height: 44, borderRadius: 16, backgroundColor: colors.greenSoft, alignItems: 'center', justifyContent: 'center' },
  headingText: { flex: 1, gap: 3 },
  title: { color: colors.ink, fontSize: 17, fontWeight: '800' },
  subtitle: { color: colors.inkMuted, fontSize: 13 },
  metaRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: spacing.sm },
  meta: { color: colors.inkMuted, fontSize: 12, marginRight: spacing.sm },
});
