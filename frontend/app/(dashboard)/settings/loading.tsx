import { WorkspaceRouteLoading } from "@/components/shared/workspace-ui";

export default function SettingsLoading() {
  return (
    <WorkspaceRouteLoading
      eyebrow="Platform governance"
      title="Loading Settings"
      rows={3}
    />
  );
}
