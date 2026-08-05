import { useRouter } from 'expo-router';
import AlertTriangle from 'lucide-react-native/icons/triangle-alert';
import CheckCircle2 from 'lucide-react-native/icons/circle-check-big';
import ChevronRight from 'lucide-react-native/icons/chevron-right';
import Clock3 from 'lucide-react-native/icons/clock-3';
import { useCallback, useMemo, useState } from 'react';
import {
  Pressable,
  RefreshControl,
  SectionList,
  StyleSheet,
  Text,
  View,
  type SectionListRenderItemInfo,
} from 'react-native';

import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { Screen } from '@/design/components/screen';
import { StatusPill } from '@/design/components/status-pill';
import { colors, spacing } from '@/design/theme';
import type {
  AttendanceRosterPassenger,
  AttendanceSession,
} from '@/features/coordinator/api/coordinator-contracts';
import {
  AttendanceActivitySummary,
  type ExpandedAttendanceRoster,
} from '@/features/coordinator/ui/attendance-activity-summary';
import { OperationHeader } from '@/features/coordinator/ui/operation-header';
import {
  useManagerAttendanceRoster,
  useManagerAttendanceSessions,
} from '@/features/manager/hooks/use-manager-operations';
import { useTrips } from '@/features/trips/hooks/use-trips';

type Row =
  | { kind: 'session'; value: AttendanceSession }
  | { kind: 'summary'; value: AttendanceSession }
  | { kind: 'passenger'; value: AttendanceRosterPassenger; status: 'counted' | 'missing' };
type AttendanceSection = { title: string; data: Row[] };

