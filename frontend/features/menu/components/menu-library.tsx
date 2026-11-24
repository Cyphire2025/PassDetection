"use client";

import type { MenuCategory } from "../api/menu.api";
import { useMenuLibraryController } from "../hooks/use-menu-library-controller";
import { MenuLibraryView } from "./menu-library-view";

export function MenuLibrary({ categories }: { categories: MenuCategory[] }) {
  const model = useMenuLibraryController(categories);
  return <MenuLibraryView model={model} />;
}
