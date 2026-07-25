"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import QRCode from "qrcode";
import { ArrowLeft, Ban, Clock3, Power, Printer, QrCode, RefreshCw, ShieldCheck } from "lucide-react";
import { Badge, Button, Card, CardContent, Skeleton } from "@/components/ui";
import { PageHeader } from "@/components/shared/page-header";
import { ROUTES } from "@/constants/routes";
import { useGroupQrCodes, usePassengerQrLifecycle } from "../hooks/use-operations";
import type { GroupPassengerQrCode } from "../api/operations.api";

type QrImageMap = Record<string, string>;

export function TourGroupQrCodesPage({ groupId }: { groupId: string }) {
  const { data, isLoading, error } = useGroupQrCodes(groupId);
  const qrLifecycle = usePassengerQrLifecycle(groupId);
  const [qrImages, setQrImages] = useState<QrImageMap>({});
  const [generatedPayloads, setGeneratedPayloads] = useState<Record<string, string>>({});
  const [pendingPassengerId, setPendingPassengerId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const visiblePayloads = useMemo(
    () => ({
      ...Object.fromEntries(
        (data?.passengers ?? [])
          .filter((passenger) => passenger.qr_payload)
          .map((passenger) => [passenger.passenger_id, passenger.qr_payload as string]),
      ),
      ...generatedPayloads,
    }),
    [data?.passengers, generatedPayloads],
  );

  useEffect(() => {
    let cancelled = false;

    async function generateQrImages() {
      const revealed = Object.entries(visiblePayloads);
      if (revealed.length === 0) {
        setQrImages({});
        return;
      }

      const entries = await Promise.all(
        revealed.map(async ([passengerId, payload]) => [
          passengerId,
          await QRCode.toDataURL(payload, {
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
  }, [visiblePayloads]);

  const revealToken = async (passengerId: string, regenerate: boolean) => {
    if (regenerate && !window.confirm("Regenerate this QR? The previous printed code will stop working immediately.")) return;
    setPendingPassengerId(passengerId);
    setActionError(null);
    try {
      const result = await (regenerate
        ? qrLifecycle.regenerate.mutateAsync(passengerId)
        : qrLifecycle.generate.mutateAsync(passengerId));
      if (result.qr_payload) {
        setGeneratedPayloads((current) => ({ ...current, [passengerId]: result.qr_payload as string }));
      }
    } catch {
      setActionError("The QR action could not be completed. Refresh and try again.");
    } finally {
      setPendingPassengerId(null);
    }
  };

  const updateLifecycle = async (passengerId: string, action: "revoke" | "expire" | "activate" | "deactivate") => {
    const warnings = {
      revoke: "Revoke this QR permanently? The passenger will need a newly generated code.",
      expire: "Expire this QR now? It will stop scanning immediately.",
      activate: "Activate this QR again? Any existing printed copy will become scannable.",
      deactivate: "Deactivate this QR? It can be activated again later.",
    };
    if (!window.confirm(warnings[action])) return;
    setPendingPassengerId(passengerId);
    setActionError(null);
    try {
      if (action === "revoke") await qrLifecycle.revoke.mutateAsync(passengerId);
      if (action === "expire") await qrLifecycle.expire.mutateAsync(passengerId);
      if (action === "activate") await qrLifecycle.setActive.mutateAsync({ passengerId, isActive: true });
      if (action === "deactivate") await qrLifecycle.setActive.mutateAsync({ passengerId, isActive: false });
      if (action === "revoke" || action === "expire") {
        setGeneratedPayloads((current) => {
          const next = { ...current };
          delete next[passengerId];
          return next;
        });
      }
    } catch {
      setActionError("The QR status could not be updated. Refresh and try again.");
    } finally {
      setPendingPassengerId(null);
    }
  };

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
                disabled={Object.keys(qrImages).length === 0}
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

      {actionError && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 print:hidden">
          {actionError}
        </div>
      )}

      <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 text-sm text-blue-800 print:hidden">
        Generated QR cards stay visible here for office users. Use Regenerate only when the printed code must be replaced.
      </div>

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
                  payload={visiblePayloads[passenger.passenger_id]}
                  isPending={pendingPassengerId === passenger.passenger_id}
                  onGenerate={() => void revealToken(passenger.passenger_id, false)}
                  onRegenerate={() => void revealToken(passenger.passenger_id, true)}
                  onLifecycle={(action) => void updateLifecycle(passenger.passenger_id, action)}
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
  payload,
  isPending,
  onGenerate,
  onRegenerate,
  onLifecycle,
}: {
  passenger: GroupPassengerQrCode;
  imageUrl?: string;
  payload?: string;
  isPending: boolean;
  onGenerate: () => void;
  onRegenerate: () => void;
  onLifecycle: (action: "revoke" | "expire" | "activate" | "deactivate") => void;
}) {
  const hasToken = passenger.qr_status !== "not_generated";
  return (
    <article className="break-inside-avoid rounded-xl border border-slate-200 bg-white p-4 shadow-sm print:rounded-none print:border-slate-300 print:shadow-none">
      <div className="flex gap-4">
        <div className="flex h-36 w-36 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white p-2">
          {imageUrl ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={imageUrl} alt={`${passenger.client_name} attendance QR`} className="h-full w-full" />
          ) : (
            <div className="px-2 text-center print:hidden">
              <ShieldCheck className="mx-auto h-9 w-9 text-slate-300" aria-hidden="true" />
              <p className="mt-2 text-[11px] leading-4 text-slate-400">
                {hasToken ? "Regenerate to restore display" : "Generate to reveal"}
              </p>
            </div>
          )}
        </div>

        <div className="min-w-0 flex-1">
          <h3 className="break-words text-base font-semibold text-slate-900">{passenger.client_name}</h3>
          <p className="mt-1 break-all text-xs text-slate-500">
            {[passenger.client_email, passenger.client_phone].filter(Boolean).join(" | ") || "No contact"}
          </p>
          <div className="mt-3">
            <Badge variant="secondary">Shared group access</Badge>
          </div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Badge variant={statusVariant(passenger.qr_status)} dot>{formatQrStatus(passenger.qr_status)}</Badge>
            {passenger.qr_token_version && <Badge variant="outline">v{passenger.qr_token_version}</Badge>}
          </div>
          {passenger.qr_expires_at && (
            <p className="mt-2 text-[11px] text-slate-500">
              Expires {new Date(passenger.qr_expires_at).toLocaleDateString()}
            </p>
          )}
          {payload && (
            <p className="mt-3 break-all font-mono text-[10px] leading-4 text-slate-400 print:text-slate-500">
              {payload}
            </p>
          )}
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2 print:hidden">
        {!hasToken ? (
          <Button type="button" className="col-span-2 gap-2" disabled={isPending} onClick={onGenerate}>
            <QrCode className="h-4 w-4" /> {isPending ? "Generating" : "Generate QR Code"}
          </Button>
        ) : (
          <>
            <Button type="button" className="col-span-2 gap-2" disabled={isPending} onClick={onRegenerate}>
              <RefreshCw className="h-4 w-4" /> {isPending ? "Updating" : "Regenerate QR Code"}
            </Button>
            {passenger.qr_status === "active" && (
              <Button type="button" variant="secondary" disabled={isPending} onClick={() => onLifecycle("deactivate")}>
                <Power className="mr-1.5 h-4 w-4" /> Deactivate
              </Button>
            )}
            {passenger.qr_status === "inactive" && (
              <Button type="button" variant="secondary" disabled={isPending} onClick={() => onLifecycle("activate")}>
                <Power className="mr-1.5 h-4 w-4" /> Activate
              </Button>
            )}
            {(passenger.qr_status === "active" || passenger.qr_status === "inactive") && (
              <Button type="button" variant="outline" disabled={isPending} onClick={() => onLifecycle("expire")}>
                <Clock3 className="mr-1.5 h-4 w-4" /> Expire now
              </Button>
            )}
            {passenger.qr_status !== "revoked" && (
              <Button type="button" variant="danger" className="col-span-2" disabled={isPending} onClick={() => onLifecycle("revoke")}>
                <Ban className="mr-1.5 h-4 w-4" /> Revoke permanently
              </Button>
            )}
          </>
        )}
      </div>
    </article>
  );
}

function formatQrStatus(status: string) {
  return status.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());
}

function statusVariant(status: string): "default" | "success" | "warning" | "destructive" | "outline" {
  if (status === "active") return "success";
  if (status === "inactive" || status === "expired") return "warning";
  if (status === "revoked") return "destructive";
  return "outline";
}
