import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import { connection } from "next/server";
import "./globals.css";
import { PwaRegistrar } from "@/components/pwa/pwa-registrar";
import { QueryProvider } from "@/providers/query-provider";
import { QueueSafeSignOutGuard } from "@/features/auth/components/queue-safe-sign-out-guard";
import { StepUpDialog } from "@/features/auth/components/step-up-dialog";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

export const metadata: Metadata = {
  applicationName: "Global Connects Coordinator",
  title: {
    default: "Global Connects Dashboard - Passport MRZ Platform",
    template: "%s | Global Connects Dashboard",
  },
  description:
    "Secure passport MRZ processing platform for travel agencies.",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    capable: true,
    statusBarStyle: "default",
    title: "Tour Ops",
  },
  icons: {
    icon: [
      { url: "/pwa-icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/pwa-icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [
      { url: "/apple-touch-icon.png", sizes: "180x180", type: "image/png" },
    ],
  },
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#0f172a",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
  colorScheme: "light",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  // A request-specific CSP nonce is generated in proxy.ts. Waiting for the
  // incoming request prevents a statically generated shell from containing
  // scripts that cannot receive that nonce.
  await connection();

  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning data-scroll-behavior="smooth">
      <body className="min-h-screen bg-slate-50 font-sans antialiased" suppressHydrationWarning>
        <PwaRegistrar />
        <QueryProvider>
        <QueueSafeSignOutGuard />
        <StepUpDialog />
          {children}
        </QueryProvider>
      </body>
    </html>
  );
}