export default function ManagerAttendanceScreen() {
  const router = useRouter();
  const trips = useTrips();
  const sessions = useManagerAttendanceSessions(trips.selectedTripId);
  const activities = useMemo(() => sessions.data?.items ?? [], [sessions.data?.items]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const effectiveSessionId = activities.some((item) => item.id === selectedId)
    ? selectedId
    : null;
  const selectedActivity = activities.find((item) => item.id === effectiveSessionId) ?? null;
  const [expanded, setExpanded] = useState<{
    sessionId: string;
    status: Exclude<ExpandedAttendanceRoster, null>;
  } | null>(null);
  const expandedStatus = expanded?.sessionId === effectiveSessionId ? expanded.status : null;
  const roster = useManagerAttendanceRoster(
    trips.selectedTripId,
    effectiveSessionId,
    expandedStatus ?? 'missing',
    expandedStatus !== null,
  );

  const chooseSession = useCallback((session: AttendanceSession) => {
    setSelectedId(session.id);
    setExpanded(null);
  }, []);
  const toggleRoster = useCallback((status: 'counted' | 'missing') => {
    if (!effectiveSessionId) return;
    setExpanded((current) => (
      current?.sessionId === effectiveSessionId && current.status === status
        ? null
        : { sessionId: effectiveSessionId, status }
    ));
  }, [effectiveSessionId]);

  const sections = useMemo<AttendanceSection[]>(() => {
    const result: AttendanceSection[] = [{
      title: 'Attendance activities',
      data: activities.map((session) => ({ kind: 'session', value: session })),
    }];
    if (selectedActivity) {
      result.push({ title: 'Activity details', data: [{ kind: 'summary', value: selectedActivity }] });
    }
    if (expandedStatus && roster.data) {
      result.push({
        title: expandedStatus === 'counted' ? 'Counted passengers' : 'Missing passengers',
        data: roster.data.items.map((passenger) => ({
          kind: 'passenger',
          value: passenger,
          status: expandedStatus,
        })),
      });
    }
    return result;
  }, [activities, expandedStatus, roster.data, selectedActivity]);

  const renderItem = useCallback(({ item }: SectionListRenderItemInfo<Row, AttendanceSection>) => {
    if (item.kind === 'summary') {
      return (
        <AttendanceActivitySummary
          session={item.value}
          expanded={expandedStatus}
          onToggle={toggleRoster}
        />
      );
    }
    if (item.kind === 'passenger') {
      const Icon = item.status === 'counted' ? CheckCircle2 : AlertTriangle;
      return (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`View details for ${item.value.display_name}`}
          onPress={() => router.push({
            pathname: '/(manager)/operations/passenger/[id]',
            params: { id: item.value.id },
          })}
          style={({ pressed }) => pressed && styles.pressed}>
          <GlassCard style={styles.passengerRow}>
            <Icon
              color={item.status === 'counted' ? colors.greenDeep : colors.warning}
              size={19}
            />
            <View style={styles.passengerText}>
              <Text style={styles.passengerName}>{item.value.display_name}</Text>
              <Text style={styles.viewDetails}>View details</Text>
            </View>
            <ChevronRight color={colors.inkMuted} size={19} />
          </GlassCard>
        </Pressable>
      );
    }
    const session = item.value;
    const selected = session.id === effectiveSessionId;
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ selected }}
        accessibilityLabel={`${session.name}, ${session.scanned_count} of ${session.assigned_count} counted`}
        onPress={() => chooseSession(session)}
        style={({ pressed }) => pressed && styles.pressed}>
        <GlassCard style={[styles.sessionRow, selected && styles.selectedSession]}>
          {session.status === 'completed'
            ? <CheckCircle2 color={colors.greenDeep} size={21} />
            : <Clock3 color={colors.warning} size={21} />}
          <View style={styles.sessionText}>
            <Text style={styles.sessionName}>{session.name}</Text>
            <Text style={styles.sessionMeta}>{session.scanned_count} of {session.assigned_count} counted</Text>
          </View>
          <StatusPill
            label={session.status === 'active' ? 'In progress' : 'Completed'}
            tone={session.status === 'active' ? 'warning' : 'good'}
          />
        </GlassCard>
      </Pressable>
    );
  }, [chooseSession, effectiveSessionId, expandedStatus, router, toggleRoster]);

  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.screen}>
      <SectionList<Row, AttendanceSection>
        sections={sections}
        renderItem={renderItem}
        renderSectionHeader={({ section }) => (
          <Text accessibilityRole="header" style={styles.sectionTitle}>{section.title}</Text>
        )}
        keyExtractor={(item) => item.kind === 'passenger'
          ? `${item.kind}:${item.status}:${item.value.id}`
          : `${item.kind}:${item.value.id}`}
        stickySectionHeadersEnabled={false}
        initialNumToRender={16}
        maxToRenderPerBatch={24}
        updateCellsBatchingPeriod={35}
        windowSize={7}
        contentContainerStyle={styles.list}
        refreshControl={(
          <RefreshControl
            refreshing={sessions.isRefetching || roster.isRefetching}
            onRefresh={() => void Promise.all([
              sessions.refetch(),
              ...(expandedStatus ? [roster.refetch()] : []),
            ])}
          />
        )}
        ListHeaderComponent={(
          <View style={styles.header}>
            <OperationHeader title="Attendance" subtitle={trips.selectedTrip?.name || 'Selected group'} />
            {sessions.isPending ? <ContentLoading label="Loading attendance activities" /> : null}
            {sessions.isError ? (
              <ContentError message="Attendance activities could not be loaded." onRetry={() => void sessions.refetch()} />
            ) : null}
            {sessions.data && activities.length === 0 ? (
              <ContentEmpty title="No attendance activity" message="Coordinator scanning activities will appear here." />
            ) : null}
          </View>
        )}
        ListFooterComponent={(
          <View style={styles.footer}>
            {expandedStatus && roster.isPending ? <ContentLoading label={`Loading ${expandedStatus} passengers`} /> : null}
            {expandedStatus && roster.isError ? (
              <ContentError message="The attendance roster could not be loaded." onRetry={() => void roster.refetch()} />
            ) : null}
            {expandedStatus && roster.data?.items.length === 0 ? (
              <ContentEmpty
                title={expandedStatus === 'counted' ? 'No counted passengers' : 'No missing passengers'}
                message={expandedStatus === 'counted'
                  ? 'No passenger has been counted for this activity yet.'
                  : 'Everyone assigned to this activity has been counted.'}
              />
            ) : null}
          </View>
        )}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 0 },
  list: { paddingHorizontal: spacing.lg, paddingBottom: spacing.xxl },
  header: { gap: spacing.md, paddingBottom: spacing.sm },
  footer: { gap: spacing.md, paddingTop: spacing.md },
  sectionTitle: { color: colors.ink, fontSize: 19, fontWeight: '900', paddingTop: spacing.lg, paddingBottom: spacing.sm },
  sessionRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, marginBottom: spacing.sm },
  selectedSession: { borderColor: colors.aqua, borderWidth: 2 },
  sessionText: { flex: 1, gap: 3 },
  sessionName: { color: colors.ink, fontSize: 15, fontWeight: '800' },
  sessionMeta: { color: colors.inkMuted, fontSize: 12 },
  passengerRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.md, marginBottom: spacing.sm },
  passengerText: { flex: 1, gap: 3 },
  passengerName: { color: colors.ink, fontSize: 14, fontWeight: '700' },
  viewDetails: { color: colors.greenDeep, fontSize: 12, fontWeight: '800' },
  pressed: { opacity: 0.68 },
});
