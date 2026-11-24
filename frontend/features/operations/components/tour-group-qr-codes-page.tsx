"use client";

import { useGroupQrCodesController } from "../hooks/use-group-qr-codes-controller";
import { GroupQrCodesView } from "./group-qr-codes-view";

export { QrDeliveryPreviewDialog } from "./qr-delivery-preview-dialog";

export function TourGroupQrCodesPage({ groupId }: { groupId: string }) {
  const model = useGroupQrCodesController(groupId);
  return <GroupQrCodesView model={model} />;
}
