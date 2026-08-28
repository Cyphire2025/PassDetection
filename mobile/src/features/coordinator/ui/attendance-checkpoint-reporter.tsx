import { useEffect } from 'react';

import { useRouteFocus } from '@/core/query/use-route-focus';
import { recordAttendanceReconciliationAssessment } from '@/core/observability/attendance-observability';
import type { AttendanceSession } from '@/features/coordinator/api/coordinator-contracts';
import { publishAttendanceCloseoutCheckpoint } from '@/features/coordinator/data/attendance-closeout-checkpoint';
import { attendanceSessionQueueStatus } from '@/features/coordinator/data/attendance-queue';

const CLOSEOUT_CHECKPOINT_REFRESH_MS = 30_000;

type Props = Readonly<{
  session: AttendanceSession;
  tripId: string;
}>;

/**
 * Keeps the manager's privacy-bounded closeout evidence fresh without adding
 * operational detail to the coordinator's normal attendance screen.
 */
export function AttendanceCheckpointReporter({ session, tripId }: Props) {
  const focused = useRouteFocus();

  useEffect(() => {
    if (!focused) return;
    let active = true;
    void attendanceSessionQueueStatus(tripId, session.id)
      .then((status) => {
        if (active) {
          recordAttendanceReconciliationAssessment(
            session.scanned_count,
            session.assigned_count,
            status,
          );
        }
      })
      .catch(() => {
        if (active) {
          recordAttendanceReconciliationAssessment(
            session.scanned_count,
            session.assigned_count,
            null,
          );
        }
      });
    return () => {
      active = false;
    };
  }, [focused, session.assigned_count, session.id, session.scanned_count, tripId]);

  useEffect(() => {
    if (!focused || session.status !== 'active') return;
    let publishing = false;
    const publish = async () => {
      if (publishing) return;
      publishing = true;
      try {
        await publishAttendanceCloseoutCheckpoint(tripId, session.id);
      } catch {
        // Synchronization and the next interval remain the recovery path.
      } finally {
        publishing = false;
      }
    };
    void publish();
    const refreshTimer = setInterval(() => void publish(), CLOSEOUT_CHECKPOINT_REFRESH_MS);
    return () => clearInterval(refreshTimer);
  }, [focused, session.id, session.status, tripId]);

  return null;
}
