import type { Metadata } from "next";
import { PassportGroupDetail } from "@/features/passports/components/passport-group-detail";

export const metadata: Metadata = {
  title: "Passport Group | Global Connects Dashboard",
};

interface PassportGroupPageProps {
  params: Promise<{ groupId: string }>;
}

export default async function PassportGroupPage({ params }: PassportGroupPageProps) {
  const { groupId } = await params;
  return <PassportGroupDetail key={groupId} groupId={groupId} />;
}
