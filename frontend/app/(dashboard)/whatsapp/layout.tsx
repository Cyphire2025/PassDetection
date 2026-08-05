import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "WhatsApp",
};

export default function WhatsAppLayout({ children }: { children: ReactNode }) {
  return children;
}
