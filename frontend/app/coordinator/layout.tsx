import { AuthenticatedContent } from "@/features/auth/components/authenticated-content";
import { AuthHydrator } from "@/features/auth/components/auth-hydrator";
import { CoordinatorAccessLevelBar } from "@/features/auth/components/access-level-switcher";
import { DashboardRealtimeAttendanceBridge } from "@/features/operations/components/dashboard-realtime-attendance-bridge";
import { CoordinatorOfflineScanDrain } from "@/features/tour-operations/components/coordinator-offline-scan-drain";

export default function CoordinatorLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <AuthHydrator />
      <AuthenticatedContent>
        <CoordinatorAccessLevelBar />
        <DashboardRealtimeAttendanceBridge />
        <CoordinatorOfflineScanDrain />
        {children}
      </AuthenticatedContent>
    </>
  );
}
