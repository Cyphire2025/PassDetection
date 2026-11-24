import Link from "next/link";
import { QrCode } from "lucide-react";
import { Badge, Button, Card, CardContent } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { formatDateTime } from "@/lib/utils/format";
import type { PassportSubmission } from "@/types/passport.types";
import { formatQrStatus, qrStatusVariant } from "./passport-review-model";

export function PassportAttendanceQrCard({ data }: { data: PassportSubmission }) {
  return (
          <Card className="rounded-xl">
            <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-3">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
                  <QrCode className="h-5 w-5" aria-hidden="true" />
                </span>
                <div>
                  <h3 className="font-semibold text-slate-900">Attendance QR status</h3>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <Badge variant={qrStatusVariant(data.qr_status?.status)} dot>
                      {formatQrStatus(data.qr_status?.status ?? "not_generated")}
                    </Badge>
                    {data.qr_status?.token_version && (
                      <span className="text-xs text-slate-500">Version {data.qr_status.token_version}</span>
                    )}
                  </div>
                  {data.qr_status?.expires_at && (
                    <p className="mt-1.5 text-xs text-slate-500">
                      Expires {formatDateTime(data.qr_status.expires_at)}
                    </p>
                  )}
                </div>
              </div>
              <Link href={ROUTES.dashboard.tourOperationsGroupQrCodes(data.group_id)}>
                <Button variant="secondary" className="w-full sm:w-auto">Manage QR</Button>
              </Link>
            </CardContent>
          </Card>
  );
}
