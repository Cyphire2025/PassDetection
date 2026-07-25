import { AuthHydrator } from "@/features/auth/components/auth-hydrator";
import { CoordinatorOfflineScanDrain } from "@/features/tour-operations/components/coordinator-offline-scan-drain";

export default function CoordinatorLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <AuthHydrator />
      <CoordinatorOfflineScanDrain />
      {children}
    </>
  );
}
