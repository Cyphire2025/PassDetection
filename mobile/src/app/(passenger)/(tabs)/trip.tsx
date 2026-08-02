import { differenceInCalendarDays, format, parseISO } from 'date-fns';
import CalendarDays from 'lucide-react-native/icons/calendar-days';
import Hotel from 'lucide-react-native/icons/hotel';
import UtensilsCrossed from 'lucide-react-native/icons/utensils-crossed';
import { SectionList, StyleSheet, Text, View, type SectionListRenderItemInfo } from 'react-native';

import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { StatusPill } from '@/design/components/status-pill';
import { colors, radii, spacing } from '@/design/theme';
import type { Itinerary } from '@/features/content/api/content-contracts';
import { useAnnouncements, useMeal, useRoom } from '@/features/content/hooks/use-content';
import { useItinerary } from '@/features/content/hooks/use-itinerary';
import { useTrips } from '@/features/trips/hooks/use-trips';
import { TripSwitcher } from '@/features/trips/ui/trip-switcher';

type ItineraryDay = Itinerary['days'][number];
type ItineraryItem = ItineraryDay['items'][number];
type ItinerarySection = { day: ItineraryDay; data: ItineraryItem[] };

export default function PassengerTripScreen() {
  const trips = useTrips();
  const itinerary = useItinerary(trips.selectedTripId);
  const announcements = useAnnouncements(trips.selectedTripId);
  const room = useRoom(trips.selectedTripId);
  const meal = useMeal(trips.selectedTripId);

  if (trips.isPending) return <ContentLoading label="Loading your trip" />;
  if (trips.isError) {
    return <ContentError message="Your trip is not available offline yet." onRetry={() => void trips.refetch()} />;
  }
  if (!trips.selectedTrip) {
    return (
      <Screen bottomInset={96}>
        <PageHeader eyebrow="Passenger" title="No eligible trip" />
        <ContentEmpty title="Nothing to show yet" message="Ask your travel team to confirm that this group is enabled for the app." />
      </Screen>
    );
  }

  const trip = trips.selectedTrip;
  const daysUntilDeparture = trip.travelDate
    ? differenceInCalendarDays(parseISO(trip.travelDate), new Date())
    : null;
  const importantAnnouncement = announcements.data?.items.find(
    (item) => item.priority === 'important' || item.priority === 'emergency',
  );
  const sections: ItinerarySection[] =
    itinerary.data?.itinerary?.days.map((day) => ({ day, data: day.items })) ?? [];

  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.screen}>
      <SectionList<ItineraryItem, ItinerarySection>
        sections={sections}
        keyExtractor={(item) => item.id}
        renderItem={renderItineraryItem}
        renderSectionHeader={renderDayHeader}
        stickySectionHeadersEnabled={false}
        initialNumToRender={10}
        maxToRenderPerBatch={12}
        windowSize={7}
        contentContainerStyle={styles.list}
        ListHeaderComponent={
          <View style={styles.stack}>
            <PageHeader
              eyebrow="My trip"
              title={trip.destination || trip.name}
              subtitle={trip.name}
              accessory={<StatusPill label={trips.offline ? 'Offline copy' : 'Synced'} tone={trips.offline ? 'warning' : 'good'} />}
            />
            <TripSwitcher trips={trips.trips} selectedTripId={trips.selectedTripId} onSelect={trips.selectTrip} />

            <GlassCard style={styles.hero}>
              <View style={styles.heroTop}>
                <View style={styles.heroText}>
                  <Text style={styles.heroLabel}>Departure</Text>
                  <Text style={styles.heroDate}>
                    {trip.travelDate ? format(parseISO(trip.travelDate), 'EEE, d MMM yyyy') : 'Dates being prepared'}
                  </Text>
                </View>
                {daysUntilDeparture !== null && daysUntilDeparture >= 0 ? (
                  <View style={styles.countdown}>
                    <Text style={styles.countdownNumber}>{daysUntilDeparture}</Text>
                    <Text style={styles.countdownLabel}>{daysUntilDeparture === 1 ? 'day' : 'days'}</Text>
                  </View>
                ) : null}
              </View>
              {trip.returnDate ? <Text style={styles.returnDate}>Returns {format(parseISO(trip.returnDate), 'd MMM yyyy')}</Text> : null}
            </GlassCard>

            {importantAnnouncement ? (
              <GlassCard style={styles.alertCard}>
                <Text style={styles.alertEyebrow}>{importantAnnouncement.priority === 'emergency' ? 'Emergency update' : 'Important update'}</Text>
                <Text style={styles.alertTitle}>{importantAnnouncement.title}</Text>
                <Text numberOfLines={4} style={styles.alertMessage}>{importantAnnouncement.message}</Text>
              </GlassCard>
            ) : null}

            <View style={styles.sectionHeader}>
              <Text accessibilityRole="header" style={styles.sectionTitle}>Itinerary</Text>
              {itinerary.data?.offline ? <StatusPill label="Available offline" tone="good" /> : null}
            </View>
            {itinerary.isPending ? <ContentLoading label="Loading itinerary" /> : null}
            {itinerary.isError ? (
              <ContentError message="The itinerary has not been synchronized on this device." onRetry={() => void itinerary.refetch()} />
            ) : null}
            {itinerary.data && !itinerary.data.itinerary ? (
              <ContentEmpty title="Itinerary not published" message="Your travel team can publish it without requiring an app update." />
            ) : null}
          </View>
        }
        ListFooterComponent={
          <View style={styles.footer}>
            <Text accessibilityRole="header" style={styles.sectionTitle}>Stay & meals</Text>
            <View style={styles.summaryGrid}>
              <GlassCard style={styles.summaryCard}>
                <Hotel color={colors.blueDeep} size={22} />
                <Text style={styles.summaryLabel}>Room</Text>
                <Text style={styles.summaryValue}>{room.data?.room_number || 'Not assigned'}</Text>
                <Text numberOfLines={2} style={styles.summaryMeta}>{room.data?.hotel_name || 'Hotel information will appear here'}</Text>
              </GlassCard>
              <GlassCard style={styles.summaryCard}>
                <UtensilsCrossed color={colors.greenDeep} size={22} />
                <Text style={styles.summaryLabel}>Meal</Text>
                <Text numberOfLines={2} style={styles.summaryValue}>{meal.data?.preference || 'Not recorded'}</Text>
                <Text numberOfLines={2} style={styles.summaryMeta}>{meal.data?.notes || 'Your latest synchronized preference'}</Text>
              </GlassCard>
            </View>
            <View style={styles.offlineNote}>
              <CalendarDays color={colors.inkMuted} size={18} />
              <Text style={styles.offlineText}>Your last synchronized itinerary remains available without a network connection.</Text>
            </View>
          </View>
        }
      />
    </Screen>
  );
}

