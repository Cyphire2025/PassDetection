/**
 * Auth Layout — Light Theme
 */
import type { Metadata } from "next";
export const metadata: Metadata = { title: "Sign In" };

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <div className="w-full max-w-sm">
        {/* Brand */}
        <div className="mb-8 flex flex-col items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600">
            <svg width="20" height="20" viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <rect x="4" y="4" width="24" height="24" rx="3" fill="white" fillOpacity="0.2" />
              <rect x="8" y="10" width="16" height="2" rx="1" fill="white" />
              <rect x="8" y="14" width="12" height="2" rx="1" fill="white" />
              <rect x="8" y="18" width="16" height="2" rx="1" fill="white" />
            </svg>
          </div>
          <span className="text-lg font-bold text-slate-900">PassDetection</span>
        </div>

        {children}

        <p className="mt-8 text-center text-xs text-slate-400">
          © {new Date().getFullYear()} PassDetection. All rights reserved.
        </p>
      </div>
    </div>
  );
}
