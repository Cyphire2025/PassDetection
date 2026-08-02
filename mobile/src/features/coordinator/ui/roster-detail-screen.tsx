import { useCallback, useMemo } from 'react';
import { FlatList, StyleSheet, Text, View, type ListRenderItem } from 'react-native';

import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import type { CoordinatorPassenger } from '@/features/coordinator/api/coordinator-contracts';
import { useCoordinatorRoster } from '@/features/coordinator/hooks/use-coordinator';
import { OperationHeader } from '@/features/coordinator/ui/operation-header';
import { useTrips } from '@/features/trips/hooks/use-trips';

export function RosterDetailScreen({ mode }: { mode: 'rooming' | 'meals' }) {
  const trips = useTrips();
  const roster = useCoordinatorRoster(trips.selectedTripId, '');
  const passengers = useMemo(
    () => roster.data?.pages.flatMap((page) => page.items) ?? [],
    [roster.data],
  );
  const filtered = useMemo(
    () =>
      passengers.filter((passenger) =>
        mode === 'rooming' ? passenger.room_number : passenger.meal_preference,
      ),
    [mode, passengers],
  );
  const renderItem = useCallback<ListRenderItem<CoordinatorPassenger>>(
    ({ item }) => (
      <GlassCard style={styles.card}>
        <Text style={styles.name}>{item.display_name}</Text>
        <Text style={styles.value}>
          {mode === 'rooming' ? `Room ${item.room_number}` : item.meal_preference}
        </Text>
      </GlassCard>
    ),
    [mode],
  );
  const loadNext = useCallback(() => {
    if (roster.hasNextPage && !roster.isFetchingNextPage) void roster.fetchNextPage();
  }, [roster]);

  return (
    <Screen scroll={false} bottomInset={96} contentStyle={styles.screen}>
      <OperationHeader
        title={mode === 'rooming' ? 'Rooming' : 'Meals'}
        subtitle={`${trips.selectedTrip?.name || 'Selected trip'} · synchronized roster`}
      />
      <FlatList
        data={filtered}
        renderItem={renderItem}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.list}
        ItemSeparatorComponent={ListSeparator}
        initialNumToRender={12}
        maxToRenderPerBatch={16}
        windowSize={7}
        removeClippedSubviews
        onEndReached={loadNext}
        onEndReachedThreshold={0.6}
        ListHeaderComponent={
          <>
            {roster.isPending ? <ContentLoading label={`Loading ${mode}`} /> : null}
            {roster.isError ? (
              <ContentError
                message={`No ${mode} copy is available offline.`}
                onRetry={() => void roster.refetch()}
              />
            ) : null}
          </>
        }
        ListEmptyComponent={
          !roster.isPending && !roster.isError ? (
            <ContentEmpty
              title={`No ${mode} details loaded`}
              message={
                roster.hasNextPage
                  ? 'Load the next roster page to continue checking assignments.'
                  : 'Assignments will appear after the roster synchronizes.'
              }
            />
          ) : null
        }
        ListFooterComponent={
          roster.hasNextPage ? (
            <View style={styles.footer}>
              <PrimaryButton
                label="Load more"
                tone="secondary"
                loading={roster.isFetchingNextPage}
                onPress={loadNext}
              />
            </View>
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
  screen: { gap: spacing.md },
  list: { flexGrow: 1, paddingBottom: spacing.md },
  separator: { height: spacing.sm },
  footer: { paddingTop: spacing.md },
  card: { borderRadius: radii.md, padding: spacing.md, gap: 3 },
  name: { color: colors.ink, fontSize: 15, fontWeight: '800' },
  value: { color: colors.inkMuted, fontSize: 13 },
});
