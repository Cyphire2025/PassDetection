/**
 * Auth Layout — Light Theme
 */
import type { Metadata } from "next";

export const metadata: Metadata = { title: "Sign In" };

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div
      className="relative min-h-dvh overflow-y-auto bg-slate-900 bg-cover bg-center bg-no-repeat"
      style={{ backgroundImage: "url('/globalconnectteam.png')" }}
    >
      <div className="pointer-events-none absolute inset-0 bg-slate-950/15" aria-hidden="true" />

      <main className="relative z-10 flex min-h-dvh items-end justify-center px-4 pb-6 pt-[44vh] sm:pb-8">
        <div className="w-full max-w-sm translate-y-[3vh]">
          {children}

          <p className="mt-2 text-center text-xs font-medium text-white drop-shadow-[0_1px_2px_rgba(0,0,0,0.95)]">
            © {new Date().getFullYear()} Global Connects Dashboard. All rights reserved.
          </p>
        </div>
      </main>
    </div>
  );
}
