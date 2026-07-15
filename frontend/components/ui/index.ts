/**
 * UI Components Barrel Export
 * ===========================
 * Import all design system primitives from a single location:
 *   import { Button, Card, Badge } from "@/components/ui"
 */

export { Button, buttonVariants } from "./button";
export type { ButtonProps } from "./button";

export { Input } from "./input";
export type { InputProps } from "./input";
export { PasswordInput } from "./password-input";

export {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
} from "./card";

export { Badge, badgeVariants } from "./badge";
export type { BadgeProps } from "./badge";

export { Skeleton } from "./skeleton";
export { Separator } from "./separator";
export { ConfirmDialog, TextInputDialog } from "./modal";
