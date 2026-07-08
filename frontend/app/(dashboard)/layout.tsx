/**
 * Dashboard Layout — Light Theme
 */
import { Sidebar } from "@/components/layout/sidebar";
import { Header } from "@/components/layout/header";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-[100svh] w-full overflow-hidden bg-slate-50">
      <div className="hidden lg:flex">
        <Sidebar />
      </div>
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Header />
        <main className="min-w-0 flex-1 overflow-x-hidden overflow-y-auto" id="main-content">
          <div className="mx-auto w-full max-w-6xl px-4 py-5 sm:px-6 sm:py-7">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
