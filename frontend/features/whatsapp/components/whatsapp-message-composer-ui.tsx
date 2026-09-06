"use client";

import { Check, CircleAlert, ImageIcon, Loader2, MessageCircle } from "lucide-react";
import Image from "next/image";
import { useId, type ReactNode } from "react";
import { Skeleton } from "@/components/ui";
import type { WhatsAppMessageType, WhatsAppPreviewResponse } from "../api/whatsapp.api";
import { formatMessageType } from "../utils/message-types";
import { parseWhatsAppBoldSegments } from "../utils/whatsapp-formatting";

export function MessageComposerSection({ title, description, children }: {
  title: string;
  description: string;
  children: ReactNode;
}) {
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className="min-w-0 space-y-5 rounded-xl border border-slate-200 bg-white p-4 sm:p-5">
      <div className="border-b border-slate-100 pb-4">
        <h3 id={headingId} className="text-sm font-semibold text-slate-900">{title}</h3>
        <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>
      </div>
      {children}
    </section>
  );
}

export function MessageDeliveryPreview({
  preview, previewIsCurrent, previewFailed, messageType, headerImagePreview, headerImageId, children,
}: {
  preview: WhatsAppPreviewResponse | null;
  previewIsCurrent: boolean;
  previewFailed: boolean;
  messageType: WhatsAppMessageType;
  headerImagePreview: string | null;
  headerImageId: string | null;
  children?: ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="flex items-center gap-3 border-b border-slate-200 px-4 py-4">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-emerald-700">
          <MessageCircle className="h-5 w-5" aria-hidden="true" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold text-slate-900">Global Connect Travels</p>
          <p className="mt-0.5 break-words text-xs text-slate-500">To {preview?.recipient_name || "your recipient"}</p>
        </div>
        <span className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-1 text-[10px] font-medium ${previewIsCurrent ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
          {previewIsCurrent ? <Check className="h-3 w-3" aria-hidden="true" /> : previewFailed ? <CircleAlert className="h-3 w-3" aria-hidden="true" /> : <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" aria-hidden="true" />}
          {previewIsCurrent ? "Up to date" : previewFailed ? "Unavailable" : "Updating"}
        </span>
      </div>
      {children && <div className="border-b border-slate-200 px-4 py-3">{children}</div>}
      <div className="bg-[#f0f2ef] p-3 sm:p-5">
        <p className="mb-4 text-center text-[10px] font-medium uppercase tracking-wider text-slate-500">Message preview</p>
        <div className="ml-auto w-full max-w-[420px] overflow-hidden rounded-xl rounded-tr-sm border border-emerald-900/5 bg-[#dcf8c6] shadow-sm">
          {headerImagePreview ? (
            <div className="relative m-1.5 aspect-[16/10] overflow-hidden rounded-lg bg-white">
              <Image src={headerImagePreview} alt={`Selected ${formatMessageType(messageType)} image header`} fill unoptimized className="object-contain" />
            </div>
          ) : messageType !== "reminder" ? (
            <div className="m-1.5 flex min-h-32 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-slate-300 bg-white/75 px-5 py-5 text-center">
              <ImageIcon className="h-6 w-6 text-slate-400" aria-hidden="true" />
              <p className="text-xs font-medium text-slate-600">{headerImageId ? "Saved message image" : "Your header image will appear here"}</p>
              <p className="text-[11px] leading-5 text-slate-500">{headerImageId ? "The image from the previous message will be reused." : "Add a JPEG or PNG to complete the message."}</p>
            </div>
          ) : null}
          <div data-testid="whatsapp-message-preview" className="px-4 py-4 text-[13px] leading-[1.65] text-slate-800">
            {preview ? (
              <p className="whitespace-pre-wrap [overflow-wrap:anywhere]">
                {parseWhatsAppBoldSegments(preview.rendered_message).map((segment, index) => segment.bold ? (
                  <strong key={`${index}:${segment.text}`}>{segment.text}</strong>
                ) : <span key={`${index}:${segment.text}`}>{segment.text}</span>)}
              </p>
            ) : (
              <div className="space-y-3 py-2" aria-label="Loading message preview">
                <Skeleton className="h-4 w-2/3" /><Skeleton className="h-24 w-full" /><Skeleton className="h-16 w-4/5" />
              </div>
            )}
          </div>
        </div>
        <p className="mt-4 text-center text-[11px] leading-5 text-slate-500">Sent as a private message to each recipient.</p>
      </div>
      {preview && <details className="border-t border-slate-200 px-4 py-3 text-xs text-slate-500">
        <summary className="cursor-pointer font-medium focus-visible:outline-blue-500">Message template</summary>
        <p className="mt-2 break-all font-mono text-[11px]">{preview.template_name}</p>
      </details>}
    </div>
  );
}
