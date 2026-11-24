import { Ban, Clock3, Power, QrCode, RefreshCw, ShieldCheck } from "lucide-react";
import { Badge, Button } from "@/components/ui";
import type { GroupPassengerQrCode } from "../api/operations.api";
import { formatQrStatus, statusVariant } from "./qr-status";

export function PassengerQrCard({
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
    <article className="break-inside-avoid rounded-xl border border-slate-200 bg-white p-4 shadow-sm [contain-intrinsic-size:260px] [content-visibility:auto] print:rounded-none print:border-slate-300 print:shadow-none print:[content-visibility:visible]">
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
