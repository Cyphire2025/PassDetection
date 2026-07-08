"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import QRCode from "qrcode";
import { ArrowLeft, Printer, QrCode } from "lucide-react";
import { Badge, Button, Card, CardContent, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/shared/page-header";
import { ROUTES } from "@/constants/routes";
import { useGroupQrCodes } from "../hooks/use-operations";
import type { GroupPassengerQrCode } from "../api/operations.api";

type QrImageMap = Record<string, string>;

export function TourGroupQrCodesPage({ groupId }: { groupId: string }) {
  const { data, isLoading, error } = useGroupQrCodes(groupId);
  const [qrImages, setQrImages] = useState<QrImageMap>({});

  const passengers = useMemo(() => data?.passengers ?? [], [data?.passengers]);

  useEffect(() => {
    let cancelled = false;

    async function generateQrImages() {
      if (passengers.length === 0) {
        setQrImages({});
        return;
      }

      const entries = await Promise.all(
        passengers.map(async (passenger) => [
          passenger.passenger_id,
          await QRCode.toDataURL(passenger.qr_payload, {
            errorCorrectionLevel: "M",
            margin: 2,
            scale: 7,
            color: {
              dark: "#020617",
              light: "#ffffff",
            },
          }),
        ] as const),
      );

      if (!cancelled) {
        setQrImages(Object.fromEntries(entries));
      }
    }

    generateQrImages();
    return () => {
      cancelled = true;
    };
  }, [passengers]);

  return (
    <div className="space-y-6 print:space-y-4">
      <div className="print:hidden">
        <PageHeader
          title={data?.group_name ? `${data.group_name} QR Codes` : "Group QR Codes"}
          description="Print or share these passenger QR cards for coordinator attendance scanning."
          actions={
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                variant="secondary"
                leftIcon={<Printer className="h-4 w-4" aria-hidden="true" />}
                onClick={() => window.print()}
                disabled={!data || data.passengers.length === 0}
              >
                Print
              </Button>
              <Link
                href={ROUTES.dashboard.tourOperationsGroupAssignments}
                className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition hover:bg-slate-50"
              >
                <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                Groups
              </Link>
            </div>
          }
        />
      </div>

      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 print:hidden">
          QR codes could not be loaded.
        </div>
      )}

      <Card className="print:border-0 print:shadow-none">
        <CardContent className="p-0 print:p-0">
          <div className="flex items-center justify-between gap-3 border-b border-slate-200 p-5 print:p-0 print:pb-4">
            <div className="flex items-center gap-3">
              <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600 print:hidden">
                <QrCode className="h-5 w-5" aria-hidden="true" />
              </span>
              <div>
                <h2 className="text-base font-semibold text-slate-900 print:text-xl">
                  {data?.group_name ?? "Passenger QR Sheet"}
                </h2>
                <p className="text-sm text-slate-500 print:text-xs">
                  {data ? `${data.passengers.length} submitted passenger${data.passengers.length === 1 ? "" : "s"}` : "Loading passengers"}
                </p>
              </div>
            </div>
            {data?.generated_at && (
              <p className="hidden text-xs text-slate-500 print:block">
                Generated {new Date(data.generated_at).toLocaleString()}
              </p>
            )}
          </div>

          {isLoading ? (
            <div className="grid gap-4 p-5 md:grid-cols-2 xl:grid-cols-3">
              {Array.from({ length: 6 }).map((_, index) => (
                <Skeleton key={index} className="h-64 rounded-xl" />
              ))}
            </div>
          ) : !data || data.passengers.length === 0 ? (
            <div className="p-5">
              <p className="rounded-lg border border-dashed border-slate-300 px-3 py-8 text-center text-sm text-slate-500">
                No submitted passengers found for this group.
              </p>
            </div>
          ) : (
            <div className="grid gap-4 p-5 md:grid-cols-2 xl:grid-cols-3 print:grid-cols-2 print:p-0">
              {data.passengers.map((passenger) => (
                <PassengerQrCard
                  key={passenger.passenger_id}
                  passenger={passenger}
                  imageUrl={qrImages[passenger.passenger_id]}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function PassengerQrCard({
  passenger,
  imageUrl,
}: {
  passenger: GroupPassengerQrCode;
  imageUrl?: string;
}) {
  return (
    <article className="break-inside-avoid rounded-xl border border-slate-200 bg-white p-4 shadow-sm print:rounded-none print:border-slate-300 print:shadow-none">
      <div className="flex gap-4">
        <div className="flex h-36 w-36 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white p-2">
          {imageUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={imageUrl} alt={`${passenger.client_name} attendance QR`} className="h-full w-full" />
          ) : (
            <QrCode className="h-10 w-10 text-slate-300" aria-hidden="true" />
          )}
        </div>

        <div className="min-w-0 flex-1">
          <h3 className="break-words text-base font-semibold text-slate-900">{passenger.client_name}</h3>
          <p className="mt-1 break-all text-xs text-slate-500">
            {[passenger.client_email, passenger.client_phone].filter(Boolean).join(" | ") || "No contact"}
          </p>
          <div className="mt-3">
            <Badge variant={passenger.coordinator_id ? "secondary" : "warning"}>
              {passenger.coordinator_name ?? "No coordinator"}
            </Badge>
          </div>
          <p className="mt-3 break-all font-mono text-[10px] leading-4 text-slate-400 print:text-slate-500">
            {passenger.qr_payload}
          </p>
        </div>
      </div>
    </article>
  );
}
