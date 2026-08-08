/**
 * Dashboard Layout — Light Theme
 */
import { Sidebar } from "@/components/layout/sidebar";
import { Header } from "@/components/layout/header";
import { AuthenticatedContent } from "@/features/auth/components/authenticated-content";
import { AuthHydrator } from "@/features/auth/components/auth-hydrator";
import { WhatsAppActivityTrackerProvider } from "@/features/whatsapp/components/whatsapp-activity-tracker";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <AuthHydrator />
      <AuthenticatedContent>
        <WhatsAppActivityTrackerProvider>
          <div
            className="fixed inset-0 flex min-h-0 w-full overflow-hidden overscroll-none bg-slate-50"
            data-dashboard-shell
          >
            <div className="hidden min-h-0 shrink-0 lg:flex">
              <Sidebar />
            </div>
            <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
              <Header />
              <main
                className="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-y-contain"
                id="main-content"
              >
                <div className="mx-auto w-full max-w-6xl px-4 py-5 sm:px-6 sm:py-7">
                  {children}
                </div>
              </main>
            </div>
          </div>
        </WhatsAppActivityTrackerProvider>
      </AuthenticatedContent>
    </>
  );
}
