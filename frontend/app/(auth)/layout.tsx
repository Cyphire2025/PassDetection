/**
 * Auth Layout — Light Theme
 */
import type { Metadata } from "next";
import Image from "next/image";
import loginBackground from "../../public/globalconnectteam.png";

export const metadata: Metadata = { title: "Sign In" };

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative min-h-dvh overflow-x-clip overflow-y-auto bg-slate-900">
      <Image
        src={loginBackground}
        alt=""
        fill
        sizes="100vw"
        preload
        className="pointer-events-none object-cover object-center"
      />
      <div className="pointer-events-none absolute inset-0 bg-slate-950/25" aria-hidden="true" />

      <main className="relative z-10 flex min-h-dvh items-end justify-center pb-[max(1.5rem,env(safe-area-inset-bottom))] pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] pt-[clamp(8rem,40dvh,28rem)]">
        <div className="w-full max-w-sm">
          <div className="rounded-2xl border border-white/20 bg-slate-950/70 shadow-2xl">
            {children}
          </div>

          <p className="mt-2 text-center text-xs font-medium text-white drop-shadow-[0_1px_2px_rgba(0,0,0,0.95)]">
            © {new Date().getFullYear()} Global Connects Dashboard. All rights reserved.
          </p>
        </div>
      </main>
    </div>
  );
}
