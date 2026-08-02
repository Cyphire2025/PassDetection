import { differenceInCalendarDays, format, parseISO } from 'date-fns';
import { router } from 'expo-router';
import CheckCircle2 from 'lucide-react-native/icons/circle-check-big';
import CloudDownload from 'lucide-react-native/icons/cloud-download';
import FileClock from 'lucide-react-native/icons/file-clock';
import FileText from 'lucide-react-native/icons/file-text';
import { useCallback, useMemo, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View, type ListRenderItem } from 'react-native';

import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import { cacheDocument, type DocumentWithOfflineState } from '@/features/content/data/content-repository';
import { commonDocumentHeading, isItineraryDocument } from '@/features/content/data/passenger-document-policy';
import { useAnnouncements, useCommonDocuments } from '@/features/content/hooks/use-content';
import { useTrips } from '@/features/trips/hooks/use-trips';
import { TripSwitcher } from '@/features/trips/ui/trip-switcher';

type CommonDocumentSection = {
  key: string;
  title: string;
  documents: DocumentWithOfflineState[];
  fixed?: boolean;
};

export default function PassengerTripScreen() {
  const trips = useTrips();
  const announcements = useAnnouncements(trips.selectedTripId);
  const commonDocuments = useCommonDocuments(trips.selectedTripId);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [documentError, setDocumentError] = useState<string | null>(null);

  const sections = useMemo<CommonDocumentSection[]>(() => {
    const documents = commonDocuments.data?.items ?? [];
    const itinerary = documents.filter((document) => isItineraryDocument(document.category));
    const grouped = new Map<string, DocumentWithOfflineState[]>();
    for (const document of documents) {
      if (isItineraryDocument(document.category)) continue;
      const current = grouped.get(document.category) ?? [];
      current.push(document);
      grouped.set(document.category, current);
    }
    return [
      { key: 'itinerary', title: 'Itinerary', documents: itinerary, fixed: true },
      ...[...grouped.entries()].map(([category, items]) => ({
        key: category,
        title: commonDocumentHeading(category),
        documents: items,
      })),
    ];
  }, [commonDocuments.data?.items]);

  const openDocument = useCallback(async (document: DocumentWithOfflineState) => {
    if (document.metadata_state !== 'ready' || !document.offline_available) return;
    setOpeningId(document.id);
    setDocumentError(null);
    try {
      if (!document.offline || document.offlineVersion !== document.version) await cacheDocument(document);
      router.push({ pathname: '/document/[id]', params: { id: document.id } });
    } catch (caught) {
      setDocumentError(caught instanceof Error ? caught.message : 'This document could not be opened.');
    } finally {
      setOpeningId(null);
    }
  }, []);

  const renderSection = useCallback<ListRenderItem<CommonDocumentSection>>(({ item: section }) => (
    <View style={styles.documentSection}>
      <Text accessibilityRole="header" style={styles.sectionTitle}>{section.title}</Text>
      {section.documents.length ? section.documents.map((document) => {
        const ready = document.metadata_state === 'ready' && document.offline_available;
        const offlineCurrent = ready && document.offline && document.offlineVersion === document.version;
        return (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={ready ? `Open ${document.display_name}` : `${document.display_name} is being prepared`}
            disabled={!ready || openingId === document.id}
            key={document.id}
            onPress={() => void openDocument(document)}>
            <GlassCard style={[styles.documentCard, !ready && styles.pendingCard]}>
              <View style={styles.documentIcon}>
                {ready ? <FileText color={colors.greenDeep} size={23} /> : <FileClock color={colors.inkMuted} size={23} />}
              </View>
              <View style={styles.documentCopy}>
                <Text numberOfLines={2} style={styles.documentTitle}>{document.display_name}</Text>
                <Text style={styles.documentMeta}>
                  {ready ? `Updated ${new Date(document.updated_at).toLocaleDateString()}` : 'Being prepared'}
                </Text>
              </View>
              {offlineCurrent ? (
                <CheckCircle2 accessibilityLabel="Ready offline" color={colors.greenDeep} size={22} />
              ) : (
                <CloudDownload accessibilityLabel="Download for offline use" color={colors.inkMuted} size={22} />
              )}
            </GlassCard>
          </Pressable>
        );
      }) : (
        <View style={styles.emptyDocument}>
          <Text style={styles.emptyTitle}>{section.fixed ? 'Itinerary not yet published' : 'No documents published'}</Text>
          <Text style={styles.emptyMessage}>
            {section.fixed
              ? 'Your published itinerary PDF will appear here and download automatically.'
              : 'This section will update as soon as your travel team publishes a file.'}
          </Text>
        </View>
      )}
    </View>
  ), [openDocument, openingId]);

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

  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.screen}>
      <FlatList
        data={sections}
        keyExtractor={(section) => section.key}
        renderItem={renderSection}
        contentContainerStyle={styles.list}
        initialNumToRender={6}
        maxToRenderPerBatch={8}
        windowSize={5}
        ListHeaderComponent={
          <View style={styles.header}>
            <PageHeader eyebrow="My trip" title={trip.destination || trip.name} subtitle={trip.name} />
            <TripSwitcher trips={trips.trips} selectedTripId={trips.selectedTripId} onSelect={trips.selectTrip} />
            <View style={styles.departure}>
              <View style={styles.departureCopy}>
                <Text style={styles.departureLabel}>Departure</Text>
                <Text style={styles.departureDate}>
                  {trip.travelDate ? format(parseISO(trip.travelDate), 'EEE, d MMM yyyy') : 'Dates being prepared'}
                </Text>
                {trip.returnDate ? <Text style={styles.returnDate}>Returns {format(parseISO(trip.returnDate), 'd MMM yyyy')}</Text> : null}
              </View>
              {daysUntilDeparture !== null && daysUntilDeparture >= 0 ? (
                <View style={styles.countdown}>
                  <Text style={styles.countdownNumber}>{daysUntilDeparture}</Text>
                  <Text style={styles.countdownLabel}>{daysUntilDeparture === 1 ? 'day' : 'days'}</Text>
                </View>
              ) : null}
            </View>
            {importantAnnouncement ? (
              <GlassCard style={styles.alertCard}>
                <Text style={styles.alertEyebrow}>{importantAnnouncement.priority === 'emergency' ? 'Emergency update' : 'Important update'}</Text>
                <Text style={styles.alertTitle}>{importantAnnouncement.title}</Text>
                <Text numberOfLines={4} style={styles.alertMessage}>{importantAnnouncement.message}</Text>
              </GlassCard>
            ) : null}
            {documentError ? <ContentError message={documentError} /> : null}
            {commonDocuments.isPending ? <ContentLoading label="Loading common documents" /> : null}
            {commonDocuments.isError ? (
              <ContentError message="Common documents are not available on this device yet." onRetry={() => void commonDocuments.refetch()} />
            ) : null}
          </View>
        }
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 0 },
  list: { paddingHorizontal: spacing.lg, paddingBottom: 104 },
  header: { gap: spacing.lg, paddingBottom: spacing.sm },
  departure: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.lg,
    paddingVertical: spacing.md,
    borderTopWidth: 1,
    borderBottomWidth: 1,
    borderColor: colors.border,
  },
  departureCopy: { flex: 1, gap: spacing.xs },
  departureLabel: { color: colors.greenDeep, fontSize: 12, fontWeight: '900', textTransform: 'uppercase', letterSpacing: 1 },
  departureDate: { color: colors.ink, fontSize: 21, fontWeight: '800' },
  returnDate: { color: colors.inkMuted, fontSize: 14 },
  countdown: { minWidth: 68, alignItems: 'center', justifyContent: 'center' },
  countdownNumber: { color: colors.greenDeep, fontSize: 27, fontWeight: '900', lineHeight: 29 },
  countdownLabel: { color: colors.inkMuted, fontSize: 11, fontWeight: '700' },
  alertCard: { borderColor: 'rgba(184,64,77,0.25)', backgroundColor: 'rgba(255,242,243,0.9)', gap: spacing.xs },
  alertEyebrow: { color: colors.danger, fontSize: 11, fontWeight: '900', textTransform: 'uppercase' },
  alertTitle: { color: colors.ink, fontSize: 18, fontWeight: '800' },
  alertMessage: { color: colors.inkMuted, lineHeight: 21 },
  documentSection: { gap: spacing.sm, paddingTop: spacing.lg },
  sectionTitle: { color: colors.ink, fontSize: 21, fontWeight: '900' },
  documentCard: { borderRadius: radii.md, padding: spacing.md, flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  pendingCard: { opacity: 0.72 },
  documentIcon: { width: 44, height: 44, borderRadius: 14, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.greenSoft },
  documentCopy: { flex: 1, gap: 3 },
  documentTitle: { color: colors.ink, fontSize: 15, fontWeight: '800' },
  documentMeta: { color: colors.inkMuted, fontSize: 11 },
  emptyDocument: { gap: spacing.xs, paddingVertical: spacing.md, paddingHorizontal: spacing.sm },
  emptyTitle: { color: colors.ink, fontSize: 15, fontWeight: '800' },
  emptyMessage: { color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
});
