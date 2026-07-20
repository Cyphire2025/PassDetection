/**
 * Client Upload Page
 * ==================
 * Public page - no auth required.
 * Clients receive a link /upload/[token] and land here.
 *
 * Current client-side quality checks cover Phases 5 through 8.
 */

import type { Metadata } from "next";
import { UploadFlow } from "@/features/upload/components/upload-flow";

interface UploadPageProps {
  params: Promise<{ token: string }>;
}

export async function generateMetadata(): Promise<Metadata> {
  return {
    title: "Upload Your Passport | Global Connects Dashboard",
    description: "Securely upload your passport document.",
    robots: { index: false, follow: false },
  };
}

export default async function ClientUploadPage({ params }: UploadPageProps) {
  const { token } = await params;
  return <UploadFlow token={token} />;
}
