import type { Metadata } from "next";
import { CoordinatorHotelCheckin } from "@/features/tour-operations/components/coordinator-hotel-checkin";
export const metadata: Metadata = { title: "Hotel Check-in | PassDetection" };
export default async function HotelCheckinPage({ params }: { params: Promise<{ groupId: string }> }) { const { groupId } = await params; return <CoordinatorHotelCheckin groupId={groupId} />; }
