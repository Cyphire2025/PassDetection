import Link from "next/link";
import { AlertTriangle, ArrowLeft, CheckCircle2, Printer, QrCode, Send, ShieldCheck, UsersRound } from "lucide-react";
import { Button, Skeleton } from "@/components/ui";
import { ROUTES } from "@/constants/routes";
import { WhatsAppActivityInline } from "@/features/whatsapp/components/whatsapp-activity-tracker";
import { OperationsPageHeader, OperationsSummaryItem, OperationsSummaryStrip } from "./operations-workspace-ui";
import type { useGroupQrCodesController } from "../hooks/use-group-qr-codes-controller";

export function GroupQrPageHeader({ model }: { model: ReturnType<typeof useGroupQrCodesController> }) {
  const {
    data,
    isLoading,
    activeCount,
    summaryUnavailable,
    passengerCount,
    notGeneratedCount,
    attentionCount,
    setDeliveryFeedback,
    setSelectedQrTokenIds,
    setMessageContent,
    sendQrBroadcast,
    setIsSendPreviewOpen,
    setActionError,
    setPrintRequested,
    setRenderLimit,
    printRequested,
  } = model;
  return (
    <>
      <div className="print:hidden">
        <OperationsPageHeader
          title={data?.group_name ? `${data.group_name} QR codes` : "Group QR codes"}
          description="Generate, print, and send passenger QR codes. Review expired or inactive codes."
          icon={QrCode}
          context={<span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-white/10 px-2.5 py-1 text-xs font-medium text-slate-200"><ShieldCheck className="h-3.5 w-3.5 text-sky-300" aria-hidden="true" />{summaryUnavailable ? "Status unavailable" : `${activeCount} active codes`}</span>}
          actions={
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                leftIcon={<Send className="h-4 w-4" aria-hidden="true" />}
                onClick={() => {
                  setDeliveryFeedback(null);
                  setSelectedQrTokenIds(null);
                  setMessageContent(null);
                  sendQrBroadcast.reset();
                  setIsSendPreviewOpen(true);
                }}
                disabled={!data || data.passengers.length === 0}
              >
                Send WhatsApp Broadcast
              </Button>
              <Button
                type="button"
                className="bg-white text-slate-950 hover:bg-sky-50 active:bg-sky-100"
                leftIcon={<Printer className="h-4 w-4" aria-hidden="true" />}
                onClick={() => {
                  setActionError(null);
                  setPrintRequested(true);
                  setRenderLimit(passengerCount);
                }}
                isLoading={printRequested}
                disabled={!data || passengerCount === 0}
              >
                {printRequested ? "Preparing print" : "Print all"}
              </Button>
              <Link
                href={ROUTES.dashboard.tourOperationsGroupAssignments}
                className="inline-flex h-9 items-center justify-center gap-2 rounded-lg border border-white/20 bg-white/10 px-3.5 text-sm font-semibold text-white transition hover:bg-white/15"
              >
                <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                Groups
              </Link>
            </div>
          }
        />
      </div>
      <div className="print:hidden">
        <WhatsAppActivityInline />
      </div>
      <div className="print:hidden">
        <OperationsSummaryStrip label="Passenger QR summary">
          {isLoading ? Array.from({ length: 4 }).map((_, index) => <Skeleton key={index} className="h-[72px] rounded-none" />) : (
            <>
              <OperationsSummaryItem label="Passengers" value={summaryUnavailable ? "—" : passengerCount.toLocaleString()} helper="submitted roster" icon={UsersRound} />
              <OperationsSummaryItem label="Active codes" value={summaryUnavailable ? "—" : activeCount.toLocaleString()} helper="ready to scan" icon={CheckCircle2} tone={activeCount === passengerCount && passengerCount > 0 ? "success" : "default"} />
              <OperationsSummaryItem label="Not generated" value={summaryUnavailable ? "—" : notGeneratedCount.toLocaleString()} helper="need a code" icon={QrCode} tone={summaryUnavailable ? "default" : notGeneratedCount > 0 ? "attention" : "success"} />
              <OperationsSummaryItem label="Lifecycle attention" value={summaryUnavailable ? "—" : attentionCount.toLocaleString()} helper="inactive or expired" icon={AlertTriangle} tone={summaryUnavailable ? "default" : attentionCount > 0 ? "attention" : "success"} />
            </>
          )}
        </OperationsSummaryStrip>
      </div>
    </>
  );
}
