import { router, useLocalSearchParams } from 'expo-router';
import MapPin from 'lucide-react-native/icons/map-pin';
import Search from 'lucide-react-native/icons/search';
import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState, type ReactElement } from 'react';
import {
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  Text,
  TextInput,
  View,
  type ListRenderItem,
} from 'react-native';

import { formatCalendarDate } from '@/core/localization/date-time';
import { MOBILE_LIST_WINDOWING } from '@/core/performance/mobile-performance-budgets';
import { useManualRefresh } from '@/core/query/use-manual-refresh';
import { userFacingErrorMessage } from '@/core/errors/user-facing-error';
import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { RequiredDownloadScreen } from '@/design/components/required-download-screen';
import { Screen } from '@/design/components/screen';
import { colors, radii, spacing } from '@/design/theme';
import type { PassengerPreloadProgress } from '@/features/content/data/passenger-preload';
import type { Trip } from '@/features/trips/model/trip';
import { useTrips } from '@/features/trips/hooks/use-trips';
import { passengerTripDestination } from '@/features/trips/data/passenger-trip-selection';
import { switchToPassengerTrip } from '@/features/trips/data/passenger-trip-switch';

const INITIAL_PROGRESS: PassengerPreloadProgress = {
  percent: 0,
  message: 'Preparing secure offline access',
  completedLabel: 'Starting download',
};

