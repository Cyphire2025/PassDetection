import { router } from 'expo-router';
import CheckCircle2 from 'lucide-react-native/icons/circle-check-big';
import CloudDownload from 'lucide-react-native/icons/cloud-download';
import FileClock from 'lucide-react-native/icons/file-clock';
import FileText from 'lucide-react-native/icons/file-text';
import LockKeyhole from 'lucide-react-native/icons/lock-keyhole';
import { useCallback, useMemo, useState } from 'react';
import { FlatList, Pressable, StyleSheet, Text, View, type ListRenderItem } from 'react-native';

import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { StatusPill } from '@/design/components/status-pill';
import { colors, radii, spacing } from '@/design/theme';
import { cacheDocument, type DocumentWithOfflineState } from '@/features/content/data/content-repository';
import { useDocuments } from '@/features/content/hooks/use-content';
import { useTrips } from '@/features/trips/hooks/use-trips';

export default function PassengerDocumentsScreen() {
  const trips = useTrips();
  const documents = useDocuments(trips.selectedTripId);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const personalDocuments = useMemo(
    () => documents.data?.items.filter((document) => document.scope === 'personal') ?? [],
    [documents.data],
  );

  const open = useCallback(async (document: DocumentWithOfflineState) => {
    if (document.metadata_state !== 'ready' || !document.offline_available) return;
    setDownloading(document.id);
    setError(null);
    try {
      if (!document.offline || document.offlineVersion !== document.version) await cacheDocument(document);
      await documents.refetch();
      router.push({ pathname: '/document/[id]', params: { id: document.id } });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The document could not be secured for offline use.');
    } finally {
      setDownloading(null);
    }
  }, [documents]);

  const renderItem = useCallback<ListRenderItem<DocumentWithOfflineState>>(({ item: document }) => {
    const ready = document.metadata_state === 'ready' && document.offline_available;
    const offlineCurrent = ready && document.offline && document.offlineVersion === document.version;
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={ready ? `Open ${document.display_name}` : `${document.display_name} is being prepared`}
        disabled={!ready || downloading === document.id}
        onPress={() => void open(document)}>
        <GlassCard style={[styles.documentCard, !ready && styles.documentPending]}>
          <View style={styles.iconBox}>
            {ready ? <FileText color={colors.blueDeep} size={24} /> : <FileClock color={colors.inkMuted} size={24} />}
          </View>
          <View style={styles.documentText}>
            <Text style={styles.category}>{document.category.replaceAll('_', ' ')}</Text>
            <Text numberOfLines={2} style={styles.documentTitle}>{document.display_name}</Text>
            <Text style={styles.updated}>
              {ready ? `Updated ${new Date(document.updated_at).toLocaleDateString()}` : 'Secure metadata is being prepared'}
            </Text>
          </View>
          {downloading === document.id ? (
            <StatusPill label="Securing…" />
          ) : offlineCurrent ? (
            <CheckCircle2 accessibilityLabel="Available offline" color={colors.greenDeep} size={23} />
          ) : ready ? (
            <CloudDownload accessibilityLabel="Download encrypted offline copy" color={colors.inkMuted} size={23} />
          ) : (
            <StatusPill label="Pending" tone="warning" />
          )}
        </GlassCard>
      </Pressable>
    );
  }, [downloading, open]);

  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.screen}>
      <FlatList
        data={personalDocuments}
        renderItem={renderItem}
        keyExtractor={(document) => document.id}
        contentContainerStyle={styles.list}
        ItemSeparatorComponent={ListSeparator}
        initialNumToRender={10}
        maxToRenderPerBatch={12}
        windowSize={7}
        ListHeaderComponent={
          <View style={styles.header}>
            <PageHeader eyebrow="Private to you" title="My documents" subtitle="Only documents authorized for your passenger identity appear here." />
            <View style={styles.securityNote}>
              <LockKeyhole color={colors.greenDeep} size={18} />
              <Text style={styles.securityText}>Offline copies are encrypted and stay inside Group Companion.</Text>
            </View>
            {error ? <ContentError message={error} /> : null}
            {documents.isPending ? <ContentLoading label="Checking documents" /> : null}
            {documents.isError ? (
              <ContentError message="Documents have not been synchronized on this device." onRetry={() => void documents.refetch()} />
            ) : null}
          </View>
        }
        ListEmptyComponent={
          documents.data && !documents.isPending ? (
            <ContentEmpty title="No documents available" message="New personal documents will appear after your travel team publishes them." />
          ) : null
        }
        ListFooterComponent={
          documents.data?.offline ? (
            <View style={styles.footer}><StatusPill label="Showing the last offline document list" tone="warning" /></View>
          ) : null
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
  header: { gap: spacing.lg, paddingBottom: spacing.md },
  footer: { paddingTop: spacing.lg },
  separator: { height: spacing.sm },
  securityNote: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  securityText: { flex: 1, color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
  documentCard: { borderRadius: radii.md, padding: spacing.md, flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  documentPending: { opacity: 0.72 },
  iconBox: { width: 46, height: 46, borderRadius: 15, backgroundColor: colors.blueSoft, alignItems: 'center', justifyContent: 'center' },
  documentText: { flex: 1, gap: 2 },
  category: { color: colors.greenDeep, fontSize: 10, fontWeight: '900', textTransform: 'uppercase' },
  documentTitle: { color: colors.ink, fontSize: 15, fontWeight: '800' },
  updated: { color: colors.inkMuted, fontSize: 11 },
});
