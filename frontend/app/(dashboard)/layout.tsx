/**
 * Dashboard Layout — Light Theme
 */
import { Sidebar } from "@/components/layout/sidebar";
import { Header } from "@/components/layout/header";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <Sidebar />
      <div className="flex flex-1 flex-col overflow-hidden">
        <Header />
        <main className="flex-1 overflow-y-auto" id="main-content">
          <div className="mx-auto max-w-6xl px-6 py-7">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}
