import Image from "next/image";

import { cn } from "@/lib/utils/cn";

interface BrandLogoProps {
  className?: string;
  compact?: boolean;
  priority?: boolean;
}

export function BrandLogo({
  className,
  compact = false,
  priority = false,
}: BrandLogoProps) {
  return (
    <div
      className={cn(
        "relative shrink-0 overflow-hidden bg-white",
        compact ? "h-8 w-8 rounded-lg" : "h-11 w-[184px]",
        className,
      )}
    >
      <Image
        src="/globalconnect-logo.png"
        alt="Global Connects Dashboard"
        fill
        priority={priority}
        sizes={compact ? "32px" : "184px"}
        className={cn(
          "max-w-none object-cover object-center",
          compact ? "scale-[2.7]" : "scale-105",
        )}
      />
    </div>
  );
}
