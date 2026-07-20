/**
 * Auth Layout — Light Theme
 */
import type { Metadata } from "next";
import { BrandLogo } from "@/components/brand/brand-logo";

export const metadata: Metadata = { title: "Sign In" };

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm">
        {/* Brand */}
        <div className="mb-8 flex justify-center">
          <BrandLogo className="h-16 w-[240px]" priority />
        </div>

        {children}

        <p className="mt-8 text-center text-xs text-slate-400">
          © {new Date().getFullYear()} Global Connects Dashboard. All rights reserved.
        </p>
      </div>
    </div>
  );
}
