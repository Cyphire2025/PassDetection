import { Badge } from "@/components/ui";
import { formatQrStatus } from "./qr-status";

export function QrDeliverySummary({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: number;
  tone?: "neutral" | "success" | "warning" | "danger";
}) {
  const toneClass = tone === "success"
    ? "border-emerald-200 bg-emerald-50 text-emerald-900"
    : tone === "warning"
      ? "border-amber-200 bg-amber-50 text-amber-900"
      : tone === "danger"
        ? "border-red-200 bg-red-50 text-red-900"
        : "border-slate-200 bg-slate-50 text-slate-900";
  return (
    <div className={`rounded-xl border p-3 ${toneClass}`}>
      <div className="text-xs font-medium opacity-70">{label}</div>
      <div className="mt-1 text-xl font-semibold">{value}</div>
    </div>
  );
}

export function QrDeliveryPreviewStatus({ status }: { status: string }) {
  const variant = status === "ready"
    ? "success"
    : status === "retryable"
      ? "warning"
      : status === "blocked"
        ? "destructive"
        : "secondary";
  return <Badge variant={variant}>{formatQrStatus(status)}</Badge>;
}
