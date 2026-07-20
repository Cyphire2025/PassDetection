import type { Metadata } from "next";
import { QrScannerProof } from "@/features/tour-operations/components/qr-scanner-proof";

export const metadata: Metadata = {
  title: "Tour Scanner | Global Connects Dashboard",
};

export default function TourScannerPage() {
  return <QrScannerProof />;
}
