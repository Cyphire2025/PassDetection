import type { Metadata, Viewport } from "next";
import { AssistantWorkspace } from "@/features/ai/components/assistant-workspace";

export const metadata: Metadata = {
  title: "Global Connects AI",
  description: "Your private Global Connects assistant for groups, documents and travel operations.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#ebe9e5", colorScheme: "light" };

export default function AiPreviewPage() {
  return <AssistantWorkspace />;
}
