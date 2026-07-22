"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { WhatsAppPage } from "@/features/whatsapp/components/whatsapp-page";
import { ROUTES } from "@/constants/routes";
import { canAccessWhatsAppBroadcasts } from "@/lib/utils/role-access";
import {
  selectHasHydrated,
  selectUserRole,
  useAuthStore,
} from "@/stores/auth.store";

export default function DashboardWhatsAppPage() {
  const router = useRouter();
  const hasHydrated = useAuthStore(selectHasHydrated);
  const role = useAuthStore(selectUserRole);
  const canAccessWhatsApp = canAccessWhatsAppBroadcasts(role);

  useEffect(() => {
    if (!hasHydrated || role === null || canAccessWhatsApp) return;
    router.replace(
      (role === "agency_coordinator"
        ? ROUTES.coordinator
        : ROUTES.dashboard.passports) as never,
    );
  }, [canAccessWhatsApp, hasHydrated, role, router]);

  if (!hasHydrated || !canAccessWhatsApp) return null;

  return <WhatsAppPage />;
}
