import { useRouter } from 'expo-router';
import AlertTriangle from 'lucide-react-native/icons/triangle-alert';
import CheckCircle2 from 'lucide-react-native/icons/circle-check-big';
import ChevronRight from 'lucide-react-native/icons/chevron-right';
import Clock3 from 'lucide-react-native/icons/clock-3';
import { useCallback, useEffect, useMemo, useState } from 'react';
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
import { useRouteFocus } from '@/core/query/use-route-focus';
import { ContentEmpty, ContentError, ContentLoading } from '@/design/components/content-state';
import { GlassCard } from '@/design/components/glass-card';
import { PrimaryButton } from '@/design/components/primary-button';
import { Screen } from '@/design/components/screen';
import { StatusPill } from '@/design/components/status-pill';
import { TextField } from '@/design/components/text-field';
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
  completeManagerAttendanceSession,
  createManagerAttendanceSession,
  loadManagerAttendanceCloseoutStatus,
  type AttendanceCloseoutStatus,
} from '@/features/manager/data/manager-operations';
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
const MANAGER_CLOSEOUT_REFRESH_MS = 30_000;

export default function ManagerAttendanceScreen() {
  const router = useRouter();
  const focused = useRouteFocus();
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
  const [closeBusy, setCloseBusy] = useState(false);
  const [closeError, setCloseError] = useState<{ tripId: string; message: string } | null>(null);
  const effectiveCloseError = closeError?.tripId === trips.selectedTripId ? closeError.message : null;
  const closeoutKey = trips.selectedTripId && effectiveSessionId
    ? `${trips.selectedTripId}:${effectiveSessionId}`
    : null;
  const [closeoutEvidence, setCloseoutEvidence] = useState<Readonly<{
    error: boolean;
    key: string;
    loading: boolean;
    status: AttendanceCloseoutStatus | null;
  }> | null>(null);
  const selectedCloseout = closeoutKey && closeoutEvidence?.key === closeoutKey
    ? closeoutEvidence.status
    : null;
  const closeoutLoading = Boolean(
    closeoutKey
    && (closeoutEvidence?.key !== closeoutKey || closeoutEvidence.loading),
  );
  const closeoutUnavailable = Boolean(
    closeoutKey
    && closeoutEvidence?.key === closeoutKey
    && closeoutEvidence.error,
  );
  const [exceptionDraft, setExceptionDraft] = useState<Readonly<{
    key: string;
    reason: string;
  }> | null>(null);
  const exceptionReason = closeoutKey && exceptionDraft?.key === closeoutKey
    ? exceptionDraft.reason
    : '';
  const [activityDraft, setActivityDraft] = useState<{ tripId: string; name: string } | null>(null);
  const activityName = activityDraft?.tripId === trips.selectedTripId ? activityDraft.name : '';
  const [createBusy, setCreateBusy] = useState(false);
  const [createNotice, setCreateNotice] = useState<{
    tripId: string;
    kind: 'error' | 'success';
    message: string;
  } | null>(null);
  const effectiveCreateNotice = createNotice?.tripId === trips.selectedTripId ? createNotice : null;

  useEffect(() => {
    const tripId = trips.selectedTripId;
    const sessionId = selectedActivity?.status === 'active' ? selectedActivity.id : null;
    if (!focused || !tripId || !sessionId) return;
    const key = `${tripId}:${sessionId}`;
    let active = true;
    let loading = false;
    const refresh = async () => {
      if (loading) return;
      loading = true;
      setCloseoutEvidence((current) => ({
        error: false,
        key,
        loading: true,
        status: current?.key === key ? current.status : null,
      }));
      try {
        const status = await loadManagerAttendanceCloseoutStatus(tripId, sessionId);
        if (active) setCloseoutEvidence({ error: false, key, loading: false, status });
      } catch {
        if (active) setCloseoutEvidence({ error: true, key, loading: false, status: null });
      } finally {
        loading = false;
      }
    };
    void refresh();
    const refreshTimer = setInterval(() => void refresh(), MANAGER_CLOSEOUT_REFRESH_MS);
    return () => {
      active = false;
      clearInterval(refreshTimer);
    };
  }, [focused, selectedActivity?.id, selectedActivity?.status, trips.selectedTripId]);

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

  const createActivity = useCallback(() => {
    const tripId = trips.selectedTripId;
    const normalizedName = activityName.trim();
    if (!tripId || normalizedName.length < 2 || createBusy) return;
    setCreateBusy(true);
    setCreateNotice(null);
    void createManagerAttendanceSession(tripId, normalizedName)
      .then(async (created) => {
        setActivityDraft({ tripId, name: '' });
        setSelectedId(created.id);
        try {
          const result = await sessions.refetch();
          if (!result.error) {
            setCreateNotice({
              tripId,
              kind: 'success',
              message: `${created.name} is ready for coordinators to select.`,
            });
            return;
          }
        } catch {
          // A successful mutation stays successful even if the follow-up query rejects.
        }
        setCreateNotice({
          tripId,
          kind: 'error',
          message: `${created.name} is ready, but the latest activity list could not be loaded.`,
        });
      }, (caught: unknown) => {
        setCreateNotice({
          tripId,
          kind: 'error',
          message: userFacingErrorMessage(caught, 'The attendance activity could not be created.'),
        });
      })
      .finally(() => setCreateBusy(false));
  }, [activityName, createBusy, sessions, trips.selectedTripId]);

  const closeSelectedActivity = useCallback(() => {
    const tripId = trips.selectedTripId;
    if (!tripId || !selectedActivity || selectedActivity.status !== 'active') return;
    const selectedActivityId = selectedActivity.id;
    setCloseBusy(true);
    setCloseError(null);
    void Promise.all([
      sessions.refetch(),
      loadManagerAttendanceCloseoutStatus(tripId, selectedActivityId),
    ])
      .then(([sessionsResult, closeout]) => {
        const key = `${tripId}:${selectedActivityId}`;
        setCloseoutEvidence({ error: false, key, loading: false, status: closeout });
        if (sessionsResult.error) {
          setCloseError({
            tripId,
            message: 'The authoritative server count and coordinator checkpoints could not be refreshed, so the activity was not closed.',
          });
          return;
        }
        const authoritative = sessionsResult.data?.items.find(
          (session) => session.id === selectedActivityId,
        );
        if (!authoritative) {
          setCloseError({
            tripId,
            message: 'The authoritative activity could not be refreshed, so it was not closed.',
          });
          return;
        }
        if (authoritative.status !== 'active') {
          setCloseError({
            tripId,
            message: 'This activity is already closed. The latest server status is now displayed.',
          });
          return;
        }
        const normalizedExceptionReason = exceptionReason.trim().replace(/\s+/g, ' ');
        if (
          !closeout.ready
          && (normalizedExceptionReason.length < 10 || normalizedExceptionReason.length > 500)
        ) {
          setCloseError({
            tripId,
            message: 'Enter an operational manager-exception reason between 10 and 500 characters.',
          });
          return;
        }
        const exceptionUsed = !closeout.ready;
        const serverCount = `${authoritative.scanned_count} of ${authoritative.assigned_count}`;
        Alert.alert(
          exceptionUsed ? 'Review audited manager exception' : 'Review guarded close',
          exceptionUsed
            ? closeout.active_assignment_count === 0
              ? `The server confirms ${serverCount} passengers, but no coordinator account is assigned and no affirmative checkpoint evidence exists. Exception reason: "${normalizedExceptionReason}".`
              : `${closeout.blocked_assignment_count} of ${closeout.active_assignment_count} coordinator checkpoints are missing, stale, or nonzero, with ${closeout.unresolved_count} unresolved items reported. Exception reason: "${normalizedExceptionReason}".`
            : `The server confirms ${serverCount} passengers and all ${closeout.active_assignment_count} assigned coordinator accounts recently reported clear. Scans saved before closure can still reconcile.`,
          [
            { text: 'Cancel', style: 'cancel' },
            {
              text: 'Continue',
              onPress: () => Alert.alert(
                exceptionUsed ? 'Override the closeout guard?' : 'Close for every coordinator?',
                exceptionUsed
                  ? 'Final warning: close despite coordinator checkpoint blockers and permanently audit this manager exception? This does not discard scans already saved before closure.'
                  : 'This shared activity will stop accepting new camera capture for every coordinator. This action does not discard scans already saved before closure.',
                [
                  { text: 'Cancel', style: 'cancel' },
                  {
                    text: exceptionUsed ? 'Override and close' : 'Close activity',
                    style: 'destructive',
                    onPress: () => {
                      setCloseBusy(true);
                      setCloseError(null);
                      void completeManagerAttendanceSession(
                        tripId,
                        authoritative.id,
                        exceptionUsed ? normalizedExceptionReason : undefined,
                      )
                        .then(async () => {
                          if (exceptionUsed) {
                            setExceptionDraft((current) => (
                              current?.key === key ? { key, reason: '' } : current
                            ));
                          }
                          try {
                            const [sessionsResult, rosterResult] = await Promise.all([
                              sessions.refetch(),
                              expandedStatus ? roster.refetch() : Promise.resolve(null),
                            ]);
                            if (!sessionsResult.error && !rosterResult?.error) return;
                          } catch {
                            // The query client can reject when explicitly configured to throw.
                          }
                          setCloseError({
                            tripId,
                            message: 'The shared activity was closed, but the latest status could not be loaded.',
                          });
                        }, (caught: unknown) => {
                          setCloseError({
                            tripId,
                            message: userFacingErrorMessage(caught, 'The shared activity could not be closed.'),
                          });
                        })
                        .finally(() => setCloseBusy(false));
                    },
                  },
                ],
              ),
            },
          ],
        );
      }, () => {
        setCloseError({
          tripId,
          message: 'The authoritative coordinator closeout evidence could not be refreshed, so the activity was not closed.',
        });
      })
      .finally(() => setCloseBusy(false));
  }, [exceptionReason, expandedStatus, roster, selectedActivity, sessions, trips.selectedTripId]);

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
        {...MOBILE_LIST_WINDOWING.denseRoster}
        contentContainerStyle={styles.list}
        refreshControl={(
          <RefreshControl
            refreshing={sessions.isRefetching || roster.isRefetching || Boolean(closeoutEvidence?.loading)}
            onRefresh={() => void Promise.all([
              sessions.refetch(),
              ...(expandedStatus ? [roster.refetch()] : []),
              ...(trips.selectedTripId && selectedActivity?.status === 'active' ? [
                loadManagerAttendanceCloseoutStatus(
                  trips.selectedTripId,
                  selectedActivity.id,
                ).then((status) => {
                  setCloseoutEvidence({
                    error: false,
                    key: `${trips.selectedTripId}:${selectedActivity.id}`,
                    loading: false,
                    status,
                  });
                }),
              ] : []),
            ])}
          />
        )}
        ListHeaderComponent={(
          <View style={styles.header}>
            <OperationHeader title="Attendance" subtitle={trips.selectedTrip?.name || 'Selected group'} />
            <GlassCard style={styles.createCard}>
              <Text style={styles.createTitle}>Prepare attendance activity</Text>
              <Text style={styles.createHelp}>
                Create the canonical name and stable ID before coordinators scan.
              </Text>
              <TextField
                label="Activity name"
                value={activityName}
                onChangeText={(name) => {
                  if (trips.selectedTripId) setActivityDraft({ tripId: trips.selectedTripId, name });
                }}
                placeholder="Airport reporting count"
                autoCapitalize="sentences"
                autoCorrect={false}
                editable={!createBusy}
                maxLength={160}
                returnKeyType="done"
                onSubmitEditing={createActivity}
              />
              <PrimaryButton
                label="Create activity"
                loading={createBusy}
                disabled={activityName.trim().length < 2}
                onPress={createActivity}
              />
              {effectiveCreateNotice ? (
                effectiveCreateNotice.kind === 'error' ? (
                  <ContentError message={effectiveCreateNotice.message} />
                ) : (
                  <Text accessibilityLiveRegion="polite" style={styles.createSuccess}>
                    {effectiveCreateNotice.message}
                  </Text>
                )
              ) : null}
            </GlassCard>
            {sessions.isPending ? <ContentLoading label="Loading attendance activities" /> : null}
            {sessions.isError ? (
              <ContentError message="Attendance activities could not be loaded." onRetry={() => void sessions.refetch()} />
            ) : null}
            {effectiveCloseError ? <ContentError message={effectiveCloseError} /> : null}
            {sessions.data && activities.length === 0 ? (
              <ContentEmpty title="No attendance activity" message="Create the first canonical activity above." />
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
            {selectedActivity?.status === 'active' ? (
              <>
                <GlassCard style={styles.closeoutCard}>
                  <View style={styles.closeoutTitleRow}>
                    <Text accessibilityRole="header" style={styles.closeoutTitle}>
                      Coordinator closeout checkpoints
                    </Text>
                    {selectedCloseout ? (
                      <StatusPill
                        label={selectedCloseout.ready ? 'Clear' : 'Blocked'}
                        tone={selectedCloseout.ready ? 'good' : 'warning'}
                      />
                    ) : null}
                  </View>
                  {closeoutLoading ? (
                    <ContentLoading label="Loading coordinator checkpoints" />
                  ) : null}
                  {closeoutUnavailable ? (
                    <ContentError message="Coordinator checkpoint evidence is unavailable. Closeout is disabled until it can be refreshed." />
                  ) : null}
                  {selectedCloseout ? (
                    <>
                      <Text style={selectedCloseout.ready ? styles.closeoutReady : styles.closeoutBlocked}>
                        {selectedCloseout.ready
                          ? `${selectedCloseout.ready_assignment_count} of ${selectedCloseout.active_assignment_count} assigned coordinator accounts recently reported zero unresolved items.`
                          : selectedCloseout.active_assignment_count === 0
                            ? 'No coordinator account is assigned. An audited manager exception is required to close.'
                            : `${selectedCloseout.blocked_assignment_count} of ${selectedCloseout.active_assignment_count} coordinator checkpoints are missing, stale, or nonzero; ${selectedCloseout.unresolved_count} unresolved items are reported.`}
                      </Text>
                      <Text style={styles.closeoutHelp}>
                        Checkpoints expire after {selectedCloseout.checkpoint_ttl_seconds} seconds.
                        They are count-only latest reports for assigned coordinator accounts, not proof about every physical device.
                      </Text>
                      {selectedCloseout.coordinators.map((coordinator) => {
                        const unresolved = coordinator.pending_count
                          + coordinator.sending_count
                          + coordinator.retryable_count
                          + coordinator.needs_review_count
                          + coordinator.unreviewed_rejected_count;
                        return (
                          <View key={coordinator.coordinator_id} style={styles.coordinatorCheckpoint}>
                            <Text style={styles.coordinatorName}>{coordinator.coordinator_name}</Text>
                            <Text style={styles.coordinatorState}>
                              {coordinator.state} · {unresolved} unresolved
                            </Text>
                          </View>
                        );
                      })}
                      {!selectedCloseout.ready ? (
                        <View style={styles.exceptionBox}>
                          <Text style={styles.exceptionTitle}>Audited manager exception</Text>
                          <Text style={styles.exceptionHelp}>
                            Use only for an operational emergency. Do not enter passenger names,
                            QR values, passport details, or other personal information.
                          </Text>
                          <TextField
                            label="Operational exception reason"
                            value={exceptionReason}
                            onChangeText={(reason) => {
                              if (closeoutKey) setExceptionDraft({ key: closeoutKey, reason });
                            }}
                            placeholder="Document the emergency and approval"
                            autoCapitalize="sentences"
                            autoCorrect={false}
                            editable={!closeBusy}
                            maxLength={500}
                          />
                        </View>
                      ) : null}
                    </>
                  ) : null}
                </GlassCard>
                <PrimaryButton
                  label={selectedCloseout?.ready
                    ? 'Close after clear checkpoints'
                    : 'Override checkpoint guard and close'}
                  tone="danger"
                  loading={closeBusy}
                  disabled={
                    !selectedCloseout
                    || (!selectedCloseout.ready && (
                      exceptionReason.trim().replace(/\s+/g, ' ').length < 10
                      || exceptionReason.trim().replace(/\s+/g, ' ').length > 500
                    ))
                  }
                  onPress={closeSelectedActivity}
                />
              </>
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
  createCard: { gap: spacing.md },
  createTitle: { color: colors.ink, fontSize: 17, fontWeight: '900' },
  createHelp: { color: colors.inkMuted, fontSize: 13, lineHeight: 19 },
  createSuccess: { color: colors.greenDeep, fontSize: 13, fontWeight: '800' },
  footer: { gap: spacing.md, paddingTop: spacing.md },
  closeoutCard: { gap: spacing.md },
  closeoutTitleRow: { flexDirection: 'row', alignItems: 'center', gap: spacing.md },
  closeoutTitle: { flex: 1, color: colors.ink, fontSize: 17, fontWeight: '900' },
  closeoutReady: { color: colors.greenDeep, fontSize: 13, fontWeight: '800', lineHeight: 19 },
  closeoutBlocked: { color: colors.warning, fontSize: 13, fontWeight: '800', lineHeight: 19 },
  closeoutHelp: { color: colors.inkMuted, fontSize: 11, lineHeight: 17 },
  coordinatorCheckpoint: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    padding: spacing.sm,
  },
  coordinatorName: { flex: 1, color: colors.ink, fontSize: 12, fontWeight: '800' },
  coordinatorState: { color: colors.inkMuted, fontSize: 11, textTransform: 'capitalize' },
  exceptionBox: {
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.warning,
    borderRadius: 10,
    padding: spacing.md,
  },
  exceptionTitle: { color: colors.warning, fontSize: 13, fontWeight: '900' },
  exceptionHelp: { color: colors.inkMuted, fontSize: 11, lineHeight: 17 },
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
