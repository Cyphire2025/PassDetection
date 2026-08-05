import type { Metadata } from "next";
import { MenuPage } from "@/features/menu/components/menu-page";

export const metadata: Metadata = {
  title: "Menu & Meal Planner",
};

export default function MenuRoutePage() {
  return <MenuPage />;
}
