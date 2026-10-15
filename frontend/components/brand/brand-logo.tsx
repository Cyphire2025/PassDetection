import { preload } from "react-dom";

import { cn } from "@/lib/utils/cn";

interface BrandLogoProps {
  className?: string;
  compact?: boolean;
  priority?: boolean;
}

const LOGO_SRC = "/globalconnect-logo-transparent.png";

export function BrandLogo({
  className,
  compact = false,
  priority = false,
}: BrandLogoProps) {
  if (priority) preload(LOGO_SRC, { as: "image" });
  return (
    <svg
      role="img"
      aria-label="Global Connect Travels"
      viewBox="103 145 417 145"
      preserveAspectRatio="xMidYMid meet"
      className={cn(
        "block shrink-0",
        compact ? "h-10 w-12" : "h-16 w-[184px]",
        className,
      )}
    >
      {/* Frame the artwork's alpha bounds; keep the supplied PNG unchanged. */}
      <image href={LOGO_SRC} width="612" height="408" />
    </svg>
  );
}
