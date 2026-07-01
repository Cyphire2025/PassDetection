/**
 * cn — Class Name Utility
 * =======================
 * Merges Tailwind classes with clsx and resolves conflicts with tailwind-merge.
 *
 * Usage:
 *   cn("px-4 py-2", isActive && "bg-blue-600", className)
 */

import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
