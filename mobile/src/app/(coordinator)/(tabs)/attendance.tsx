import { useQuery } from '@tanstack/react-query';
import AlertTriangle from 'lucide-react-native/icons/triangle-alert';
import CheckCircle2 from 'lucide-react-native/icons/circle-check-big';
import CircleMinus from 'lucide-react-native/icons/circle-minus';
import Clock3 from 'lucide-react-native/icons/clock-3';
import UsersRound from 'lucide-react-native/icons/users-round';
import { useCallback, useMemo, useState } from 'react';
import {
  Alert,
  Pressable,
  SectionList,
  StyleSheet,
  Text,
  View,
  type SectionListRenderItemInfo,
} from 'react-native';

import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PageHeader } from '@/design/components/page-header';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { StatusPill } from '@/design/components/status-pill';
import { TextField } from '@/design/components/text-field';
import { colors, radii, spacing } from '@/design/theme';
import type { AttendanceSession, MissingPassenger } from '@/features/coordinator/api/coordinator-contracts';
import {
  completeAttendanceSession,
  createAttendanceSession,
  selectAttendanceSession,
} from '@/features/coordinator/data/attendance-sessions';
import { acknowledgeRejectedAttendance, attendanceQueueCounts, drainAttendanceQueue } from '@/features/coordinator/data/attendance-queue';
import {
  useAttendanceSessionDetail,
  useAttendanceSessions,
  useAttendanceSummary,
} from '@/features/coordinator/hooks/use-coordinator';
import { useTrips } from '@/features/trips/hooks/use-trips';
import { TripSwitcher } from '@/features/trips/ui/trip-switcher';

type Row =
  | { kind: 'session'; value: AttendanceSession }
  | { kind: 'missing'; value: MissingPassenger };
type AttendanceSection = { title: 'Activities' | 'Missing passengers'; data: Row[] };

