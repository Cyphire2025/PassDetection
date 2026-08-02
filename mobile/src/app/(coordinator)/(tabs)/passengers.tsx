import { useDeferredValue, useMemo, useState } from 'react';
import { FlatList, RefreshControl, StyleSheet, Text, View } from 'react-native';

import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { StatusPill } from '@/design/components/status-pill';
import { TextField } from '@/design/components/text-field';
import { colors, radii, spacing } from '@/design/theme';
import { useCoordinatorRoster } from '@/features/coordinator/hooks/use-coordinator';
import type { CoordinatorPassenger } from '@/features/coordinator/api/coordinator-contracts';
import { useTrips } from '@/features/trips/hooks/use-trips';
import { TripSwitcher } from '@/features/trips/ui/trip-switcher';

export default function CoordinatorPassengersScreen() {
  const trips = useTrips();
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search.trim());
  const roster = useCoordinatorRoster(trips.selectedTripId, deferredSearch);
  const pages = roster.data?.pages;
  const passengers = useMemo(() => {
    const byId = new Map<string, CoordinatorPassenger>();
    for (const page of pages ?? []) {
      for (const passenger of page.items) byId.set(passenger.id, passenger);
    }
    return [...byId.values()];
  }, [pages]);
  const offline = roster.data?.pages.some((page) => page.offline) ?? false;

  return (
    <Screen scroll={false} bottomInset={96} contentStyle={styles.screen}>
      <PageHeader
        eyebrow="Operations"
        title="Passengers"
        subtitle="Search the bounded, account-isolated roster."
        accessory={offline ? <StatusPill label="Offline copy" tone="warning" /> : undefined}
      />
      <TripSwitcher trips={trips.trips} selectedTripId={trips.selectedTripId} onSelect={trips.selectTrip} />
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
        initialNumToRender={16}
        maxToRenderPerBatch={24}
        windowSize={7}
        removeClippedSubviews
        contentContainerStyle={styles.list}
        refreshControl={<RefreshControl refreshing={roster.isRefetching} onRefresh={() => void roster.refetch()} />}
        onEndReachedThreshold={0.5}
        onEndReached={() => {
          if (roster.hasNextPage && !roster.isFetchingNextPage) void roster.fetchNextPage();
        }}
        ListEmptyComponent={!roster.isPending && !roster.isError ? (
          <ContentEmpty title="No passengers found" message={deferredSearch ? 'Try a different search.' : 'The roster is currently empty.'} />
        ) : null}
        ListFooterComponent={roster.isFetchingNextPage ? <ContentLoading label="Loading more passengers" /> : null}
        renderItem={({ item }) => (
          <GlassCard style={styles.card}>
            <View style={styles.passengerText}>
              <Text style={styles.name}>{item.display_name}</Text>
              <Text style={styles.meta}>{item.employee_code || 'No employee code'}</Text>
              <Text style={styles.meta} numberOfLines={1}>
                {item.room_number ? `Room ${item.room_number}` : 'Room pending'} · {item.meal_preference || 'Meal pending'}
              </Text>
            </View>
            <StatusPill
              label={item.attendance_status.replace('_', ' ')}
              tone={item.attendance_status === 'present' ? 'good' : item.attendance_status === 'missing' ? 'warning' : 'neutral'}
            />
          </GlassCard>
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
  name: { color: colors.ink, fontSize: 15, fontWeight: '800' },
  meta: { color: colors.inkMuted, fontSize: 11, textTransform: 'capitalize' },
});
