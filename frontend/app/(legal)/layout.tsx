import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

export default function LegalLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-white text-slate-900">
      <header className="border-b border-slate-200">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-4 px-5 py-4">
          <Link href="/" aria-label="Global Connect Travels home">
            <Image
              src="/globalconnect-logo.png"
              alt="Global Connect Travels"
              width={150}
              height={56}
              className="h-auto w-32"
              priority
            />
          </Link>
          <nav aria-label="Legal pages" className="flex gap-4 text-sm">
            <Link
              className="text-blue-700 hover:underline"
              href={"/privacy-policy" as never}
            >
              Privacy
            </Link>
            <Link
              className="text-blue-700 hover:underline"
              href={"/terms" as never}
            >
              Terms
            </Link>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-5 py-10">{children}</main>

      <footer className="border-t border-slate-200">
        <div className="mx-auto max-w-3xl px-5 py-6 text-sm text-slate-600">
          © Global Connect Travels. All rights reserved.
        </div>
      </footer>
    </div>
  );
}
