/**
 * Separator Component — Light Theme
 */
import * as React from "react";
import { cn } from "@/lib/utils/cn";

interface SeparatorProps extends React.HTMLAttributes<HTMLHRElement> {
  orientation?: "horizontal" | "vertical";
}

function Separator({ className, orientation = "horizontal", ...props }: SeparatorProps) {
  return (
    <hr
      className={cn(
        "border-slate-200",
        orientation === "horizontal" ? "w-full border-t" : "h-full border-l",
        className
      )}
      {...props}
    />
  );
}
export { Separator };
