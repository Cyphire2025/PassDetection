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

import { useManualRefresh } from '@/core/query/use-manual-refresh';
import { userFacingErrorMessage } from '@/core/errors/user-facing-error';
import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { StatusPill } from '@/design/components/status-pill';
import { colors, spacing } from '@/design/theme';
import type { AttendanceSession, MissingPassenger } from '@/features/coordinator/api/coordinator-contracts';
import { completeAttendanceSession, selectAttendanceSession } from '@/features/coordinator/data/attendance-sessions';
import { visibleAttendanceSessions } from '@/features/coordinator/data/coordinator-view-policy';
import { useAttendanceSessionDetail, useAttendanceSessions } from '@/features/coordinator/hooks/use-coordinator';
import { useCoordinatorTrips } from '@/features/coordinator/hooks/use-coordinator-trips';

type Row =
  | { kind: 'session'; value: AttendanceSession }
  | { kind: 'missing'; value: MissingPassenger };
type AttendanceSection = { title: 'Started and completed' | 'Missing passengers'; data: Row[] };

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
  const viewSessionId = viewedSession?.tripId === trips.selectedTripId
    ? viewedSession.sessionId
    : null;
  const effectiveSessionId = viewSessionId
    ?? visibleSessions.find((session) => session.id === sessions.data?.selectedSessionId)?.id
    ?? visibleSessions[0]?.id
    ?? null;
  const detail = useAttendanceSessionDetail(trips.selectedTripId, effectiveSessionId);
  const [busy, setBusy] = useState(false);
  const [operationError, setOperationError] = useState<{ tripId: string; message: string } | null>(null);
  const error = operationError?.tripId === trips.selectedTripId ? operationError.message : null;
  const refetchSessions = sessions.refetch;
  const refetchDetail = detail.refetch;

  const refreshAttendance = useCallback(async () => {
    await refetchSessions();
    if (effectiveSessionId) await refetchDetail();
  }, [effectiveSessionId, refetchDetail, refetchSessions]);

  const chooseSession = useCallback(async (session: AttendanceSession) => {
    const tripId = trips.selectedTripId;
    if (!tripId) return;
    setViewedSession({ tripId, sessionId: session.id });
    if (session.status !== 'active') return;
    setOperationError(null);
    try {
      await selectAttendanceSession(tripId, session.id);
      await refetchSessions();
    } catch (caught) {
      setOperationError({
        tripId,
        message: userFacingErrorMessage(caught, 'The attendance activity could not be opened.'),
      });
    }
  }, [refetchSessions, trips.selectedTripId]);

  const completeSelected = useCallback(() => {
    const tripId = trips.selectedTripId;
    const selected = visibleSessions.find((session) => session.id === effectiveSessionId);
    if (!tripId || !selected || selected.status !== 'active') return;
    Alert.alert(
      'Complete attendance activity?',
      'New scans cannot be added after completion.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Complete',
          style: 'destructive',
          onPress: () => {
            setBusy(true);
            setOperationError(null);
            void completeAttendanceSession(tripId, selected.id)
              .then(() => Promise.all([refetchSessions(), refetchDetail()]))
              .catch((caught: unknown) => {
                setOperationError({
                  tripId,
                  message: userFacingErrorMessage(caught, 'The activity could not be completed.'),
                });
              })
              .finally(() => setBusy(false));
          },
        },
      ],
    );
  }, [effectiveSessionId, refetchDetail, refetchSessions, trips.selectedTripId, visibleSessions]);

  const sections = useMemo<AttendanceSection[]>(() => [
    {
      title: 'Started and completed',
      data: visibleSessions.map((session) => ({ kind: 'session', value: session })),
    },
    {
      title: 'Missing passengers',
      data: (detail.data?.missing ?? []).map((passenger) => ({ kind: 'missing', value: passenger })),
    },
  ], [detail.data?.missing, visibleSessions]);

  const selectedActivity = visibleSessions.find((session) => session.id === effectiveSessionId) ?? null;
  const renderItem = useCallback(({ item }: SectionListRenderItemInfo<Row, AttendanceSection>) => {
    if (item.kind === 'missing') {
      return (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`View details for ${item.value.display_name}`}
          onPress={() => router.push({ pathname: '/(coordinator)/operations/passenger/[id]', params: { id: item.value.id } })}
          style={({ pressed }) => pressed && styles.pressed}>
          <GlassCard style={styles.missingRow}>
            <AlertTriangle color={colors.warning} size={19} />
            <View style={styles.missingText}>
              <Text style={styles.missingName}>{item.value.display_name}</Text>
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
        accessibilityLabel={`${session.name}, ${session.status}, ${session.scanned_count} scanned`}
        onPress={() => void chooseSession(session)}
        style={({ pressed }) => pressed && styles.pressed}>
        <GlassCard style={[styles.sessionRow, viewed && styles.viewedSession]}>
          {session.status === 'completed'
            ? <CheckCircle2 color={colors.greenDeep} size={21} />
            : <Clock3 color={colors.warning} size={21} />}
          <View style={styles.sessionText}>
            <Text style={styles.sessionName}>{session.name}</Text>
            <Text style={styles.sessionMeta}>{session.scanned_count} of {session.assigned_count} scanned</Text>
          </View>
          <StatusPill
            label={session.status === 'active' ? 'In progress' : 'Completed'}
            tone={session.status === 'active' ? 'warning' : 'good'}
          />
        </GlassCard>
      </Pressable>
    );
  }, [chooseSession, effectiveSessionId, router]);

  return (
    <Screen scroll={false} bottomInset={0} contentStyle={styles.screen}>
      <SectionList<Row, AttendanceSection>
        sections={sections}
        renderItem={renderItem}
        renderSectionHeader={({ section }) => (
          <Text accessibilityRole="header" style={styles.sectionTitle}>{section.title}</Text>
        )}
        keyExtractor={(item) => `${item.kind}:${item.value.id}`}
        stickySectionHeadersEnabled={false}
        initialNumToRender={12}
        maxToRenderPerBatch={18}
        updateCellsBatchingPeriod={35}
        windowSize={7}
        contentContainerStyle={styles.list}
        refreshControl={
          <RefreshControl
            refreshing={manualRefresh.isRefreshing}
            onRefresh={() => void manualRefresh.refresh(refreshAttendance)}
          />
        }
        ListHeaderComponent={
          <View style={styles.header}>
            <PageHeader
              eyebrow="Operations"
              title="Attendance"
              subtitle={trips.selectedTrip?.name || 'Selected group activities'}
              tone="coordinator"
            />
            {sessions.isPending ? <ContentLoading label="Loading attendance activities" /> : null}
            {sessions.isError ? (
              <ContentError message="Attendance activities are not available offline." onRetry={() => void sessions.refetch()} />
            ) : null}
            {error ? <ContentError message={error} /> : null}
            {sessions.data && visibleSessions.length === 0 ? (
              <ContentEmpty title="No started attendance" message="Create an activity from Scan to begin attendance." />
            ) : null}
          </View>
        }
        ListFooterComponent={
          <View style={styles.footer}>
            {detail.isPending && effectiveSessionId ? <ContentLoading label="Loading missing passengers" /> : null}
            {detail.isError ? (
              <ContentError message="Activity details are not available offline." onRetry={() => void detail.refetch()} />
            ) : null}
            {detail.data && detail.data.missing.length === 0 ? (
              <ContentEmpty title="No missing passengers" message="Everyone assigned to this activity has been scanned." />
            ) : null}
            {selectedActivity?.status === 'active' ? (
              <PrimaryButton label="Complete selected activity" tone="danger" loading={busy} onPress={completeSelected} />
            ) : null}
          </View>
        }
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
  missingRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.md, marginBottom: spacing.sm },
  missingText: { flex: 1, gap: 3 },
  missingName: { color: colors.ink, fontSize: 14, fontWeight: '700' },
  viewDetails: { color: colors.greenDeep, fontSize: 12, fontWeight: '800' },
  pressed: { opacity: 0.68 },
});
