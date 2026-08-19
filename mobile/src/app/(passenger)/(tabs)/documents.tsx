import { router } from 'expo-router';
import CheckCircle2 from 'lucide-react-native/icons/circle-check-big';
import ChevronDown from 'lucide-react-native/icons/chevron-down';
import ChevronRight from 'lucide-react-native/icons/chevron-right';
import CloudDownload from 'lucide-react-native/icons/cloud-download';
import FileClock from 'lucide-react-native/icons/file-clock';
import FileText from 'lucide-react-native/icons/file-text';
import LockKeyhole from 'lucide-react-native/icons/lock-keyhole';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Pressable,
  SectionList,
  StyleSheet,
  Text,
  View,
  type SectionListRenderItemInfo,
} from 'react-native';

import { MOBILE_LIST_WINDOWING } from '@/core/performance/mobile-performance-budgets';
import { useManualRefresh } from '@/core/query/use-manual-refresh';
import { englishMessages, formatInstantDate } from '@/core/localization/date-time';
import { userFacingErrorMessage } from '@/core/errors/user-facing-error';
import { passengerDocumentViewerRoute } from '@/core/navigation/document-viewer-routes';
import { ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import {
  prefetchPassengerOfflineDocuments,
  type DocumentWithOfflineState,
} from '@/features/content/data/content-repository';
import {
  passengerDocumentSlots,
  shouldPrefetchPassengerDocument,
  type PassengerDocumentSlot,
  type PassengerDocumentSlotId,
} from '@/features/content/data/passenger-document-policy';
import { useDocuments } from '@/features/content/hooks/use-content';
import { useTrips } from '@/features/trips/hooks/use-trips';

type PassengerDocumentRow =
  | { kind: 'document'; key: string; document: DocumentWithOfflineState }
  | { kind: 'pending'; key: string; message: string };

type PassengerDocumentUiSlot = Omit<PassengerDocumentSlot, 'documents'> & {
  data: PassengerDocumentRow[];
  itemCount: number;
  expanded: boolean;
};

export default function PassengerDocumentsScreen() {
  const trips = useTrips();
  const selectedTimeZone = trips.selectedTrip?.timeZone;
  const documents = useDocuments(trips.selectedTripId);
  const manualRefresh = useManualRefresh();
  const [error, setError] = useState<string | null>(null);
  const [expandedSlots, setExpandedSlots] = useState<Record<PassengerDocumentSlotId, boolean>>({
    passport: false,
    visa: false,
    flight_ticket: false,
  });
  const attemptedPrefetch = useRef<string | null>(null);
  const automaticRunId = useRef(0);
  const automaticInFlight = useRef<string | null>(null);
  const refetchDocuments = documents.refetch;
  const documentItems = useMemo(
    () => (documents.data?.items ?? []) as DocumentWithOfflineState[],
    [documents.data?.items],
  );
  const slots = useMemo(
    () => passengerDocumentSlots(documentItems).map((slot): PassengerDocumentUiSlot => {
      const { documents: slotDocuments, ...slotMetadata } = slot;
      const rows: PassengerDocumentRow[] = slotDocuments.length
        ? slotDocuments.map((document) => ({
          kind: 'document' as const,
          key: `${slot.id}:${document.id}`,
          document: document as DocumentWithOfflineState,
        }))
        : [{ kind: 'pending' as const, key: `${slot.id}:pending`, message: slot.pendingMessage }];
      return {
        ...slotMetadata,
        data: expandedSlots[slot.id] ? rows : [],
        itemCount: slotDocuments.length,
        expanded: expandedSlots[slot.id],
      };
    }),
    [documentItems, expandedSlots],
  );
  const staleSignature = useMemo(
    () => documentItems
      .filter((document) => shouldPrefetchPassengerDocument(document) && (!document.offline || document.offlineVersion !== document.version))
      .map((document) => `${document.id}:${document.version}`)
      .sort()
      .join('|'),
    [documentItems],
  );

  useEffect(() => {
    const tripId = trips.selectedTripId;
    if (
      !tripId ||
      !staleSignature ||
      attemptedPrefetch.current === staleSignature ||
      automaticInFlight.current === staleSignature
    ) return;
    const currentRun = ++automaticRunId.current;
    attemptedPrefetch.current = staleSignature;
    automaticInFlight.current = staleSignature;
    void prefetchPassengerOfflineDocuments(tripId).then((result) => {
      if (automaticRunId.current !== currentRun) return;
      if (result.completed) void refetchDocuments();
    }).catch(() => {
      // Background preparation is deliberately silent. The initial preparation
      // screen and explicit pull-to-refresh surface honest retry-later warnings.
    }).finally(() => {
      if (automaticInFlight.current === staleSignature) automaticInFlight.current = null;
    });
    return () => {
      if (automaticRunId.current === currentRun) automaticRunId.current += 1;
    };
  }, [refetchDocuments, staleSignature, trips.selectedTripId]);

  const open = useCallback((document: DocumentWithOfflineState) => {
    if (!shouldPrefetchPassengerDocument(document)) return;
    setError(null);
    router.push({
      pathname: passengerDocumentViewerRoute,
      params: { id: document.id, tripId: document.trip_id },
    });
  }, []);

  const refresh = useCallback(async () => {
    setError(null);
    attemptedPrefetch.current = null;
    try {
      await refetchDocuments();
      if (trips.selectedTripId) {
        const result = await prefetchPassengerOfflineDocuments(trips.selectedTripId);
        if (result.failed) {
          setError(`${result.failed} document${result.failed === 1 ? '' : 's'} could not be saved offline yet. Background sync will retry later.`);
        }
        await refetchDocuments();
      }
    } catch (caught) {
      setError(userFacingErrorMessage(caught, 'Documents could not be refreshed yet.'));
    }
  }, [refetchDocuments, trips.selectedTripId]);

  const toggleSlot = useCallback((slotId: PassengerDocumentSlotId) => {
    setExpandedSlots((current) => ({ ...current, [slotId]: !current[slotId] }));
  }, []);

  const renderSlotHeader = useCallback(({ section: slot }: { section: PassengerDocumentUiSlot }) => (
    <Pressable
      testID={`passenger-document-slot-${slot.id}`}
      accessibilityRole="button"
      accessibilityLabel={`${slot.expanded ? 'Collapse' : 'Expand'} ${slot.title} documents`}
      accessibilityState={{ expanded: slot.expanded }}
      onPress={() => toggleSlot(slot.id)}
      style={({ pressed }) => [styles.slotPressable, pressed && styles.slotPressed]}>
      <GlassCard style={styles.slotHeadingCard}>
        <View style={styles.slotHeading}>
          <View style={styles.slotIcon}><FileText color={colors.blueDeep} size={24} /></View>
          <View style={styles.slotCopy}>
            <Text accessibilityRole="header" style={styles.slotTitle}>{slot.title}</Text>
            <Text style={styles.slotMeta}>
              {slot.itemCount ? `${slot.itemCount} ${slot.itemCount === 1 ? 'file' : 'files'}` : 'Awaiting documents'}
            </Text>
          </View>
          {slot.expanded
            ? <ChevronDown color={colors.blueDeep} size={22} />
            : <ChevronRight color={colors.blueDeep} size={22} />}
        </View>
      </GlassCard>
    </Pressable>
  ), [toggleSlot]);

  const renderDocument = useCallback(({
    item,
    index,
    section,
  }: SectionListRenderItemInfo<PassengerDocumentRow, PassengerDocumentUiSlot>) => {
    if (item.kind === 'pending') {
      return (
        <View style={styles.pendingRow}>
          <FileClock color={colors.inkMuted} size={20} />
          <Text style={styles.pendingMessage}>{item.message}</Text>
        </View>
      );
    }

    const { document } = item;
    const openable = shouldPrefetchPassengerDocument(document);
    const ready = document.metadata_state === 'ready' && document.offline_available;
    const offlineCurrent = ready && document.offline && document.offlineVersion === document.version;
    return (
      <Pressable
        testID={`passenger-document-${section.id}-${index}`}
        accessibilityRole="button"
        accessibilityLabel={openable ? `Open ${document.display_name}` : `${document.display_name} is being prepared`}
        disabled={!openable}
        onPress={() => open(document)}
        style={styles.documentRow}>
        {ready ? <FileText color={colors.inkMuted} size={20} /> : <FileClock color={colors.inkMuted} size={20} />}
        <View style={styles.documentCopy}>
          <Text numberOfLines={2} style={styles.documentName}>{document.display_name}</Text>
          <Text style={styles.documentMeta}>
            {ready
              ? englishMessages.updatedOn(formatInstantDate(
                document.updated_at,
                { timeZone: selectedTimeZone },
              ))
              : openable
                ? 'Tap to securely prepare and open'
                : 'Being prepared by your travel team'}
          </Text>
        </View>
        {offlineCurrent ? (
          <CheckCircle2 accessibilityLabel="Available offline" color={colors.greenDeep} size={22} />
        ) : (
          <CloudDownload accessibilityLabel="Downloading for offline use" color={colors.inkMuted} size={22} />
        )}
      </Pressable>
    );
  }, [open, selectedTimeZone]);

  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.screen}>
      <SectionList<PassengerDocumentRow, PassengerDocumentUiSlot>
        testID="passenger-documents-list"
        sections={slots}
        renderItem={renderDocument}
        renderSectionHeader={renderSlotHeader}
        keyExtractor={(item) => item.key}
        stickySectionHeadersEnabled={false}
        contentContainerStyle={styles.list}
        {...MOBILE_LIST_WINDOWING.compactInteractive}
        refreshing={manualRefresh.isRefreshing}
        onRefresh={() => void manualRefresh.refresh(refresh)}
        ListHeaderComponent={
          <View style={styles.header}>
            <PageHeader eyebrow="Private to you" title="My documents" subtitle="Passport, Visa and Flight Tickets authorized for your passenger identity." tone="passenger" />
            <View style={styles.securityNote}>
              <LockKeyhole color={colors.greenDeep} size={18} />
              <Text style={styles.securityText}>Documents are prepared automatically and remain available without internet.</Text>
            </View>
            {error ? <ContentError message={error} /> : null}
            {documents.isPending ? <ContentLoading label="Checking documents" /> : null}
            {documents.isError ? (
              <ContentError message="Documents have not been synchronized on this device." onRetry={() => void documents.refetch()} />
            ) : null}
          </View>
        }
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 0 },
  list: { flexGrow: 1, paddingHorizontal: spacing.lg, paddingBottom: 104 },
  header: { gap: spacing.lg, paddingBottom: spacing.lg },
  securityNote: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  securityText: { flex: 1, color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
  slotPressable: { marginTop: spacing.md, borderRadius: radii.md },
  slotPressed: { opacity: 0.94, transform: [{ scale: 0.99 }] },
  slotHeadingCard: { borderRadius: radii.md, padding: spacing.md },
  slotHeading: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  slotIcon: { width: 44, height: 44, borderRadius: 14, backgroundColor: colors.blueSoft, alignItems: 'center', justifyContent: 'center' },
  slotCopy: { flex: 1, gap: 2 },
  slotTitle: { flex: 1, color: colors.ink, fontSize: 18, fontWeight: '900' },
  slotMeta: { color: colors.inkMuted, fontSize: 11, fontWeight: '700' },
  documentRow: {
    minHeight: 66,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    borderRadius: radii.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    marginTop: spacing.sm,
    padding: spacing.md,
  },
  documentCopy: { flex: 1, gap: 3 },
  documentName: { color: colors.ink, fontSize: 14, fontWeight: '800' },
  documentMeta: { color: colors.inkMuted, fontSize: 11 },
  pendingRow: {
    minHeight: 58,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    borderRadius: radii.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    backgroundColor: colors.surface,
    marginTop: spacing.sm,
    padding: spacing.md,
  },
  pendingMessage: { flex: 1, color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
});
