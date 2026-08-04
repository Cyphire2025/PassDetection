import { router } from 'expo-router';
import FileText from 'lucide-react-native/icons/file-text';
import MapPin from 'lucide-react-native/icons/map-pin';
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

import { useManualRefresh } from '@/core/query/use-manual-refresh';
import { managerDocumentViewerRoute } from '@/core/navigation/document-viewer-routes';
import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { StatusPill } from '@/design/components/status-pill';
import { colors, radii, spacing } from '@/design/theme';
import type { Itinerary } from '@/features/content/api/content-contracts';
import type { DocumentWithOfflineState } from '@/features/content/data/content-repository';
import { useCommonDocuments } from '@/features/content/hooks/use-content';
import { useItinerary } from '@/features/content/hooks/use-itinerary';
import { useTrips } from '@/features/trips/hooks/use-trips';
import { TripSwitcher } from '@/features/trips/ui/trip-switcher';

type ItineraryDay = Itinerary['days'][number];
type ItineraryItem = ItineraryDay['items'][number];
type Row =
  | { kind: 'itinerary'; value: ItineraryItem }
  | { kind: 'document'; value: DocumentWithOfflineState };
type Section =
  | { kind: 'day'; day: ItineraryDay; data: Row[] }
  | { kind: 'documents'; data: Row[] };

export default function ManagerItineraryScreen() {
  const trips = useTrips();
  const manualRefresh = useManualRefresh();
  const itinerary = useItinerary(trips.selectedTripId);
  const documents = useCommonDocuments(trips.selectedTripId);
  const [documentError, setDocumentError] = useState<string | null>(null);
  const commonDocuments = useMemo(
    () => documents.data?.items.filter((item) => item.scope === 'common') ?? [],
    [documents.data],
  );
  const sections = useMemo<Section[]>(() => {
    const daySections: Section[] = (itinerary.data?.itinerary?.days ?? []).map((day) => ({
      kind: 'day',
      day,
      data: day.items.map((item) => ({ kind: 'itinerary', value: item })),
    }));
    return [
      ...daySections,
      { kind: 'documents', data: commonDocuments.map((document) => ({ kind: 'document', value: document })) },
    ];
  }, [commonDocuments, itinerary.data]);

  const openDocument = useCallback((document: DocumentWithOfflineState) => {
    if (!document.offline_available || document.metadata_state !== 'ready') return;
    setDocumentError(null);
    router.push({
      pathname: managerDocumentViewerRoute,
      params: { id: document.id, tripId: document.trip_id },
    });
  }, []);

  const renderItem = useCallback(
    ({ item }: SectionListRenderItemInfo<Row, Section>) => {
      if (item.kind === 'itinerary') return <ManagerItineraryItem item={item.value} />;
      const document = item.value;
      const canOpen = document.offline_available && document.metadata_state === 'ready';
      return (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`${canOpen ? 'Open' : 'Unavailable offline'} ${document.display_name}`}
          disabled={!canOpen}
          onPress={() => openDocument(document)}
          style={({ pressed }) => pressed && styles.pressed}>
          <GlassCard style={styles.document}>
            <FileText color={colors.blueDeep} size={22} />
            <View style={styles.documentText}>
              <Text style={styles.itemTitle}>{document.display_name}</Text>
              <Text style={styles.meta}>
                {document.category} · {document.offline ? 'ready offline' : canOpen ? `version ${document.version}` : 'online only'}
              </Text>
            </View>
            {document.offline ? <StatusPill label="Offline" tone="good" /> : null}
          </GlassCard>
        </Pressable>
      );
    },
    [openDocument],
  );

  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.screen}>
      <SectionList<Row, Section>
        sections={sections}
        keyExtractor={(item) => item.value.id}
        renderItem={renderItem}
        renderSectionHeader={renderSectionHeader}
        stickySectionHeadersEnabled={false}
        initialNumToRender={10}
        maxToRenderPerBatch={12}
        windowSize={7}
        refreshControl={(
          <RefreshControl
            refreshing={manualRefresh.isRefreshing}
            onRefresh={() => void manualRefresh.refresh(
              () => Promise.all([trips.refetch(), itinerary.refetch(), documents.refetch()]),
            )}
          />
        )}
        contentContainerStyle={styles.list}
        ListHeaderComponent={
          <View style={styles.header}>
            <PageHeader eyebrow="Selected group" title="Itinerary" subtitle="Published common information only." tone="manager" />
            <TripSwitcher trips={trips.trips} selectedTripId={trips.selectedTripId} onSelect={trips.selectTrip} />
            {itinerary.isPending ? <ContentLoading label="Loading itinerary" /> : null}
            {itinerary.isError ? (
              <ContentError message="This itinerary is not available on the device." onRetry={() => void itinerary.refetch()} />
            ) : null}
            {itinerary.data && !itinerary.data.itinerary ? (
              <ContentEmpty title="Not published" message="Draft itinerary changes remain hidden until staff publish them." />
            ) : null}
          </View>
        }
        ListFooterComponent={
          <View style={styles.footer}>
            {documentError ? <ContentError message={documentError} /> : null}
            {documents.isPending ? <ContentLoading label="Loading common documents" /> : null}
            {documents.isError ? <ContentError message="Common documents are not available on this device." onRetry={() => void documents.refetch()} /> : null}
            {documents.data && commonDocuments.length === 0 ? (
              <ContentEmpty title="No common documents" message="Published travel tips and group PDFs will appear here." />
            ) : null}
          </View>
        }
      />
    </Screen>
  );
}

