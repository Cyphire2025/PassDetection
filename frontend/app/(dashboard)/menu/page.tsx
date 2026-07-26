import type { Metadata } from "next";
import { MenuPage } from "@/features/menu/components/menu-page";

export const metadata: Metadata = {
  title: "Menu & Meal Planner | Global Connects Dashboard",
};

export default function MenuRoutePage() {
  return <MenuPage />;
}
