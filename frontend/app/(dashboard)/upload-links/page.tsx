/**
 * Upload Links Page
 */

import type { Metadata } from "next";
import { UploadLinkList } from "@/features/passports/components/upload-link-list";

export const metadata: Metadata = {
  title: "Upload Links | PassDetection",
};

export default function UploadLinksPage() {
  return <UploadLinkList />;
}
