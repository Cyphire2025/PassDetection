/**
 * Passports List Page
 */

import type { Metadata } from "next";
import { PassportList } from "@/features/passports/components/passport-list";

export const metadata: Metadata = {
  title: "Passports | PassDetection",
};

export default function PassportsPage() {
  return <PassportList />;
}
