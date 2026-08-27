import { useCallback, useEffect, useRef, useState } from 'react';

import { offlineAuthorizationReadiness } from '@/core/auth/session-service';
import { useRealtimeStatusStore } from '@/core/realtime/realtime-status';
import type { AttendanceSession } from '@/features/coordinator/api/coordinator-contracts';
import { attendanceTripQueueStatus } from '@/features/coordinator/data/attendance-queue';
import { loadDeviceEventReadiness } from '@/features/coordinator/data/device-event-readiness';
import {
  assessCoordinatorEventReadiness,
  loadCoordinatorReadinessEvidence,
  type EventReadinessAssessment,
  type EventReadinessCaptureGate,
} from '@/features/coordinator/data/event-readiness';

type EventReadinessInputs = Readonly<{
  activity: AttendanceSession | null;
  cameraGranted: boolean;
  refreshSignal: string;
  tripId: string | null;
}>;

export type CoordinatorEventReadiness = Readonly<{
  assessment: EventReadinessAssessment;
  captureGate: EventReadinessCaptureGate;
  loading: boolean;
  refresh: () => Promise<void>;
  verificationIncomplete: boolean;
}>;

const INITIAL_ASSESSMENT: EventReadinessAssessment = {
  status: 'blocked',
  checks: [],
};

export function useCoordinatorEventReadiness({
  activity,
  cameraGranted,
  refreshSignal,
  tripId,
}: EventReadinessInputs): CoordinatorEventReadiness {
  const realtimeStatus = useRealtimeStatusStore((state) => state.status);
  const loadVersion = useRef(0);
  const [assessment, setAssessment] = useState(INITIAL_ASSESSMENT);
  const [verificationIncomplete, setVerificationIncomplete] = useState(false);
  const [verifiedSignature, setVerifiedSignature] = useState<string | null>(null);
  const [manualLoading, setManualLoading] = useState(false);
  const activitySelected = activity !== null;
  const scheduleStartsAt = activity?.scheduled_starts_at ?? null;
  const scheduleEndsAt = activity?.scheduled_ends_at ?? null;
  const scheduleTimeZone = activity?.schedule_timezone ?? null;
  const scheduleVersion = activity?.schedule_version ?? 1;
  const inputSignature = [
    tripId ?? 'no-trip',
    activity?.id ?? 'no-activity',
    activity?.scheduled_starts_at ?? 'no-schedule-start',
    activity?.scheduled_ends_at ?? 'no-schedule-end',
    activity?.schedule_timezone ?? 'no-schedule-zone',
    activity?.schedule_version ?? 'no-schedule-version',
    cameraGranted ? 'camera' : 'no-camera',
    realtimeStatus,
    refreshSignal,
  ].join(':');

  const load = useCallback(async (signature: string) => {
    const version = loadVersion.current + 1;
    loadVersion.current = version;
    if (!tripId || !activitySelected) {
      await Promise.resolve();
      if (loadVersion.current !== version) return;
      setVerificationIncomplete(false);
      setAssessment(assessCoordinatorEventReadiness({
        activitySelected,
        cameraGranted,
        device: null,
        evidence: null,
        offlineAuthorization: null,
        queue: null,
        realtimeStatus,
        schedule: null,
        tripSelected: tripId !== null,
      }));
      setVerifiedSignature(signature);
      return;
    }

    const [evidenceResult, authorizationResult, queueResult, deviceResult] = await Promise.allSettled([
      loadCoordinatorReadinessEvidence(tripId),
      offlineAuthorizationReadiness(),
      attendanceTripQueueStatus(tripId),
      loadDeviceEventReadiness(tripId),
    ]);
    if (loadVersion.current !== version) return;
    const incomplete = evidenceResult.status === 'rejected'
      || authorizationResult.status === 'rejected'
      || queueResult.status === 'rejected'
      || deviceResult.status === 'rejected';
    setVerificationIncomplete(incomplete);
    setAssessment(assessCoordinatorEventReadiness({
      activitySelected,
      cameraGranted,
      device: deviceResult.status === 'fulfilled' ? deviceResult.value : null,
      evidence: evidenceResult.status === 'fulfilled' ? evidenceResult.value : null,
      offlineAuthorization: authorizationResult.status === 'fulfilled'
        ? authorizationResult.value
        : null,
      queue: queueResult.status === 'fulfilled' ? queueResult.value : null,
      realtimeStatus,
      schedule: {
        endsAt: scheduleEndsAt,
        startsAt: scheduleStartsAt,
        timeZone: scheduleTimeZone,
        version: scheduleVersion,
      },
      tripSelected: true,
    }));
    setVerifiedSignature(signature);
  }, [
    activitySelected,
    cameraGranted,
    realtimeStatus,
    scheduleEndsAt,
    scheduleStartsAt,
    scheduleTimeZone,
    scheduleVersion,
    tripId,
  ]);

  useEffect(() => {
    void load(inputSignature);
    return () => {
      loadVersion.current += 1;
    };
  }, [inputSignature, load]);

  const refresh = useCallback(async () => {
    setManualLoading(true);
    try {
      await load(inputSignature);
    } finally {
      setManualLoading(false);
    }
  }, [inputSignature, load]);
  const loading = manualLoading || verifiedSignature !== inputSignature;

  return {
    assessment,
    captureGate: loading ? 'loading' : verificationIncomplete ? 'blocked' : assessment.status,
    loading,
    refresh,
    verificationIncomplete,
  };
}
