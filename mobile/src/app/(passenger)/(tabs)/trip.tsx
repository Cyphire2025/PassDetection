import { router } from 'expo-router';
import CloudDownload from 'lucide-react-native/icons/cloud-download';
import FileClock from 'lucide-react-native/icons/file-clock';
import FileText from 'lucide-react-native/icons/file-text';
import { useCallback, useMemo, useState } from 'react';
import {
  Pressable,
  RefreshControl,
  SectionList,
  StyleSheet,
  Text,
  View,
  type SectionListRenderItemInfo,
} from 'react-native';

import { MOBILE_LIST_WINDOWING } from '@/core/performance/mobile-performance-budgets';
import { useManualRefresh } from '@/core/query/use-manual-refresh';
import { englishMessages, formatInstantDate } from '@/core/localization/date-time';
import { passengerDocumentViewerRoute } from '@/core/navigation/document-viewer-routes';
import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import type { DocumentWithOfflineState } from '@/features/content/data/content-repository';
import { commonDocumentHeading, isItineraryDocument } from '@/features/content/data/passenger-document-policy';
import { useAnnouncements, useCommonDocuments } from '@/features/content/hooks/use-content';
import { useTrips } from '@/features/trips/hooks/use-trips';
import { DepartureCountdownCard } from '@/features/trips/ui/departure-countdown-card';

type CommonDocumentSection = {
  key: string;
  title: string;
  data: DocumentWithOfflineState[];
  fixed?: boolean;
};

export default function PassengerTripScreen() {
  const trips = useTrips();
  const selectedTimeZone = trips.selectedTrip?.timeZone;
  const announcements = useAnnouncements(trips.selectedTripId);
  const commonDocuments = useCommonDocuments(trips.selectedTripId);
  const [documentError, setDocumentError] = useState<string | null>(null);
  const refreshTrips = trips.refetch;
  const refreshAnnouncements = announcements.refetch;
  const refreshCommonDocuments = commonDocuments.refetch;
  const manualRefreshTask = useCallback(async () => {
    setDocumentError(null);
    await Promise.all([refreshTrips(), refreshAnnouncements(), refreshCommonDocuments()]);
  }, [refreshAnnouncements, refreshCommonDocuments, refreshTrips]);
  const manualRefresh = useManualRefresh();

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
      { key: 'itinerary', title: 'Itinerary', data: itinerary, fixed: true },
      ...[...grouped.entries()].map(([category, items]) => ({
        key: category,
        title: commonDocumentHeading(category),
        data: items,
      })),
    ];
  }, [commonDocuments.data?.items]);

  const openDocument = useCallback((document: DocumentWithOfflineState) => {
    if (document.metadata_state !== 'ready' || !document.offline_available) return;
    setDocumentError(null);
    router.push({
      pathname: passengerDocumentViewerRoute,
      params: { id: document.id, tripId: document.trip_id },
    });
  }, []);

  const renderDocument = useCallback(({
    item: document,
  }: SectionListRenderItemInfo<DocumentWithOfflineState, CommonDocumentSection>) => {
    const ready = document.metadata_state === 'ready' && document.offline_available;
    const offlineCurrent = ready && document.offline && document.offlineVersion === document.version;
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={ready ? `Open ${document.display_name}` : `${document.display_name} is being prepared`}
        disabled={!ready}
        onPress={() => openDocument(document)}
        style={styles.documentItem}>
        <GlassCard style={[styles.documentCard, !ready && styles.pendingCard]}>
          <View style={styles.documentIcon}>
            {ready ? <FileText color={colors.greenDeep} size={23} /> : <FileClock color={colors.inkMuted} size={23} />}
          </View>
          <View style={styles.documentCopy}>
            <Text numberOfLines={2} style={styles.documentTitle}>{document.display_name}</Text>
            <Text style={styles.documentMeta}>
              {ready
                ? englishMessages.updatedOn(formatInstantDate(
                  document.updated_at,
                  { timeZone: selectedTimeZone },
                ))
                : 'Being prepared'}
            </Text>
          </View>
          {!offlineCurrent ? (
            <CloudDownload accessibilityLabel="Download for offline use" color={colors.inkMuted} size={22} />
          ) : null}
        </GlassCard>
      </Pressable>
    );
  }, [openDocument, selectedTimeZone]);

  const renderSectionHeader = useCallback(({ section }: { section: CommonDocumentSection }) => (
    <View style={styles.sectionHeader}>
      <Text accessibilityRole="header" style={styles.sectionTitle}>{section.title}</Text>
      {section.data.length === 0 ? (
        <View style={styles.emptyDocument}>
          <Text style={styles.emptyTitle}>{section.fixed ? 'Itinerary not yet published' : 'No documents published'}</Text>
          <Text style={styles.emptyMessage}>
            {section.fixed
              ? 'Your published itinerary PDF will appear here and download automatically.'
              : 'This section will update as soon as your travel team publishes a file.'}
          </Text>
        </View>
      ) : null}
    </View>
  ), []);

  if (trips.isPending) return <ContentLoading label="Loading your trip" />;
  if (trips.isError) {
    return <ContentError message="Your trip is not available offline yet." onRetry={() => void trips.refetch()} />;
  }
  if (!trips.selectedTrip) {
    return (
      <Screen bottomInset={96}>
        <PageHeader eyebrow="Passenger" title="No eligible trip" tone="passenger" />
        <ContentEmpty title="Nothing to show yet" message="Ask your travel team to confirm that this group is enabled for the app." />
      </Screen>
    );
  }

  const trip = trips.selectedTrip;
  const importantAnnouncement = announcements.data?.items.find(
    (item) => item.priority === 'important' || item.priority === 'emergency',
  );

  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.screen}>
      <SectionList<DocumentWithOfflineState, CommonDocumentSection>
        sections={sections}
        keyExtractor={(document) => document.id}
        renderItem={renderDocument}
        renderSectionHeader={renderSectionHeader}
        stickySectionHeadersEnabled={false}
        contentContainerStyle={styles.list}
        {...MOBILE_LIST_WINDOWING.compact}
        refreshControl={(
          <RefreshControl
            refreshing={manualRefresh.isRefreshing}
            onRefresh={() => void manualRefresh.refresh(manualRefreshTask)}
          />
        )}
        ListHeaderComponent={
          <View style={styles.header}>
            <PageHeader eyebrow="My trip" title={trip.destination || trip.name} subtitle={trip.name} tone="passenger" />
            {trips.trips.length > 1 ? (
              <PrimaryButton
                label="Switch trip"
                tone="secondary"
                onPress={() => router.push('/(passenger)/select-trip')}
              />
            ) : null}
            <DepartureCountdownCard
              travelDate={trip.travelDate}
              returnDate={trip.returnDate}
              timeZone={trip.timeZone}
            />
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
  alertCard: { borderColor: 'rgba(184,64,77,0.25)', backgroundColor: 'rgba(255,242,243,0.9)', gap: spacing.xs },
  alertEyebrow: { color: colors.danger, fontSize: 11, fontWeight: '900', textTransform: 'uppercase' },
  alertTitle: { color: colors.ink, fontSize: 18, fontWeight: '800' },
  alertMessage: { color: colors.inkMuted, lineHeight: 21 },
  sectionHeader: { gap: spacing.sm, paddingTop: spacing.lg, paddingBottom: spacing.sm },
  sectionTitle: { color: colors.ink, fontSize: 21, fontWeight: '900' },
  documentItem: { paddingBottom: spacing.sm },
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
