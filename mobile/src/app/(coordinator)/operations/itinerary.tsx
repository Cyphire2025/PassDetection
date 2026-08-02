import { StyleSheet, Text } from 'react-native';

import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import { useItinerary } from '@/features/content/hooks/use-itinerary';
import { OperationHeader } from '@/features/coordinator/ui/operation-header';
import { useTrips } from '@/features/trips/hooks/use-trips';

export default function CoordinatorItineraryScreen() {
  const trips = useTrips();
  const itinerary = useItinerary(trips.selectedTripId);
  return (
    <Screen contentStyle={styles.screen}>
      <OperationHeader title="Itinerary" subtitle={trips.selectedTrip?.name || 'Selected trip'} />
      {itinerary.isPending ? <ContentLoading label="Loading itinerary" /> : null}
      {itinerary.isError ? <ContentError message="Itinerary is unavailable offline." onRetry={() => void itinerary.refetch()} /> : null}
      {itinerary.data?.itinerary?.days.map((day) => (
        <GlassCard key={day.id} style={styles.day}>
          <Text style={styles.dayTitle}>Day {day.day_number} · {day.title || day.date || 'Schedule'}</Text>
          {day.items.map((item) => (
            <GlassCard key={item.id} style={styles.item}>
              <Text style={styles.itemTitle}>{item.title}</Text>
              <Text style={styles.meta}>{item.location_name || 'Location pending'}{item.starts_at ? ` · ${new Date(item.starts_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}</Text>
            </GlassCard>
          ))}
        </GlassCard>
      ))}
      {itinerary.data && !itinerary.data.itinerary ? <ContentEmpty title="Not published" message="No itinerary is currently published." /> : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.lg },
  day: { gap: spacing.sm, borderRadius: radii.md },
  dayTitle: { color: colors.greenDeep, fontSize: 16, fontWeight: '900' },
  item: { gap: 3, borderRadius: radii.sm, padding: spacing.md },
  itemTitle: { color: colors.ink, fontSize: 14, fontWeight: '800' },
  meta: { color: colors.inkMuted, fontSize: 12 },
});
