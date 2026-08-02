import { router } from 'expo-router';
import CheckCircle2 from 'lucide-react-native/icons/circle-check-big';
import CloudDownload from 'lucide-react-native/icons/cloud-download';
import FileClock from 'lucide-react-native/icons/file-clock';
import FileText from 'lucide-react-native/icons/file-text';
import LockKeyhole from 'lucide-react-native/icons/lock-keyhole';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View, type ListRenderItem } from 'react-native';

import { ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import {
  cacheDocument,
  prefetchPassengerOfflineDocuments,
  type DocumentWithOfflineState,
} from '@/features/content/data/content-repository';
import {
  passengerDocumentSlots,
  type PassengerDocumentSlot,
} from '@/features/content/data/passenger-document-policy';
import { useDocuments } from '@/features/content/hooks/use-content';
import { useTrips } from '@/features/trips/hooks/use-trips';

type PassengerDocumentUiSlot = Omit<PassengerDocumentSlot, 'documents'> & {
  documents: DocumentWithOfflineState[];
};

export default function PassengerDocumentsScreen() {
  const trips = useTrips();
  const documents = useDocuments(trips.selectedTripId);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [autoCaching, setAutoCaching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const attemptedPrefetch = useRef<string | null>(null);
  const documentItems = useMemo(
    () => (documents.data?.items ?? []) as DocumentWithOfflineState[],
    [documents.data?.items],
  );
  const slots = useMemo(
    () => passengerDocumentSlots(documentItems) as PassengerDocumentUiSlot[],
    [documentItems],
  );
  const staleSignature = useMemo(
    () => documentItems
      .filter((document) => document.metadata_state === 'ready' && document.offline_available && (!document.offline || document.offlineVersion !== document.version))
      .map((document) => `${document.id}:${document.version}`)
      .sort()
      .join('|'),
    [documentItems],
  );

  useEffect(() => {
    const tripId = trips.selectedTripId;
    if (!tripId || autoCaching || !staleSignature || attemptedPrefetch.current === staleSignature) return;
    let active = true;
    attemptedPrefetch.current = staleSignature;
    setAutoCaching(true);
    void prefetchPassengerOfflineDocuments(tripId).then((result) => {
      if (!active) return;
      if (result.completed) void documents.refetch();
      if (result.failed) setError(`${result.failed} document${result.failed === 1 ? '' : 's'} will retry automatically when the connection is ready.`);
    }).finally(() => {
      if (active) setAutoCaching(false);
    });
    return () => {
      active = false;
    };
  }, [autoCaching, documents, staleSignature, trips.selectedTripId]);

  const open = useCallback(async (document: DocumentWithOfflineState) => {
    if (document.metadata_state !== 'ready' || !document.offline_available) return;
    setOpeningId(document.id);
    setError(null);
    try {
      if (!document.offline || document.offlineVersion !== document.version) await cacheDocument(document);
      await documents.refetch();
      router.push({ pathname: '/document/[id]', params: { id: document.id } });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The document could not be secured for offline use.');
    } finally {
      setOpeningId(null);
    }
  }, [documents]);

  const renderSlot = useCallback<ListRenderItem<PassengerDocumentUiSlot>>(({ item: slot }) => (
    <GlassCard style={styles.slotCard}>
      <View style={styles.slotHeading}>
        <View style={styles.slotIcon}><FileText color={colors.greenDeep} size={24} /></View>
        <Text accessibilityRole="header" style={styles.slotTitle}>{slot.title}</Text>
      </View>
      {slot.documents.length ? slot.documents.map((document) => {
        const ready = document.metadata_state === 'ready' && document.offline_available;
        const offlineCurrent = ready && document.offline && document.offlineVersion === document.version;
        return (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={ready ? `Open ${document.display_name}` : `${document.display_name} is being prepared`}
            disabled={!ready || openingId === document.id}
            key={document.id}
            onPress={() => void open(document)}
            style={styles.documentRow}>
            {ready ? <FileText color={colors.inkMuted} size={20} /> : <FileClock color={colors.inkMuted} size={20} />}
            <View style={styles.documentCopy}>
              <Text numberOfLines={2} style={styles.documentName}>{document.display_name}</Text>
              <Text style={styles.documentMeta}>
                {ready ? `Updated ${new Date(document.updated_at).toLocaleDateString()}` : 'Being prepared by your travel team'}
              </Text>
            </View>
            {offlineCurrent ? (
              <CheckCircle2 accessibilityLabel="Available offline" color={colors.greenDeep} size={22} />
            ) : (
              <CloudDownload accessibilityLabel="Downloading encrypted copy" color={colors.inkMuted} size={22} />
            )}
          </Pressable>
        );
      }) : (
        <View style={styles.pendingRow}>
          <FileClock color={colors.inkMuted} size={20} />
          <Text style={styles.pendingMessage}>{slot.pendingMessage}</Text>
        </View>
      )}
    </GlassCard>
  ), [open, openingId]);

  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.screen}>
      <FlatList
        data={slots}
        renderItem={renderSlot}
        keyExtractor={(slot) => slot.id}
        contentContainerStyle={styles.list}
        ItemSeparatorComponent={ListSeparator}
        initialNumToRender={3}
        maxToRenderPerBatch={3}
        windowSize={3}
        ListHeaderComponent={
          <View style={styles.header}>
            <PageHeader eyebrow="Private to you" title="My documents" subtitle="Passport, Visa and Flight Tickets authorized for your passenger identity." />
            <View style={styles.securityNote}>
              <LockKeyhole color={colors.greenDeep} size={18} />
              <Text style={styles.securityText}>Encrypted copies download automatically and remain available without internet.</Text>
            </View>
            {autoCaching ? <ContentLoading label="Securing new documents for offline use" /> : null}
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

function ListSeparator() {
  return <View style={styles.separator} />;
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 0 },
  list: { flexGrow: 1, paddingHorizontal: spacing.lg, paddingBottom: 104 },
  header: { gap: spacing.lg, paddingBottom: spacing.lg },
  separator: { height: spacing.md },
  securityNote: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  securityText: { flex: 1, color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
  slotCard: { borderRadius: radii.md, padding: spacing.md, gap: spacing.sm },
  slotHeading: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  slotIcon: { width: 44, height: 44, borderRadius: 14, backgroundColor: colors.greenSoft, alignItems: 'center', justifyContent: 'center' },
  slotTitle: { flex: 1, color: colors.ink, fontSize: 18, fontWeight: '900' },
  documentRow: { minHeight: 66, flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderTopWidth: 1, borderColor: colors.border, paddingTop: spacing.sm },
  documentCopy: { flex: 1, gap: 3 },
  documentName: { color: colors.ink, fontSize: 14, fontWeight: '800' },
  documentMeta: { color: colors.inkMuted, fontSize: 11 },
  pendingRow: { minHeight: 58, flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderTopWidth: 1, borderColor: colors.border, paddingTop: spacing.sm },
  pendingMessage: { flex: 1, color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
});