function renderSectionHeader({ section }: { section: Section }) {
  if (section.kind === 'documents') {
    return <Text accessibilityRole="header" style={styles.sectionTitle}>Common documents</Text>;
  }
  return (
    <View accessibilityRole="header" style={styles.day}>
      <Text style={styles.dayNumber}>Day {section.day.day_number}</Text>
      <Text style={styles.dayTitle}>{section.day.title || section.day.date || 'Schedule'}</Text>
    </View>
  );
}

function ManagerItineraryItem({ item }: { item: ItineraryItem }) {
  return (
    <GlassCard style={styles.item}>
      <Text style={styles.itemTitle}>{item.title}</Text>
      {item.starts_at ? <Text style={styles.meta}>{new Date(item.starts_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</Text> : null}
      {item.location_name ? (
        <View style={styles.location}>
          <MapPin color={colors.greenDeep} size={15} />
          <Text style={styles.meta}>{item.location_name}</Text>
        </View>
      ) : null}
      {item.description ? <Text style={styles.description}>{item.description}</Text> : null}
    </GlassCard>
  );
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 0 },
  list: { paddingHorizontal: spacing.lg, paddingBottom: 104, gap: spacing.sm },
  header: { gap: spacing.lg, paddingBottom: spacing.md },
  footer: { gap: spacing.md, paddingTop: spacing.md },
  day: { gap: 2, paddingTop: spacing.lg, paddingBottom: spacing.sm, backgroundColor: 'rgba(248,253,255,0.97)' },
  dayNumber: { color: colors.greenDeep, fontSize: 12, fontWeight: '900', textTransform: 'uppercase' },
  dayTitle: { color: colors.ink, fontSize: 19, fontWeight: '800' },
  item: { borderRadius: radii.md, gap: spacing.xs, marginBottom: spacing.sm },
  itemTitle: { color: colors.ink, fontSize: 15, fontWeight: '800' },
  meta: { color: colors.inkMuted, fontSize: 12, textTransform: 'capitalize' },
  description: { color: colors.inkMuted, fontSize: 13, lineHeight: 19, marginTop: spacing.xs },
  location: { flexDirection: 'row', alignItems: 'center', gap: spacing.xs },
  sectionTitle: { color: colors.ink, fontSize: 20, fontWeight: '800', paddingTop: spacing.xl, paddingBottom: spacing.sm, backgroundColor: 'rgba(248,253,255,0.97)' },
  document: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderRadius: radii.md, marginBottom: spacing.sm },
  documentText: { flex: 1, gap: 3 },
  pressed: { opacity: 0.7 },
});
