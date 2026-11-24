"use client";

import { createContext, type RefObject } from "react";

interface GroupBannerFrame {
  element: RefObject<HTMLDivElement | null>;
  previewing: boolean;
  setPreviewing: (previewing: boolean) => void;
}

/** Layout ownership stays with the group whose header contains the editor action. */
export const GroupBannerFrameContext = createContext<GroupBannerFrame | null>(null);
