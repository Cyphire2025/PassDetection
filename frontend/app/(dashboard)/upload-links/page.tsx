/**
 * Upload Links Page
 */

import type { Metadata } from "next";
import { UploadLinkList } from "@/features/passports/components/upload-link-list";

export const metadata: Metadata = {
  title: "Group Links",
};

export default function UploadLinksPage() {
  return <UploadLinkList />;
}
