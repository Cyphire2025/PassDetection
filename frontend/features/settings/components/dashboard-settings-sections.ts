import { Database, MessageSquare, Monitor, ShieldCheck, SlidersHorizontal, Sparkles } from "lucide-react";

const SECTIONS = [
  { id: "ai", title: "AI assistant", description: "Models, connection and access", icon: Sparkles },
  {
    id: "appearance",
    title: "Appearance & navigation",
    description: "Display and sidebar preferences",
    icon: Monitor,
  },
  {
    id: "policies",
    title: "Platform policies",
    description: "Intake, review and retention",
    icon: SlidersHorizontal,
  },
  {
    id: "whatsapp",
    title: "WhatsApp templates",
    description: "Approved message template names",
    icon: MessageSquare,
  },
  {
    id: "security",
    title: "Account & security",
    description: "Your identity and active sessions",
    icon: ShieldCheck,
  },
  {
    id: "data",
    title: "Data administration",
    description: "Manage retained operational data",
    icon: Database,
  },
] as const;
export type Section = (typeof SECTIONS)[number]["id"];

export function visibleSections(role: string | undefined) {
  return SECTIONS.filter(({ id }) => {
    if (id === "ai") return role === "super_admin";
    if (id === "whatsapp") return role === "super_admin" || role === "agency_admin";
    return true;
  });
}
