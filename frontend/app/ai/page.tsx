import type { Metadata, Viewport } from "next";
import { VoicePreview } from "@/features/ai/components/voice-preview";

export const metadata: Metadata = {
  title: "AI Voice Preview",
  description: "Give your voice a form. An experimental voice-reactive sculpture by Global Connects.",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#ebe9e5", colorScheme: "light" };

export default function AiPreviewPage() {
  return <VoicePreview />;
}