export default function PassengerTripSelectionScreen(): ReactElement {
  const params = useLocalSearchParams<{ tripId?: string | string[]; next?: string | string[] }>();
  const trips = useTrips();
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search.trim().toLocaleLowerCase());
  const [switchingTripId, setSwitchingTripId] = useState<string | null>(null);
  const [blockingTripId, setBlockingTripId] = useState<string | null>(null);
  const [progress, setProgress] = useState(INITIAL_PROGRESS);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const automaticAttempt = useRef<string | null>(null);
  const activeAttempt = useRef<string | null>(null);
  const requestedTripId = typeof params.tripId === 'string' ? params.tripId : params.tripId?.[0] ?? null;
  const requestedDestination = passengerTripDestination(
    typeof params.next === 'string' ? params.next : params.next?.[0],
  );
  const refreshTrips = trips.refetch;
  const manualRefreshTask = useCallback(async () => {
    await refreshTrips();
  }, [refreshTrips]);
  const manualRefresh = useManualRefresh();

  const filteredTrips = useMemo(() => {
    const matching = deferredSearch ? trips.trips.filter((trip) =>
      [trip.name, trip.destination, trip.travelDate]
        .filter(Boolean)
        .some((value) => value?.toLocaleLowerCase().includes(deferredSearch)),
    ) : trips.trips;
    if (!trips.selectedTripId) return matching;
    return [...matching].sort((left, right) => {
      if (left.id === trips.selectedTripId) return -1;
      if (right.id === trips.selectedTripId) return 1;
      return 0;
    });
  }, [deferredSearch, trips.selectedTripId, trips.trips]);

  const prepareTrip = useCallback(async (tripId: string) => {
    if (activeAttempt.current) return;
    activeAttempt.current = tripId;
    setSwitchingTripId(tripId);
    setSelectionError(null);
    setProgress(INITIAL_PROGRESS);
    try {
      await switchToPassengerTrip({
        tripId,
        trips: trips.trips,
        onProgress: setProgress,
        // Only an unprepared trip owns a blocking download screen. A cache
        // prepared for the exact passenger identity opens immediately after
        // the server-authorized token rotation and refreshes silently.
        onBlockingPreparation: () => setBlockingTripId(tripId),
      });
      router.replace(requestedDestination);
    } catch (caught) {
      setSelectionError(userFacingErrorMessage(caught, 'This trip could not be prepared. Try again.'));
    } finally {
      if (activeAttempt.current === tripId) activeAttempt.current = null;
      setBlockingTripId((current) => current === tripId ? null : current);
      setSwitchingTripId((current) => current === tripId ? null : current);
    }
  }, [requestedDestination, trips.trips]);

  useEffect(() => {
    if (!requestedTripId || trips.isPending || trips.isError || switchingTripId) return;
    if (automaticAttempt.current === requestedTripId) return;
    automaticAttempt.current = requestedTripId;
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      // The preload refreshes the backend assignment list before selecting anything,
      // so a stale React Query snapshot cannot accept or reject a notification trip.
      void prepareTrip(requestedTripId);
    });
    return () => {
      active = false;
    };
  }, [prepareTrip, requestedTripId, switchingTripId, trips.isError, trips.isPending]);

  const renderTrip = useCallback<ListRenderItem<Trip>>(({ item }) => {
    const lastOpened = item.id === trips.selectedTripId;
    const opening = item.id === switchingTripId;
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${lastOpened ? 'Last opened trip. ' : ''}Open ${item.name}${item.destination ? `, ${item.destination}` : ''}`}
        accessibilityState={{ busy: opening, disabled: switchingTripId !== null }}
        disabled={switchingTripId !== null}
        onPress={() => void prepareTrip(item.id)}
        style={({ pressed }) => pressed && styles.pressed}>
        <GlassCard style={[styles.tripCard, lastOpened && styles.selectedTripCard]}>
          <View style={styles.tripIcon}>
            <MapPin color={colors.greenDeep} size={22} />
          </View>
          <View style={styles.tripCopy}>
            <View style={styles.tripTitleRow}>
              <Text style={styles.tripName}>{item.name}</Text>
              {opening ? (
                <Text style={styles.lastOpened}>Opening</Text>
              ) : lastOpened ? (
                <Text style={styles.lastOpened}>Last opened</Text>
              ) : null}
            </View>
            <Text style={styles.tripMeta}>
              {[
                item.destination,
        item.travelDate ? formatCalendarDate(item.travelDate) : null,
              ].filter(Boolean).join(' - ') || 'Trip details are being prepared'}
            </Text>
          </View>
        </GlassCard>
      </Pressable>
    );
  }, [prepareTrip, switchingTripId, trips.selectedTripId]);

  if (blockingTripId) {
    return (
      <RequiredDownloadScreen
        message={progress.message}
        progress={progress.percent}
        completedLabel={progress.completedLabel}
      />
    );
  }

  if (trips.isPending) return <ContentLoading label="Loading your available trips" />;
  if (trips.isError) {
    return <ContentError message="Your assigned trips could not be loaded." onRetry={() => void trips.refetch()} />;
  }

  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.screen}>
      <FlatList
        data={filteredTrips}
        keyExtractor={(trip) => trip.id}
        renderItem={renderTrip}
        contentContainerStyle={styles.list}
        ItemSeparatorComponent={ListSeparator}
        keyboardShouldPersistTaps="handled"
        {...MOBILE_LIST_WINDOWING.standard}
        refreshControl={(
          <RefreshControl
            refreshing={manualRefresh.isRefreshing}
            onRefresh={() => void manualRefresh.refresh(manualRefreshTask)}
          />
        )}
        ListHeaderComponent={(
          <View style={styles.header}>
            <PageHeader
              eyebrow="Passenger access"
              title="Choose your trip"
              subtitle="Only trips assigned to this verified passenger account are shown."
              tone="passenger"
            />
            <View style={styles.searchBox}>
              <Search color={colors.inkMuted} size={20} />
              <TextInput
                accessibilityLabel="Search assigned trips"
                autoCapitalize="none"
                autoCorrect={false}
                onChangeText={setSearch}
                placeholder="Search group or destination"
                placeholderTextColor={colors.inkMuted}
                returnKeyType="search"
                style={styles.searchInput}
                value={search}
              />
            </View>
            {selectionError ? <ContentError message={selectionError} /> : null}
          </View>
        )}
        ListEmptyComponent={(
          <ContentEmpty
            title={search ? 'No matching trip' : 'No eligible trip'}
            message={search
              ? 'Try another group name or destination.'
              : 'Ask your travel team to confirm that the group is enabled for passenger access.'}
          />
        )}
      />
    </Screen>
  );
}

function ListSeparator() {
  return <View style={styles.separator} />;
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 0 },
  list: { flexGrow: 1, paddingHorizontal: spacing.lg, paddingBottom: spacing.xl },
  header: { gap: spacing.lg, paddingBottom: spacing.lg },
  searchBox: {
    minHeight: 52,
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    borderRadius: radii.lg,
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.surfaceStrong,
    paddingHorizontal: spacing.md,
  },
  searchInput: { flex: 1, minHeight: 50, color: colors.ink, fontSize: 16 },
  tripCard: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.md },
  selectedTripCard: { borderColor: colors.greenDeep, borderWidth: 1.5 },
  tripIcon: {
    width: 44,
    height: 44,
    borderRadius: 15,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.greenSoft,
  },
  tripCopy: { flex: 1, gap: 4 },
  tripTitleRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: spacing.sm },
  tripName: { color: colors.ink, fontSize: 17, fontWeight: '900' },
  lastOpened: { color: colors.greenDeep, fontSize: 11, fontWeight: '900', textTransform: 'uppercase' },
  tripMeta: { color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
  separator: { height: spacing.sm },
  pressed: { opacity: 0.68 },
});
