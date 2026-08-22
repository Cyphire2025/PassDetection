import CalendarDays from 'lucide-react-native/icons/calendar-days';
import ChevronRight from 'lucide-react-native/icons/chevron-right';
import MapPinned from 'lucide-react-native/icons/map-pinned';
import Search from 'lucide-react-native/icons/search';
import UsersRound from 'lucide-react-native/icons/users-round';
import { useLocalSearchParams } from 'expo-router';
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

import { formatCalendarDate } from '@/core/localization/date-time';
import { MOBILE_LIST_WINDOWING } from '@/core/performance/mobile-performance-budgets';
import { useManualRefresh } from '@/core/query/use-manual-refresh';
import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { Screen } from '@/design/components/screen';
import { StatusPill } from '@/design/components/status-pill';
import { colors, radii, spacing } from '@/design/theme';
import { useCoordinatorTrips } from '@/features/coordinator/hooks/use-coordinator-trips';
import type { Trip } from '@/features/trips/model/trip';

export default function CoordinatorGroupsScreen() {
  const trips = useCoordinatorTrips();
  const manualRefresh = useManualRefresh();
  const { notice } = useLocalSearchParams<{ notice?: string }>();
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
          <View style={styles.heading}>
            <View style={styles.icon}><UsersRound color={colors.green} size={23} /></View>
            <View style={styles.headingText}>
              <Text style={styles.title}>{item.name}</Text>
              <Text style={styles.subtitle}>{item.destination || 'Destination pending'}</Text>
            </View>
            <ChevronRight color={colors.inkMuted} size={20} />
          </View>
          <View style={styles.metaRow}>
            <MapPinned color={colors.blueDeep} size={16} />
            <Text style={styles.meta}>{item.destination || 'Location pending'}</Text>
            <CalendarDays color={colors.blueDeep} size={16} />
            <Text style={styles.meta}>
              {item.travelDate ? formatCalendarDate(item.travelDate) : 'Dates pending'}
            </Text>
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
        {...MOBILE_LIST_WINDOWING.standard}
        refreshControl={(
          <RefreshControl
            refreshing={manualRefresh.isRefreshing}
            onRefresh={() => void manualRefresh.refresh(trips.refetch)}
          />
        )}
        ListHeaderComponent={(
          <View style={styles.header}>
            <PageHeader
              eyebrow="Coordinator"
              title="Assigned trips"
              subtitle="Operational access is limited to your current assignments."
              tone="coordinator"
            />
            <GlassCard style={styles.summaryCard}>
              <View style={styles.summaryMetric}>
                <Text style={styles.summaryValue}>{trips.trips.length.toLocaleString()}</Text>
                <Text style={styles.summaryLabel}>assigned {trips.trips.length === 1 ? 'trip' : 'trips'}</Text>
              </View>
              <View style={styles.summaryDivider} />
              <View style={styles.summaryMetric}>
                <Text numberOfLines={1} style={styles.summaryContext}>
                  {trips.selectedTripId ? 'Trip selected' : 'Choose one'}
                </Text>
                <Text style={styles.summaryLabel}>operational context</Text>
              </View>
            </GlassCard>
            {notice === 'select-group' && !trips.selectedTripId ? (
              <GlassCard style={styles.notice}>
                <Text accessibilityRole="alert" style={styles.noticeText}>Select a group to continue.</Text>
              </GlassCard>
            ) : null}
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
            {trips.isPending ? <ContentLoading label="Loading assigned trips" /> : null}
            {trips.isError ? <ContentError message="No assigned trip is available offline." onRetry={() => void trips.refetch()} /> : null}
          </View>
        )}
        ListEmptyComponent={!trips.isPending && !trips.isError ? (
          <ContentEmpty
            title={search ? 'No matching trip' : 'No assigned trips'}
            message={search
              ? 'Try another group name or destination.'
              : 'Ask operations staff to enable Coordinator access and assign this account.'}
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
    shadowColor: colors.blueDeep,
    shadowOpacity: 0.08,
    shadowRadius: 14,
    shadowOffset: { width: 0, height: 7 },
    elevation: 2,
  },
  searchInput: { flex: 1, minHeight: 50, color: colors.ink, fontSize: 16 },
  separator: { height: spacing.sm },
  card: { borderRadius: radii.md, gap: spacing.md, backgroundColor: colors.white, borderLeftColor: colors.aqua, borderLeftWidth: 4 },
  selected: { borderColor: colors.green, borderWidth: 2, borderLeftWidth: 5, backgroundColor: colors.greenWash },
  summaryCard: { flexDirection: 'row', alignItems: 'stretch', padding: 0, overflow: 'hidden' },
  summaryMetric: { flex: 1, minHeight: 78, justifyContent: 'center', paddingHorizontal: spacing.lg, gap: 2 },
  summaryDivider: { width: 1, marginVertical: spacing.md, backgroundColor: colors.border },
  summaryValue: { color: colors.navy, fontSize: 25, fontWeight: '900' },
  summaryContext: { color: colors.blueDeep, fontSize: 18, fontWeight: '900' },
  summaryLabel: { color: colors.inkMuted, fontSize: 11, fontWeight: '700' },
  notice: { padding: spacing.md, borderColor: colors.green },
  noticeText: { color: colors.greenDeep, fontSize: 14, fontWeight: '800' },
  pressed: { opacity: 0.7 },
  heading: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  icon: { width: 44, height: 44, borderRadius: 16, backgroundColor: colors.navy, alignItems: 'center', justifyContent: 'center' },
  headingText: { flex: 1, gap: 3 },
  title: { color: colors.ink, fontSize: 17, fontWeight: '800' },
  subtitle: { color: colors.inkMuted, fontSize: 13 },
  metaRow: { flexDirection: 'row', alignItems: 'center', flexWrap: 'wrap', gap: spacing.sm },
  meta: { color: colors.inkMuted, fontSize: 12, marginRight: spacing.sm },
});
