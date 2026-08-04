import CalendarDays from 'lucide-react-native/icons/calendar-days';
import ChevronRight from 'lucide-react-native/icons/chevron-right';
import MapPinned from 'lucide-react-native/icons/map-pinned';
import Search from 'lucide-react-native/icons/search';
import UsersRound from 'lucide-react-native/icons/users-round';
import { useCallback, useDeferredValue, useMemo, useState } from 'react';
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

import { useManualRefresh } from '@/core/query/use-manual-refresh';
import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { StatusPill } from '@/design/components/status-pill';
import { colors, radii, spacing } from '@/design/theme';
import { useTrips } from '@/features/trips/hooks/use-trips';
import type { Trip } from '@/features/trips/model/trip';

export default function ManagerGroupsScreen() {
  const trips = useTrips();
  const manualRefresh = useManualRefresh();
  const [search, setSearch] = useState('');
  const deferredSearch = useDeferredValue(search.trim().toLocaleLowerCase());
  const filteredTrips = useMemo(() => deferredSearch
    ? trips.trips.filter((trip) => [trip.name, trip.destination, trip.travelDate]
      .filter(Boolean)
      .some((value) => value?.toLocaleLowerCase().includes(deferredSearch)))
    : trips.trips, [deferredSearch, trips.trips]);
  const selectTrip = trips.selectTrip;
  const selectedTripId = trips.selectedTripId;
  const renderTrip = useCallback<ListRenderItem<Trip>>(({ item }) => {
    const selected = item.id === selectedTripId;
    return (
      <Pressable
        accessibilityRole="radio"
        accessibilityState={{ selected }}
        onPress={() => selectTrip(item.id)}
        style={({ pressed }) => pressed && styles.pressed}>
        <GlassCard style={[styles.card, selected && styles.selected]}>
          <View style={styles.cardHeading}>
            <View style={styles.icon}>
              <UsersRound color={colors.white} size={23} />
            </View>
            <View style={styles.cardText}>
              <Text style={styles.title}>{item.name}</Text>
              <Text style={styles.destination}>{item.destination || 'Destination being prepared'}</Text>
            </View>
            <ChevronRight color={colors.inkMuted} size={20} />
          </View>
          <View style={styles.metaRow}>
            <MapPinned color={colors.blueDeep} size={16} />
            <Text style={styles.meta}>{item.destination || 'Location pending'}</Text>
            <CalendarDays color={colors.blueDeep} size={16} />
            <Text style={styles.meta}>{item.travelDate || 'Dates pending'}</Text>
          </View>
          {selected ? <StatusPill label="Selected group" tone="good" /> : null}
        </GlassCard>
      </Pressable>
    );
  }, [selectTrip, selectedTripId]);

  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.screen}>
      <FlatList
        data={filteredTrips}
        keyExtractor={(trip) => trip.id}
        renderItem={renderTrip}
        contentContainerStyle={styles.list}
        ItemSeparatorComponent={ListSeparator}
        initialNumToRender={10}
        maxToRenderPerBatch={12}
        windowSize={7}
        removeClippedSubviews
        refreshControl={(
          <RefreshControl
            refreshing={manualRefresh.isRefreshing}
            onRefresh={() => void manualRefresh.refresh(trips.refetch)}
          />
        )}
        ListHeaderComponent={(
          <View style={styles.header}>
            <PageHeader
              eyebrow="Client Manager"
              title="Assigned groups"
              subtitle="Only groups explicitly shared with your account appear here."
              accessory={trips.offline ? <StatusPill label="Offline copy" tone="warning" /> : undefined}
              tone="manager"
            />
            <View style={styles.searchBox}>
              <Search color={colors.inkMuted} size={20} />
              <TextInput
                accessibilityLabel="Search assigned groups"
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
            {trips.isPending ? <ContentLoading label="Loading assigned groups" /> : null}
            {trips.isError ? (
              <ContentError message="No assigned group is available offline yet." onRetry={() => void trips.refetch()} />
            ) : null}
          </View>
        )}
        ListEmptyComponent={!trips.isPending && !trips.isError ? (
          <ContentEmpty
            title={search ? 'No matching group' : 'No assigned groups'}
            message={search
              ? 'Try another group name or destination.'
              : 'Your travel team can explicitly assign a GC App-enabled group to this account.'}
          />
        ) : null}
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
  separator: { height: spacing.sm },
  card: { borderRadius: radii.md, gap: spacing.md, borderLeftColor: colors.blue, borderLeftWidth: 4 },
  selected: { borderColor: colors.blue, borderWidth: 2, borderLeftWidth: 5, backgroundColor: colors.aquaSoft },
  pressed: { opacity: 0.7 },
  cardHeading: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  icon: { width: 44, height: 44, borderRadius: 16, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.blueDeep },
  cardText: { flex: 1, gap: 3 },
  title: { color: colors.ink, fontSize: 17, fontWeight: '800' },
  destination: { color: colors.inkMuted, fontSize: 13 },
  metaRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: spacing.sm },
  meta: { color: colors.inkMuted, fontSize: 12, marginRight: spacing.sm },
});
