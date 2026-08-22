import { useRouter } from 'expo-router';
import AlertTriangle from 'lucide-react-native/icons/triangle-alert';
import CheckCircle2 from 'lucide-react-native/icons/circle-check-big';
import ChevronRight from 'lucide-react-native/icons/chevron-right';
import Clock3 from 'lucide-react-native/icons/clock-3';
import { useCallback, useMemo, useState } from 'react';
import {
  Alert,
  Pressable,
  RefreshControl,
  SectionList,
  StyleSheet,
  Text,
  View,
  type SectionListRenderItemInfo,
} from 'react-native';

import { userFacingErrorMessage } from '@/core/errors/user-facing-error';
import { MOBILE_LIST_WINDOWING } from '@/core/performance/mobile-performance-budgets';
import { useManualRefresh } from '@/core/query/use-manual-refresh';
import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { StatusPill } from '@/design/components/status-pill';
import { colors, spacing } from '@/design/theme';
import type {
  AttendanceRosterPassenger,
  AttendanceSession,
} from '@/features/coordinator/api/coordinator-contracts';
import {
  leaveAttendanceSession,
  selectAttendanceSession,
} from '@/features/coordinator/data/attendance-sessions';
import { visibleAttendanceSessions } from '@/features/coordinator/data/coordinator-view-policy';
import {
  useAttendanceSessions,
  useCoordinatorAttendanceRoster,
} from '@/features/coordinator/hooks/use-coordinator';
import { useCoordinatorTrips } from '@/features/coordinator/hooks/use-coordinator-trips';
import {
  AttendanceActivitySummary,
  type ExpandedAttendanceRoster,
} from '@/features/coordinator/ui/attendance-activity-summary';
import { AttendanceIssuesBanner } from '@/features/coordinator/ui/attendance-issues-banner';
import { AttendanceReconciliationCard } from '@/features/coordinator/ui/attendance-reconciliation-card';

type Row =
  | { kind: 'session'; value: AttendanceSession }
  | { kind: 'summary'; value: AttendanceSession }
  | { kind: 'passenger'; value: AttendanceRosterPassenger; status: 'counted' | 'missing' };
type AttendanceSection = { title: string | null; data: Row[] };

