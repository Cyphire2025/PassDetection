import type { Metadata } from "next";
import { QrScannerProof } from "@/features/tour-operations/components/qr-scanner-proof";

export const metadata: Metadata = {
  title: "Tour Scanner | PassDetection",
};

export default function TourScannerPage() {
  return <QrScannerProof />;
}
