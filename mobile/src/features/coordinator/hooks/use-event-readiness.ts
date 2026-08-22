import { useCallback, useEffect, useRef, useState } from 'react';

import { offlineAuthorizationReadiness } from '@/core/auth/session-service';
import { useRealtimeStatusStore } from '@/core/realtime/realtime-status';
import { attendanceTripQueueStatus } from '@/features/coordinator/data/attendance-queue';
import { loadDeviceEventReadiness } from '@/features/coordinator/data/device-event-readiness';
import {
  assessCoordinatorEventReadiness,
  loadCoordinatorReadinessEvidence,
  type EventReadinessAssessment,
  type EventReadinessCaptureGate,
} from '@/features/coordinator/data/event-readiness';

type EventReadinessInputs = Readonly<{
  activityId: string | null;
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
  activityId,
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
  const inputSignature = [
    tripId ?? 'no-trip',
    activityId ?? 'no-activity',
    cameraGranted ? 'camera' : 'no-camera',
    realtimeStatus,
    refreshSignal,
  ].join(':');

  const load = useCallback(async (signature: string) => {
    const version = loadVersion.current + 1;
    loadVersion.current = version;
    const activitySelected = activityId !== null;
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
      tripSelected: true,
    }));
    setVerifiedSignature(signature);
  }, [activityId, cameraGranted, realtimeStatus, tripId]);

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
