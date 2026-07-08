import type { Metadata } from "next";
import { TourGroupQrCodesPage } from "@/features/operations/components/tour-group-qr-codes-page";

export const metadata: Metadata = {
  title: "Tour Group QR Codes | PassDetection",
};

interface TourGroupQrCodesRouteProps {
  params: Promise<{ groupId: string }>;
}

export default async function TourGroupQrCodesRoute({ params }: TourGroupQrCodesRouteProps) {
  const { groupId } = await params;
  return <TourGroupQrCodesPage groupId={groupId} />;
}