function renderDayHeader({ section }: { section: ItinerarySection }) {
  const { day } = section;
  return (
    <View accessibilityRole="header" style={styles.dayHeader}>
      <View style={styles.timelineRail}>
        <View style={styles.dayDot} />
        <View style={styles.dayLine} />
      </View>
      <View style={styles.dayHeadingText}>
        <Text style={styles.dayLabel}>Day {day.day_number}</Text>
        <Text style={styles.dayTitle}>
          {day.title || (day.date ? format(parseISO(day.date), 'EEEE, d MMMM') : 'Schedule')}
        </Text>
      </View>
    </View>
  );
}

function renderItineraryItem({ item }: SectionListRenderItemInfo<ItineraryItem, ItinerarySection>) {
  return (
    <View style={styles.itemRow}>
      <View style={styles.itemRail}><View style={styles.itemLine} /></View>
      <GlassCard style={styles.itineraryItem}>
        <Text style={styles.itemTime}>{item.starts_at ? format(parseISO(item.starts_at), 'p') : 'Time to be confirmed'}</Text>
        <Text style={styles.itemTitle}>{item.title}</Text>
        {item.location_name ? <Text style={styles.itemMeta}>{item.location_name}</Text> : null}
        {item.description ? <Text style={styles.itemDescription}>{item.description}</Text> : null}
      </GlassCard>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 0 },
  list: { paddingHorizontal: spacing.lg, paddingBottom: 104 },
  stack: { gap: spacing.lg },
  footer: { gap: spacing.lg, paddingTop: spacing.lg },
  hero: { backgroundColor: 'rgba(221,243,252,0.86)', gap: spacing.sm },
  heroTop: { flexDirection: 'row', alignItems: 'center', gap: spacing.lg },
  heroText: { flex: 1, gap: spacing.xs },
  heroLabel: { color: colors.blueDeep, fontSize: 12, fontWeight: '800', textTransform: 'uppercase', letterSpacing: 1 },
  heroDate: { color: colors.ink, fontSize: 21, fontWeight: '800' },
  returnDate: { color: colors.inkMuted, fontSize: 14 },
  countdown: { width: 68, height: 68, borderRadius: 34, backgroundColor: colors.white, alignItems: 'center', justifyContent: 'center' },
  countdownNumber: { color: colors.greenDeep, fontSize: 25, fontWeight: '900', lineHeight: 27 },
  countdownLabel: { color: colors.inkMuted, fontSize: 11, fontWeight: '700' },
  alertCard: { borderColor: 'rgba(184,64,77,0.25)', backgroundColor: 'rgba(255,242,243,0.9)', gap: spacing.xs },
  alertEyebrow: { color: colors.danger, fontSize: 11, fontWeight: '900', textTransform: 'uppercase' },
  alertTitle: { color: colors.ink, fontSize: 18, fontWeight: '800' },
  alertMessage: { color: colors.inkMuted, lineHeight: 21 },
  sectionHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  sectionTitle: { color: colors.ink, fontSize: 21, fontWeight: '800' },
  dayHeader: { flexDirection: 'row', backgroundColor: 'rgba(248,253,255,0.97)', paddingTop: spacing.lg },
  timelineRail: { width: 26, alignItems: 'center' },
  dayDot: { width: 13, height: 13, borderRadius: 7, backgroundColor: colors.green, marginTop: 7 },
  dayLine: { width: 2, flex: 1, minHeight: 28, backgroundColor: colors.border, marginTop: 4 },
  dayHeadingText: { flex: 1, paddingBottom: spacing.sm },
  dayLabel: { color: colors.greenDeep, fontSize: 12, fontWeight: '900', textTransform: 'uppercase' },
  dayTitle: { color: colors.ink, fontSize: 18, fontWeight: '800', marginTop: 2 },
  itemRow: { flexDirection: 'row', paddingBottom: spacing.sm },
  itemRail: { width: 26, alignItems: 'center' },
  itemLine: { width: 2, flex: 1, backgroundColor: colors.border },
  itineraryItem: { flex: 1, borderRadius: radii.md, padding: spacing.md, gap: 3 },
  itemTime: { color: colors.blueDeep, fontSize: 12, fontWeight: '800' },
  itemTitle: { color: colors.ink, fontSize: 16, fontWeight: '700' },
  itemMeta: { color: colors.greenDeep, fontSize: 13 },
  itemDescription: { color: colors.inkMuted, fontSize: 13, lineHeight: 19, marginTop: spacing.xs },
  summaryGrid: { flexDirection: 'row', gap: spacing.md },
  summaryCard: { flex: 1, borderRadius: radii.md, gap: spacing.xs },
  summaryLabel: { color: colors.inkMuted, fontSize: 12, fontWeight: '700', marginTop: spacing.sm },
  summaryValue: { color: colors.ink, fontSize: 16, fontWeight: '800' },
  summaryMeta: { color: colors.inkMuted, fontSize: 12, lineHeight: 17 },
  offlineNote: { flexDirection: 'row', gap: spacing.sm, alignItems: 'center' },
  offlineText: { flex: 1, color: colors.inkMuted, fontSize: 12, lineHeight: 18 },
});
