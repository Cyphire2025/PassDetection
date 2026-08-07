import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { ROUTES } from "@/constants/routes";

export const metadata: Metadata = {
  title: "Group Documents",
};

interface DocumentGroupPageProps {
  params: Promise<{ groupId: string }>;
}

export default async function DocumentGroupPage({ params }: DocumentGroupPageProps) {
  const { groupId } = await params;
  redirect(ROUTES.dashboard.documentGroup(groupId) as never);
}
