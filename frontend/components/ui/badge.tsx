/**
 * Badge Component — Light Theme
 */

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils/cn";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium border",
  {
    variants: {
      variant: {
        default:     "bg-slate-100 text-slate-700 border-slate-200",
        secondary:   "bg-blue-50 text-blue-700 border-blue-200",
        success:     "bg-green-50 text-green-700 border-green-200",
        warning:     "bg-amber-50 text-amber-700 border-amber-200",
        destructive: "bg-red-50 text-red-700 border-red-200",
        outline:     "bg-transparent text-slate-600 border-slate-300",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {
  dot?: boolean;
}

function Badge({ className, variant, dot = false, children, ...props }: BadgeProps) {
  return (
    <span className={cn(badgeVariants({ variant }), className)} {...props}>
      {dot && (
        <span
          className={cn("h-1.5 w-1.5 rounded-full", {
            "bg-slate-500":  variant === "default",
            "bg-blue-500":   variant === "secondary",
            "bg-green-500":  variant === "success",
            "bg-amber-500":  variant === "warning",
            "bg-red-500":    variant === "destructive",
          })}
          aria-hidden="true"
        />
      )}
      {children}
    </span>
  );
}

export { Badge, badgeVariants };