export default function CoordinatorAttendanceScreen() {
  const trips = useTrips();
  const summary = useAttendanceSummary(trips.selectedTripId);
  const sessions = useAttendanceSessions(trips.selectedTripId);
  const [viewSessionId, setViewSessionId] = useState<string | null>(null);
  const effectiveSessionId = viewSessionId ?? sessions.data?.selectedSessionId ?? sessions.data?.items[0]?.id ?? null;
  const detail = useAttendanceSessionDetail(trips.selectedTripId, effectiveSessionId);
  const queueQuery = useQuery({
    queryKey: ['coordinator-attendance-queue', trips.selectedTripId],
    queryFn: () => attendanceQueueCounts(trips.selectedTripId!),
    enabled: Boolean(trips.selectedTripId),
  });
  const [syncing, setSyncing] = useState(false);
  const [activityName, setActivityName] = useState('');
  const [activityError, setActivityError] = useState<string | null>(null);
  const [activityBusy, setActivityBusy] = useState(false);

  const retry = useCallback(async () => {
    if (!trips.selectedTripId) return;
    setSyncing(true);
    try {
      await drainAttendanceQueue(trips.selectedTripId);
      await Promise.all([queueQuery.refetch(), summary.refetch(), detail.refetch()]);
    } finally {
      setSyncing(false);
    }
  }, [detail, queueQuery, summary, trips.selectedTripId]);

  const createActivity = useCallback(async () => {
    const tripId = trips.selectedTripId;
    const name = activityName.trim();
    if (!tripId || name.length < 2) {
      setActivityError('Enter an activity name of at least 2 characters.');
      return;
    }
    setActivityBusy(true);
    setActivityError(null);
    try {
      const created = await createAttendanceSession(tripId, name);
      setActivityName('');
      setViewSessionId(created.id);
      await sessions.refetch();
    } catch (caught) {
      setActivityError(caught instanceof Error ? caught.message : 'The activity could not be created.');
    } finally {
      setActivityBusy(false);
    }
  }, [activityName, sessions, trips.selectedTripId]);

  const chooseSession = useCallback(async (session: AttendanceSession) => {
    setViewSessionId(session.id);
    if (!trips.selectedTripId || !['draft', 'active'].includes(session.status)) return;
    setActivityError(null);
    try {
      await selectAttendanceSession(trips.selectedTripId, session.id);
      await sessions.refetch();
    } catch (caught) {
      setActivityError(caught instanceof Error ? caught.message : 'The activity could not be selected.');
    }
  }, [sessions, trips.selectedTripId]);

  const confirmCompletion = useCallback(() => {
    const tripId = trips.selectedTripId;
    const selected = sessions.data?.items.find((item) => item.id === effectiveSessionId);
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
            setActivityBusy(true);
            void completeAttendanceSession(tripId, selected.id)
              .then(() => Promise.all([sessions.refetch(), detail.refetch(), summary.refetch()]))
              .catch((caught: unknown) => {
                setActivityError(caught instanceof Error ? caught.message : 'The activity could not be completed.');
              })
              .finally(() => setActivityBusy(false));
          },
        },
      ],
    );
  }, [detail, effectiveSessionId, sessions, summary, trips.selectedTripId]);

  const sections = useMemo<AttendanceSection[]>(() => [
    {
      title: 'Activities',
      data: (sessions.data?.items ?? []).map((session) => ({ kind: 'session', value: session })),
    },
    {
      title: 'Missing passengers',
      data: (detail.data?.missing ?? []).map((passenger) => ({ kind: 'missing', value: passenger })),
    },
  ], [detail.data, sessions.data]);

  const renderItem = useCallback(({ item }: SectionListRenderItemInfo<Row, AttendanceSection>) => {
    if (item.kind === 'missing') {
      return (
        <GlassCard style={styles.missingRow}>
          <AlertTriangle color={colors.warning} size={19} />
          <Text style={styles.missingName}>{item.value.display_name}</Text>
        </GlassCard>
      );
    }
    const session = item.value;
    const selected = session.id === sessions.data?.selectedSessionId;
    const viewed = session.id === effectiveSessionId;
    return (
      <Pressable
        accessibilityRole="button"
        accessibilityState={{ selected }}
        accessibilityLabel={`${session.name}, ${session.status}, ${session.scanned_count} scanned`}
        onPress={() => void chooseSession(session)}
        style={({ pressed }) => pressed && styles.pressed}>
        <GlassCard style={[styles.sessionRow, viewed && styles.viewedSession]}>
          <View style={styles.sessionText}>
            <Text style={styles.sessionName}>{session.name}</Text>
            <Text style={styles.sessionMeta}>{session.scanned_count} of {session.assigned_count} scanned</Text>
          </View>
          <StatusPill
            label={selected ? 'Scanning' : session.status}
            tone={selected ? 'good' : session.status === 'completed' ? 'neutral' : 'warning'}
          />
        </GlassCard>
      </Pressable>
    );
  }, [chooseSession, effectiveSessionId, sessions.data?.selectedSessionId]);

  const queue = queueQuery.data ?? {};
  const pending = (queue.pending ?? 0) + (queue.sending ?? 0) + (queue.retryable ?? 0);
  const rejected = queue.rejected ?? 0;
  const selectedActivity = sessions.data?.items.find((item) => item.id === effectiveSessionId) ?? null;

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
        maxToRenderPerBatch={16}
        windowSize={7}
        contentContainerStyle={styles.list}
        ListHeaderComponent={
          <View style={styles.header}>
            <PageHeader
              eyebrow="Live progress"
              title="Attendance"
              subtitle="Named activities, server totals and the durable queue on this device."
              accessory={summary.data?.offline || sessions.data?.offline ? <StatusPill label="Offline copy" tone="warning" /> : undefined}
            />
            <TripSwitcher trips={trips.trips} selectedTripId={trips.selectedTripId} onSelect={trips.selectTrip} />
            {summary.isPending ? <ContentLoading label="Loading attendance summary" /> : null}
            {summary.isError ? <ContentError message="Attendance summary is not available offline." onRetry={() => void summary.refetch()} /> : null}
            {summary.data?.summary ? (
              <>
                <GlassCard style={styles.hero}>
                  <UsersRound color={colors.blueDeep} size={26} />
                  <View><Text style={styles.heroValue}>{summary.data.summary.total.toLocaleString()}</Text><Text style={styles.label}>assigned passengers</Text></View>
                </GlassCard>
                <View style={styles.grid}>
                  <Metric icon={<CheckCircle2 color={colors.greenDeep} size={22} />} value={summary.data.summary.present} label="Present" />
                  <Metric icon={<AlertTriangle color={colors.danger} size={22} />} value={summary.data.summary.missing} label="Missing" />
                  <Metric icon={<CircleMinus color={colors.warning} size={22} />} value={summary.data.summary.excused} label="Excused" />
                  <Metric icon={<Clock3 color={colors.inkMuted} size={22} />} value={summary.data.summary.not_marked} label="Not marked" />
                </View>
              </>
            ) : null}
            <GlassCard style={styles.queueCard}>
              <Text style={styles.queueTitle}>This device</Text>
              <Text style={styles.queueValue}>{pending} pending · {rejected} rejected</Text>
              <PrimaryButton label="Synchronize now" loading={syncing} disabled={!trips.selectedTripId || pending === 0} onPress={() => void retry()} />
              {rejected > 0 ? (
                <PrimaryButton
                  label="Acknowledge rejected scans"
                  tone="secondary"
                  onPress={() => {
                    if (trips.selectedTripId) {
                      void acknowledgeRejectedAttendance(trips.selectedTripId).then(() => queueQuery.refetch());
                    }
                  }}
                />
              ) : null}
            </GlassCard>
            <GlassCard style={styles.createCard}>
              <Text style={styles.queueTitle}>New attendance activity</Text>
              <TextField
                label="Activity name"
                value={activityName}
                onChangeText={setActivityName}
                placeholder="Airport reporting"
                maxLength={160}
                error={activityError}
              />
              <PrimaryButton label="Create and select" loading={activityBusy} onPress={() => void createActivity()} />
            </GlassCard>
            {sessions.isPending ? <ContentLoading label="Loading attendance activities" /> : null}
            {sessions.isError ? <ContentError message="Attendance activities are not available offline." onRetry={() => void sessions.refetch()} /> : null}
            {sessions.data && sessions.data.items.length === 0 ? (
              <ContentEmpty title="No attendance activities" message="Create the first activity before scanning passenger QR codes." />
            ) : null}
          </View>
        }
        ListFooterComponent={
          <View style={styles.footer}>
            {detail.isPending && effectiveSessionId ? <ContentLoading label="Loading missing passengers" /> : null}
            {detail.isError ? <ContentError message="Activity details are not available offline." onRetry={() => void detail.refetch()} /> : null}
            {detail.data && detail.data.missing.length === 0 ? (
              <ContentEmpty title="No missing passengers" message="Everyone assigned to this activity has been scanned." />
            ) : null}
            {selectedActivity?.status === 'active' ? (
              <PrimaryButton label="Complete selected activity" tone="danger" loading={activityBusy} onPress={confirmCompletion} />
            ) : null}
          </View>
        }
      />
    </Screen>
  );
}

