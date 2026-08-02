import type { ReactNode } from "react";
import { GcAppShell } from "@/features/gc-app/components/gc-app-shell";

export default function GcAppLayout({ children }: { children: ReactNode }) {
  return <GcAppShell>{children}</GcAppShell>;
}
