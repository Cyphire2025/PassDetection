import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { PwaRegistrar } from "@/components/pwa/pwa-registrar";
import { QueryProvider } from "@/providers/query-provider";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-inter",
});

export const metadata: Metadata = {
  title: {
    default: "PassDetection - Passport MRZ Platform",
    template: "%s | PassDetection",
  },
  description:
    "Secure passport MRZ processing platform for travel agencies.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  themeColor: "#ffffff",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning data-scroll-behavior="smooth">
      <body className="min-h-screen bg-slate-50 font-sans antialiased" suppressHydrationWarning>
        <PwaRegistrar />
        <QueryProvider>{children}</QueryProvider>
      </body>

    </html>
  );
}