function Metric({ icon, value, label }: { icon: React.ReactNode; value: number; label: string }) {
  return <GlassCard style={styles.metric}>{icon}<Text style={styles.value}>{value.toLocaleString()}</Text><Text style={styles.label}>{label}</Text></GlassCard>;
}

const styles = StyleSheet.create({
  screen: { paddingHorizontal: 0 },
  list: { paddingHorizontal: spacing.lg, paddingBottom: 104 },
  header: { gap: spacing.lg, paddingBottom: spacing.md },
  footer: { gap: spacing.md, paddingTop: spacing.md },
  hero: { flexDirection: 'row', alignItems: 'center', gap: spacing.lg, backgroundColor: 'rgba(221,243,252,0.82)' },
  heroValue: { color: colors.ink, fontSize: 27, fontWeight: '900' },
  grid: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  metric: { width: '47%', minHeight: 118, borderRadius: radii.md, gap: spacing.xs },
  value: { color: colors.ink, fontSize: 22, fontWeight: '900', marginTop: spacing.sm },
  label: { color: colors.inkMuted, fontSize: 12 },
  queueCard: { gap: spacing.md, borderRadius: radii.md },
  createCard: { gap: spacing.md, borderRadius: radii.md },
  queueTitle: { color: colors.ink, fontSize: 17, fontWeight: '800' },
  queueValue: { color: colors.inkMuted, fontSize: 13 },
  sectionTitle: { color: colors.ink, fontSize: 19, fontWeight: '900', paddingTop: spacing.lg, paddingBottom: spacing.sm, backgroundColor: 'rgba(248,253,255,0.97)' },
  sessionRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, marginBottom: spacing.sm },
  viewedSession: { borderColor: colors.blue },
  sessionText: { flex: 1, gap: 3 },
  sessionName: { color: colors.ink, fontSize: 15, fontWeight: '800' },
  sessionMeta: { color: colors.inkMuted, fontSize: 12 },
  missingRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md, padding: spacing.md, marginBottom: spacing.sm },
  missingName: { flex: 1, color: colors.ink, fontSize: 14, fontWeight: '700' },
  pressed: { opacity: 0.7 },
});
