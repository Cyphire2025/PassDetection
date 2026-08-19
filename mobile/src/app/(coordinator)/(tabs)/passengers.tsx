import { useRouter } from 'expo-router';
import AlertTriangle from 'lucide-react-native/icons/triangle-alert';
import ChevronRight from 'lucide-react-native/icons/chevron-right';
import { useMemo, useState } from 'react';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';

import { MOBILE_LIST_WINDOWING } from '@/core/performance/mobile-performance-budgets';
import { useManualRefresh } from '@/core/query/use-manual-refresh';
import { useDebouncedValue } from '@/core/query/use-debounced-value';
import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { TextField } from '@/design/components/text-field';
import { colors, radii, spacing } from '@/design/theme';
import type { CoordinatorPassenger } from '@/features/coordinator/api/coordinator-contracts';
import { useCoordinatorRoster } from '@/features/coordinator/hooks/use-coordinator';
import { useCoordinatorTrips } from '@/features/coordinator/hooks/use-coordinator-trips';

export default function CoordinatorPassengersScreen() {
  const router = useRouter();
  const manualRefresh = useManualRefresh();
  const trips = useCoordinatorTrips();
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebouncedValue(search.trim());
  const roster = useCoordinatorRoster(trips.selectedTripId, debouncedSearch);
  const pages = roster.data?.pages;
  const passengers = useMemo(() => {
    const byId = new Map<string, CoordinatorPassenger>();
    for (const page of pages ?? []) {
      for (const passenger of page.items) byId.set(passenger.id, passenger);
    }
    return [...byId.values()];
  }, [pages]);

  return (
    <Screen scroll={false} bottomInset={96} contentStyle={styles.screen}>
      <PageHeader
        eyebrow="Operations"
        title="Passengers"
        subtitle={trips.selectedTrip?.name || 'Selected group roster'}
        tone="coordinator"
      />
      <TextField
        label="Passenger search"
        value={search}
        onChangeText={setSearch}
        placeholder="Name or employee code"
        autoCorrect={false}
        returnKeyType="search"
      />
      {roster.isPending ? <ContentLoading label="Loading passenger roster" /> : null}
      {roster.isError ? (
        <ContentError message="This roster has not been synchronized on the device." onRetry={() => void roster.refetch()} />
      ) : null}
      <FlatList
        data={passengers}
        keyExtractor={(item) => item.id}
        keyboardShouldPersistTaps="handled"
        {...MOBILE_LIST_WINDOWING.denseRoster}
        contentContainerStyle={styles.list}
        refreshControl={(
          <RefreshControl
            refreshing={manualRefresh.isRefreshing}
            onRefresh={() => void manualRefresh.refresh(roster.refreshFirstPage)}
          />
        )}
        onEndReachedThreshold={0.5}
        onEndReached={() => {
          if (roster.hasNextPage && !roster.isFetchingNextPage) void roster.fetchNextPage();
        }}
        ListEmptyComponent={!roster.isPending && !roster.isError ? (
          <ContentEmpty title="No passengers found" message={debouncedSearch ? 'Try a different search.' : 'The roster is currently empty.'} />
        ) : null}
        ListFooterComponent={roster.isFetchingNextPage ? <ContentLoading label="Loading more passengers" /> : null}
        renderItem={({ item }) => (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`View details for ${item.display_name}`}
            onPress={() => router.push({ pathname: '/(coordinator)/operations/passenger/[id]', params: { id: item.id } })}
            style={({ pressed }) => pressed && styles.pressed}>
            <GlassCard style={styles.card}>
              <View style={styles.passengerText}>
                <View style={styles.nameRow}>
                  <Text style={styles.name}>{item.display_name}</Text>
                  {item.has_alert ? <AlertTriangle color={colors.warning} size={17} /> : null}
                </View>
                <Text style={styles.meta}>{item.employee_code || 'No employee code'}</Text>
                <Text style={styles.viewDetails}>View details</Text>
              </View>
              <ChevronRight color={colors.inkMuted} size={20} />
            </GlassCard>
          </Pressable>
        )}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { gap: spacing.md },
  list: { gap: spacing.sm, paddingTop: spacing.xs, paddingBottom: spacing.lg },
  card: { borderRadius: radii.md, flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.md },
  passengerText: { flex: 1, gap: 2 },
  nameRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  name: { flexShrink: 1, color: colors.ink, fontSize: 15, fontWeight: '800' },
  meta: { color: colors.inkMuted, fontSize: 11 },
  viewDetails: { color: colors.greenDeep, fontSize: 12, fontWeight: '800', marginTop: spacing.xs },
  pressed: { opacity: 0.68 },
});
