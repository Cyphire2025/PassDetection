import type { Metadata } from "next";
import { QrScannerProof } from "@/features/tour-operations/components/qr-scanner-proof";

export const metadata: Metadata = {
  title: "Scanner Proof | Global Connects Dashboard",
};

export default function ScannerProofPage() {
  return <QrScannerProof />;
}
