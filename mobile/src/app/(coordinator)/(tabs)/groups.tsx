import CalendarDays from 'lucide-react-native/icons/calendar-days';
import ChevronRight from 'lucide-react-native/icons/chevron-right';
import MapPinned from 'lucide-react-native/icons/map-pinned';
import UsersRound from 'lucide-react-native/icons/users-round';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { StatusPill } from '@/design/components/status-pill';
import { colors, radii, spacing } from '@/design/theme';
import { useTrips } from '@/features/trips/hooks/use-trips';

export default function CoordinatorGroupsScreen() {
  const trips = useTrips();
  return (
    <Screen bottomInset={104} contentStyle={styles.screen}>
      <PageHeader
        eyebrow="Coordinator"
        title="Assigned trips"
        subtitle="Operational access is limited to your current assignments."
        accessory={trips.offline ? <StatusPill label="Offline roster" tone="warning" /> : undefined}
      />
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
                <View style={styles.icon}><UsersRound color={colors.blueDeep} size={23} /></View>
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
              {selected ? <StatusPill label="Active workspace" tone="good" /> : null}
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
  card: { borderRadius: radii.md, gap: spacing.md },
  selected: { borderColor: colors.blue, backgroundColor: 'rgba(221,243,252,0.82)' },
  pressed: { opacity: 0.7 },
  heading: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  icon: { width: 44, height: 44, borderRadius: 16, backgroundColor: colors.blueSoft, alignItems: 'center', justifyContent: 'center' },
  headingText: { flex: 1, gap: 3 },
  title: { color: colors.ink, fontSize: 17, fontWeight: '800' },
  subtitle: { color: colors.inkMuted, fontSize: 13 },
  metaRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: spacing.sm },
  meta: { color: colors.inkMuted, fontSize: 12, marginRight: spacing.sm },
});
