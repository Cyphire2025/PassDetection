import { useLocalSearchParams, useRouter } from 'expo-router';
import ChevronRight from 'lucide-react-native/icons/chevron-right';
import Search from 'lucide-react-native/icons/search';
import { useMemo, useState } from 'react';
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

import { MOBILE_LIST_WINDOWING } from '@/core/performance/mobile-performance-budgets';
import { useDebouncedValue } from '@/core/query/use-debounced-value';
import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import type { ManagerPassenger } from '@/features/manager/api/manager-contracts';
import type { ManagerDocumentMode } from '@/features/manager/data/manager-operations';
import { useManagerRoster } from '@/features/manager/hooks/use-manager-operations';
import { useTrips } from '@/features/trips/hooks/use-trips';
import { OperationHeader } from '@/features/coordinator/ui/operation-header';

function documentMode(value: string | string[] | undefined): ManagerDocumentMode {
  const candidate = Array.isArray(value) ? value[0] : value;
  return candidate === 'visa' || candidate === 'flight_ticket' ? candidate : 'all';
}

export default function ManagerPassengersScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ mode?: string | string[] }>();
  const mode = documentMode(params.mode);
  const trips = useTrips();
  const [search, setSearch] = useState('');
  const debouncedSearch = useDebouncedValue(search.trim());
  const roster = useManagerRoster(trips.selectedTripId, debouncedSearch);
  const passengers = useMemo(
    () => roster.data?.pages.flatMap((page) => page.items) ?? [],
    [roster.data?.pages],
  );
  const title = mode === 'visa'
    ? 'Passenger visas'
    : mode === 'flight_ticket'
      ? 'Flight tickets'
      : 'All passengers';

  const openPassenger = (passenger: ManagerPassenger) => {
    if (mode === 'all') {
      router.push({
        pathname: '/(manager)/operations/passenger/[id]',
        params: { id: passenger.id },
      });
      return;
    }
    router.push({
      pathname: '/(manager)/operations/preview',
      params: {
        tripId: trips.selectedTripId!,
        passengerId: passenger.id,
        documentType: mode,
        title: `${passenger.display_name} · ${mode === 'visa' ? 'Visa' : 'Flight ticket'}`,
      },
    });
  };

  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.screen}>
      <FlatList
        data={passengers}
        keyExtractor={(item) => item.id}
        renderItem={({ item }) => {
          const available = mode === 'all'
            || (mode === 'visa' ? item.visa_status : item.flight_ticket_status) === 'available';
          return (
            <Pressable
              accessibilityRole="button"
              accessibilityState={{ disabled: !available }}
              accessibilityLabel={`${item.display_name}, ${available ? 'available' : 'not available'}`}
              disabled={!available}
              onPress={() => openPassenger(item)}
              style={({ pressed }) => pressed && styles.pressed}>
              <GlassCard style={styles.row}>
                <View style={styles.rowText}>
                  <Text style={styles.name}>{item.display_name}</Text>
                  <Text style={[styles.meta, !available && styles.unavailable]}>
                    {mode === 'all'
                      ? item.employee_code || 'Employee code not provided'
                      : available
                        ? 'Available · tap to preview from server'
                        : 'Not available'}
                  </Text>
                </View>
                {available ? <ChevronRight color={colors.inkMuted} size={20} /> : null}
              </GlassCard>
            </Pressable>
          );
        }}
        contentContainerStyle={styles.list}
        {...MOBILE_LIST_WINDOWING.detail}
        onEndReachedThreshold={0.35}
        onEndReached={() => {
          if (roster.hasNextPage && !roster.isFetchingNextPage) void roster.fetchNextPage();
        }}
        refreshControl={(
          <RefreshControl refreshing={roster.isRefetching} onRefresh={() => void roster.refetch()} />
        )}
        ListHeaderComponent={(
          <View style={styles.header}>
            <OperationHeader title={title} subtitle={trips.selectedTrip?.name || 'Selected group'} />
            <View style={styles.searchBox}>
              <Search color={colors.inkMuted} size={19} />
              <TextInput
                accessibilityLabel="Search passengers"
                autoCapitalize="words"
                autoCorrect={false}
                placeholder="Search passenger or employee code"
                placeholderTextColor={colors.inkMuted}
                value={search}
                onChangeText={setSearch}
                style={styles.input}
              />
            </View>
            {roster.isPending ? <ContentLoading label="Loading passengers" /> : null}
            {roster.isError ? (
              <ContentError message="The passenger list could not be loaded." onRetry={() => void roster.refetch()} />
            ) : null}
            {!roster.isPending && !roster.isError && passengers.length === 0 ? (
              <ContentEmpty title="No passengers found" message="Try another search or refresh this group." />
            ) : null}
          </View>
        )}
        ListFooterComponent={roster.isFetchingNextPage ? <ContentLoading label="Loading more passengers" /> : null}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 0 },
  list: { gap: spacing.sm, paddingHorizontal: spacing.lg, paddingBottom: spacing.xxl },
  header: { gap: spacing.md, paddingBottom: spacing.sm },
  searchBox: {
    minHeight: 52,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: radii.md,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: colors.border,
    backgroundColor: colors.surface,
  },
  input: { flex: 1, color: colors.ink, fontSize: 14 },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, borderRadius: radii.md },
  rowText: { flex: 1, gap: 4 },
  name: { color: colors.ink, fontSize: 15, fontWeight: '800' },
  meta: { color: colors.greenDeep, fontSize: 12, fontWeight: '700' },
  unavailable: { color: colors.inkMuted },
  pressed: { opacity: 0.7, transform: [{ scale: 0.99 }] },
});
