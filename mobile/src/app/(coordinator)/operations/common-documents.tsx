import { useFocusEffect, useRouter } from 'expo-router';
import ChevronRight from 'lucide-react-native/icons/chevron-right';
import FileText from 'lucide-react-native/icons/file-text';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Pressable, SectionList, StyleSheet, Text, View } from 'react-native';

import { syncTrip } from '@/core/sync/sync-service';
import { ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import {
  coordinatorDocumentCategoryLabel,
  coordinatorDocumentCategoryOrder,
} from '@/features/coordinator/data/coordinator-view-policy';
import { useCoordinatorTrips } from '@/features/coordinator/hooks/use-coordinator-trips';
import { OperationHeader } from '@/features/coordinator/ui/operation-header';
import {
  cacheDocument,
  type DocumentWithOfflineState,
} from '@/features/content/data/content-repository';
import { useCommonDocuments } from '@/features/content/hooks/use-content';

type DocumentSection = {
  category: string;
  title: string;
  data: DocumentWithOfflineState[];
};

export default function CoordinatorCommonDocumentsScreen() {
  const router = useRouter();
  const trips = useCoordinatorTrips();
  const documents = useCommonDocuments(trips.selectedTripId);
  const refetchDocuments = documents.refetch;
  const [opening, setOpening] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const items = useMemo(
    () => documents.data?.items.filter((item) => item.scope === 'common') ?? [],
    [documents.data],
  );
  const sections = useMemo<DocumentSection[]>(() => {
    const grouped = new Map<string, DocumentWithOfflineState[]>();
    for (const document of items) {
      const group = grouped.get(document.category) ?? [];
      group.push(document);
      grouped.set(document.category, group);
    }
    const categories = [...grouped.keys()]
      .filter((category) => category !== 'itinerary_pdf')
      .sort((left, right) => {
        const order = coordinatorDocumentCategoryOrder(left) - coordinatorDocumentCategoryOrder(right);
        return order || left.localeCompare(right);
      });
    return [
      {
        category: 'itinerary_pdf',
        title: 'Itinerary',
        data: grouped.get('itinerary_pdf') ?? [],
      },
      ...categories.map((category) => ({
        category,
        title: coordinatorDocumentCategoryLabel(category),
        data: grouped.get(category) ?? [],
      })),
    ];
  }, [items]);

  useFocusEffect(useCallback(() => {
    const tripId = trips.selectedTripId;
    if (!tripId) return;
    let active = true;
    void syncTrip(tripId)
      .catch(() => undefined)
      .then(() => {
        if (active) return refetchDocuments();
        return undefined;
      });
    return () => {
      active = false;
    };
  }, [refetchDocuments, trips.selectedTripId]));

  useEffect(() => {
    const pending = items.filter(
      (document) =>
        document.offline_available &&
        document.metadata_state === 'ready' &&
        (!document.offline || document.offlineVersion !== document.version),
    );
    if (pending.length === 0) return;
    let cancelled = false;
    void (async () => {
      let cursor = 0;
      const worker = async () => {
        while (!cancelled && cursor < pending.length) {
          const index = cursor;
          cursor += 1;
          const document = pending[index];
          if (document) await cacheDocument(document);
        }
      };
      await Promise.all(Array.from({ length: Math.min(3, pending.length) }, () => worker()));
    })().catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [items]);

  const openDocument = useCallback(async (document: DocumentWithOfflineState) => {
    if (!document.offline_available || document.metadata_state !== 'ready') return;
    setOpening(document.id);
    setError(null);
    try {
      await cacheDocument(document);
      router.push({ pathname: '/document/[id]', params: { id: document.id } });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'The document could not be opened securely.');
    } finally {
      setOpening(null);
    }
  }, [router]);

  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.screen}>
      <SectionList<DocumentWithOfflineState, DocumentSection>
        sections={sections}
        keyExtractor={(document) => document.id}
        stickySectionHeadersEnabled={false}
        initialNumToRender={8}
        maxToRenderPerBatch={12}
        windowSize={5}
        contentContainerStyle={styles.list}
        ListHeaderComponent={
          <View style={styles.header}>
            <OperationHeader title="Common Documents" subtitle={trips.selectedTrip?.name || 'Selected group'} />
            {documents.isPending ? <ContentLoading label="Loading common documents" /> : null}
            {documents.isError ? (
              <ContentError message="Common documents are not available on this device." onRetry={() => void documents.refetch()} />
            ) : null}
            {error ? <ContentError message={error} /> : null}
          </View>
        }
        renderSectionHeader={({ section }) => (
          <View style={styles.sectionHeader}>
            <Text accessibilityRole="header" style={styles.sectionTitle}>{section.title}</Text>
            {section.data.length === 0 ? (
              <GlassCard style={styles.emptyCard}>
                <Text style={styles.emptyText}>
                  {section.category === 'itinerary_pdf'
                    ? 'The itinerary PDF has not been published yet.'
                    : `No ${section.title.toLowerCase()} document is currently published.`}
                </Text>
              </GlassCard>
            ) : null}
          </View>
        )}
        renderItem={({ item }) => {
          const available = item.offline_available && item.metadata_state === 'ready';
          return (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={`Open ${item.display_name}`}
              disabled={!available || opening === item.id}
              onPress={() => void openDocument(item)}
              style={({ pressed }) => pressed && styles.pressed}>
              <GlassCard style={styles.documentCard}>
                <View style={styles.icon}><FileText color={colors.greenDeep} size={22} /></View>
                <View style={styles.documentText}>
                  <Text style={styles.documentTitle}>{item.display_name}</Text>
                  <Text style={styles.documentMeta}>
                    {opening === item.id ? 'Opening securely…' : `Version ${item.version}`}
                  </Text>
                </View>
                <ChevronRight color={colors.inkMuted} size={20} />
              </GlassCard>
            </Pressable>
          );
        }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 0 },
  list: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xxl },
  header: { gap: spacing.md, paddingBottom: spacing.sm },
  sectionHeader: { gap: spacing.sm, paddingTop: spacing.lg, paddingBottom: spacing.sm },
  sectionTitle: { color: colors.ink, fontSize: 21, fontWeight: '900' },
  emptyCard: { padding: spacing.md, borderRadius: radii.md },
  emptyText: { color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
  documentCard: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
    marginBottom: spacing.sm,
    padding: spacing.md,
    borderRadius: radii.md,
  },
  icon: {
    width: 44,
    height: 44,
    borderRadius: 16,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.greenSoft,
  },
  documentText: { flex: 1, gap: 3 },
  documentTitle: { color: colors.ink, fontSize: 15, fontWeight: '800' },
  documentMeta: { color: colors.inkMuted, fontSize: 12 },
  pressed: { opacity: 0.68 },
});
