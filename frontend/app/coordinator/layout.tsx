import { AuthenticatedContent } from "@/features/auth/components/authenticated-content";
import { AuthHydrator } from "@/features/auth/components/auth-hydrator";
import { DashboardRealtimeAttendanceBridge } from "@/features/operations/components/dashboard-realtime-attendance-bridge";
import { CoordinatorOfflineScanDrain } from "@/features/tour-operations/components/coordinator-offline-scan-drain";

export default function CoordinatorLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <AuthHydrator />
      <AuthenticatedContent>
        <DashboardRealtimeAttendanceBridge />
        <CoordinatorOfflineScanDrain />
        {children}
      </AuthenticatedContent>
    </>
  );
}
