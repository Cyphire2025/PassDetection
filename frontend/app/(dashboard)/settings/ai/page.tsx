import Link from "next/link";
import { ArrowLeft, Sparkles } from "lucide-react";
import { WorkspacePageHeader } from "@/components/shared/workspace-ui";
import { AssistantSettingsPanel } from "@/features/ai/components/assistant-settings-panel";

export default function AiSettingsPage() {
  return <div className="space-y-5"><Link href="/settings" className="inline-flex items-center gap-2 text-sm text-slate-500"><ArrowLeft size={15} />Settings</Link><WorkspacePageHeader title="AI assistant" description="Provider connection, voice and team access." icon={Sparkles} /><AssistantSettingsPanel /></div>;
}
