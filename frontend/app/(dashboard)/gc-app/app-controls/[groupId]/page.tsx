import { AppControlGroupWorkspace } from "@/features/gc-app/components/app-control-group-workspace";

export default async function AppControlGroupRoute({
  params,
}: {
  params: Promise<{ groupId: string }>;
}) {
  const { groupId } = await params;
  return <AppControlGroupWorkspace groupId={groupId} />;
}