export default function CoordinatorAttendanceScreen() {
  const router = useRouter();
  const manualRefresh = useManualRefresh();
  const trips = useCoordinatorTrips();
  const sessions = useAttendanceSessions(trips.selectedTripId);
  const visibleSessions = useMemo(
    () => visibleAttendanceSessions(sessions.data?.items ?? []),
    [sessions.data?.items],
  );
  const [viewedSession, setViewedSession] = useState<{ tripId: string; sessionId: string } | null>(null);
  const viewedSessionId = viewedSession?.tripId === trips.selectedTripId
    ? viewedSession.sessionId
    : null;
  const effectiveSessionId = viewedSessionId
    ?? visibleSessions.find((session) => session.id === sessions.data?.selectedSessionId)?.id
    ?? visibleSessions[0]?.id
    ?? null;
  const selectedActivity = visibleSessions.find((session) => session.id === effectiveSessionId) ?? null;
  const selectedForScanning = selectedActivity?.id === sessions.data?.selectedSessionId;
  const [expanded, setExpanded] = useState<{
    sessionId: string;
    status: Exclude<ExpandedAttendanceRoster, null>;
  } | null>(null);
  const expandedStatus = expanded?.sessionId === effectiveSessionId ? expanded.status : null;
  const roster = useCoordinatorAttendanceRoster(
    trips.selectedTripId,
    effectiveSessionId,
    expandedStatus ?? 'missing',
    expandedStatus !== null,
  );
  const [busy, setBusy] = useState(false);
  const [operationError, setOperationError] = useState<{ tripId: string; message: string } | null>(null);
  const error = operationError?.tripId === trips.selectedTripId ? operationError.message : null;

  const refreshAttendance = useCallback(async () => {
    const tasks: Promise<unknown>[] = [sessions.refetch()];
    if (expandedStatus) tasks.push(roster.refetch());
    await Promise.all(tasks);
  }, [expandedStatus, roster, sessions]);

  const chooseSession = useCallback(async (session: AttendanceSession) => {
    const tripId = trips.selectedTripId;
    if (!tripId) return;
    setViewedSession({ tripId, sessionId: session.id });
    setExpanded(null);
    if (session.status !== 'active') return;
    setOperationError(null);
    try {
      await selectAttendanceSession(tripId, session.id);
      await sessions.refetch();
    } catch (caught) {
      setOperationError({
        tripId,
        message: userFacingErrorMessage(caught, 'The attendance activity could not be opened.'),
      });
    }
  }, [sessions, trips.selectedTripId]);

  const toggleRoster = useCallback((status: 'counted' | 'missing') => {
    if (!effectiveSessionId) return;
    setExpanded((current) => (
      current?.sessionId === effectiveSessionId && current.status === status
        ? null
        : { sessionId: effectiveSessionId, status }
    ));
  }, [effectiveSessionId]);

  const finishMyScanning = useCallback(() => {
    const tripId = trips.selectedTripId;
    if (!tripId || !selectedActivity || selectedActivity.status !== 'active' || !selectedForScanning) return;
    Alert.alert(
      'Finish scanning on this device?',
      'This only leaves the activity on your device. It will stay open for other coordinators, and any scans already saved here will continue synchronizing.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Finish my scanning',
          onPress: () => {
            setBusy(true);
            setOperationError(null);
            void leaveAttendanceSession(tripId, selectedActivity.id)
              .then(async () => {
                try {
                  const result = await sessions.refetch();
                  if (!result.error) return;
                } catch {
                  // The query client can reject when explicitly configured to throw.
                }
                setOperationError({
                  tripId,
                  message: 'This device left the activity, but the latest activity list could not be loaded.',
                });
              }, (caught: unknown) => {
                setOperationError({
                  tripId,
                  message: userFacingErrorMessage(caught, 'This device could not leave the activity.'),
                });
              })
              .finally(() => setBusy(false));
          },
        },
      ],
    );
  }, [selectedActivity, selectedForScanning, sessions, trips.selectedTripId]);

  const sections = useMemo<AttendanceSection[]>(() => {
    const result: AttendanceSection[] = [{
      title: 'Started and completed',
      data: visibleSessions.map((session) => ({ kind: 'session', value: session })),
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
  }, [expandedStatus, roster.data, selectedActivity, visibleSessions]);

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
      const iconColor = item.status === 'counted' ? colors.greenDeep : colors.warning;
      return (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`View details for ${item.value.display_name}`}
          onPress={() => router.push({
            pathname: '/(coordinator)/operations/passenger/[id]',
            params: { id: item.value.id },
          })}
          style={({ pressed }) => pressed && styles.pressed}>
          <GlassCard style={styles.passengerRow}>
            <Icon color={iconColor} size={19} />
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
    const viewed = session.id === effectiveSessionId;
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ selected: viewed }}
        accessibilityLabel={`${session.name}, ${session.status}, ${session.scanned_count} counted`}
        onPress={() => void chooseSession(session)}
        style={({ pressed }) => pressed && styles.pressed}>
        <GlassCard style={[styles.sessionRow, viewed && styles.viewedSession]}>
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
        renderSectionHeader={({ section }) => section.title ? (
          <Text accessibilityRole="header" style={styles.sectionTitle}>{section.title}</Text>
        ) : null}
        keyExtractor={(item) => item.kind === 'passenger'
          ? `${item.kind}:${item.status}:${item.value.id}`
          : `${item.kind}:${item.value.id}`}
        stickySectionHeadersEnabled={false}
        {...MOBILE_LIST_WINDOWING.denseRoster}
        contentContainerStyle={styles.list}
        refreshControl={(
          <RefreshControl
            refreshing={manualRefresh.isRefreshing}
            onRefresh={() => void manualRefresh.refresh(refreshAttendance)}
          />
        )}
        ListHeaderComponent={(
          <View style={styles.header}>
            <PageHeader
              eyebrow="Operations"
              title="Attendance"
              subtitle={trips.selectedTrip?.name || 'Selected group activities'}
              tone="coordinator"
            />
            <AttendanceIssuesBanner tripId={trips.selectedTripId} />
            {trips.selectedTripId && selectedActivity ? (
              <AttendanceReconciliationCard
                tripId={trips.selectedTripId}
                session={selectedActivity}
                onRefresh={refreshAttendance}
              />
            ) : null}
            {sessions.isPending ? <ContentLoading label="Loading attendance activities" /> : null}
            {sessions.isError ? (
              <ContentError message="Attendance activities are not available offline." onRetry={() => void sessions.refetch()} />
            ) : null}
            {error ? <ContentError message={error} /> : null}
            {sessions.data && visibleSessions.length === 0 ? (
              <ContentEmpty title="No started attendance" message="Create an activity from Scan to begin attendance." />
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
            {selectedActivity?.status === 'active' && selectedForScanning ? (
              <PrimaryButton label="Finish my scanning" loading={busy} onPress={finishMyScanning} />
            ) : null}
          </View>
        )}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 0 },
  list: { paddingHorizontal: spacing.lg, paddingBottom: 104 },
  header: { gap: spacing.md, paddingBottom: spacing.sm },
  footer: { gap: spacing.md, paddingTop: spacing.md },
  sectionTitle: {
    color: colors.ink,
    fontSize: 19,
    fontWeight: '900',
    paddingTop: spacing.lg,
    paddingBottom: spacing.sm,
  },
  sessionRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, marginBottom: spacing.sm },
  viewedSession: { borderColor: colors.green, borderWidth: 2 },
  sessionText: { flex: 1, gap: 3 },
  sessionName: { color: colors.ink, fontSize: 15, fontWeight: '800' },
  sessionMeta: { color: colors.inkMuted, fontSize: 12 },
  passengerRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.md, marginBottom: spacing.sm },
  passengerText: { flex: 1, gap: 3 },
  passengerName: { color: colors.ink, fontSize: 14, fontWeight: '700' },
  viewDetails: { color: colors.greenDeep, fontSize: 12, fontWeight: '800' },
  pressed: { opacity: 0.68 },
});
