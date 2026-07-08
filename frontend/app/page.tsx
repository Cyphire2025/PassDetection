/**
 * Root Page - Light Theme Phase Status
 */

import Link from "next/link";
import { Button } from "@/components/ui";

export default function RootPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center bg-slate-50 px-6">
      <div className="w-full max-w-md text-center">
        <div className="mx-auto mb-6 flex h-12 w-12 items-center justify-center rounded-xl bg-blue-600">
          <svg width="22" height="22" viewBox="0 0 32 32" fill="none" aria-hidden="true">
            <rect x="4" y="4" width="24" height="24" rx="3" fill="white" fillOpacity="0.2" />
            <rect x="8" y="10" width="16" height="2" rx="1" fill="white" />
            <rect x="8" y="14" width="12" height="2" rx="1" fill="white" />
            <rect x="8" y="18" width="16" height="2" rx="1" fill="white" />
            <rect x="8" y="22" width="8" height="2" rx="1" fill="white" />
          </svg>
        </div>

        <h1 className="mb-1 text-2xl font-bold text-slate-900">PassDetection</h1>
        <p className="mb-8 text-sm text-slate-500">Enterprise Passport MRZ Platform</p>

        <div className="rounded-xl border border-slate-200 bg-white p-6 text-left shadow-sm">
          <div className="mb-4 flex items-center gap-2">
            <span className="h-2 w-2 rounded-full bg-green-500" />
            <span className="text-xs font-semibold text-green-700">Phases 1 through 13 shipped</span>
          </div>

          <ul className="space-y-2 text-sm text-slate-600">
            {[
              "Clean Architecture with backend and frontend feature modules",
              "FastAPI backend with async SQLAlchemy",
              "PostgreSQL, Redis, and MinIO-backed local stack",
              "Agency dashboard and secure upload links",
              "LAN-accessible public upload flow",
              "Smart camera with passport frame detection",
              "Blur detection and lighting guidance",
              "Mobile-first scanner with glare detection",
              "Perspective correction before upload",
              "Hands-free auto capture for stable scans",
              "MRZ-only extraction from passport photos and uploads",
              "Review-ready passport list and detail workspace",
              "Editable field review and confirmation flow",
              "Phase 14 next: field-level confidence scoring",
            ].map((item) => (
              <li key={item} className="flex items-start gap-2">
                <span className="mt-0.5 text-green-500">+</span>
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="mt-6">
          <Link href="/dashboard">
            <Button
              size="lg"
              className="w-full bg-blue-600 py-2.5 font-semibold text-white shadow-sm transition-all duration-200 hover:bg-blue-700"
            >
              Enter Platform
            </Button>
          </Link>
        </div>

        <p className="mt-6 text-xs text-slate-400">PassDetection v1.0.0 - Phase 13</p>
      </div>
    </main>
  );
}
