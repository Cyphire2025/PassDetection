"use client";

import { Bold, Check, FileText, Loader2, MessageCircle } from "lucide-react";
import Image from "next/image";
import { useId, useRef, type ReactNode } from "react";
import { Skeleton } from "@/components/ui";
import {
  parseWhatsAppBoldSegments,
  toggleWhatsAppBold,
} from "../utils/whatsapp-formatting";

export function ComposerTextField({
  label,
  value,
  onChange,
  required = true,
  maxLength = 600,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  maxLength?: number;
}) {
  const id = useId(),
    editor = useRef<HTMLTextAreaElement>(null);
  return (
    <div>
      <label htmlFor={id} className="text-sm font-medium text-slate-700">
        {label}
        {required && (
          <span className="ml-1 text-slate-400" aria-hidden="true">
            *
          </span>
        )}
      </label>
      <div className="mt-2 overflow-hidden rounded-lg border border-slate-200 bg-white focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100">
        <div className="flex items-center justify-between border-b border-slate-100 px-2 py-1.5">
          <button
            type="button"
            aria-label={`Bold selected ${label.toLocaleLowerCase()} text`}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => {
              if (!editor.current) return;
              const result = toggleWhatsAppBold(
                value,
                editor.current.selectionStart,
                editor.current.selectionEnd,
              );
              onChange(result.value);
              requestAnimationFrame(() => {
                editor.current?.focus();
                editor.current?.setSelectionRange(
                  result.selectionStart,
                  result.selectionEnd,
                );
              });
            }}
            className="rounded px-2 py-1.5 text-slate-500 hover:bg-slate-100 focus-visible:outline-blue-500"
          >
            <Bold className="h-3.5 w-3.5" />
          </button>
          <span className="pr-2 text-[11px] tabular-nums text-slate-400">
            {value.length} / {maxLength}
          </span>
        </div>
        <textarea
          ref={editor}
          id={id}
          required={required}
          maxLength={maxLength}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="block min-h-40 w-full resize-y bg-white px-4 py-3 text-sm leading-6 text-slate-900 outline-none"
        />
      </div>
    </div>
  );
}

export function ComposerPreview({
  message,
  recipientName,
  current,
  image,
  savedImage = false,
  attachment,
  children,
}: {
  message: string | null;
  recipientName?: string | null;
  current: boolean;
  image?: string | null;
  savedImage?: boolean;
  attachment?: string | null;
  children?: ReactNode;
}) {
  return (
    <section
      className="overflow-hidden rounded-xl border border-slate-200 bg-white"
      aria-label="WhatsApp message preview"
    >
      <header className="flex items-center gap-3 border-b border-slate-100 px-4 py-3">
        <span className="rounded-full bg-emerald-50 p-2 text-emerald-700">
          <MessageCircle className="h-4 w-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-slate-900">
            Global Connect Travels
          </p>
          <p className="mt-1 truncate text-xs text-slate-500">
            {recipientName
              ? `To ${recipientName}`
              : "Individual WhatsApp message"}
          </p>
        </div>
        <span className="text-emerald-600">
          {current ? (
            <Check className="h-4 w-4" aria-label="Preview up to date" />
          ) : (
            <Loader2
              className="h-4 w-4 animate-spin motion-reduce:animate-none"
              aria-label="Updating preview"
            />
          )}
        </span>
      </header>
      {children && (
        <div className="border-b border-slate-100 px-4 py-3">{children}</div>
      )}
      <div className="bg-[#f0f2ef] p-4 sm:p-5">
        <div className="ml-auto max-w-md overflow-hidden rounded-xl rounded-tr-sm border border-emerald-900/5 bg-[#e2f7d5] shadow-sm">
          {image && (
            <Image
              src={image}
              alt="Message header"
              width={480}
              height={240}
              unoptimized
              className="max-h-48 w-full object-contain"
            />
          )}
          {savedImage && !image && (
            <p className="border-b border-emerald-900/5 px-4 py-3 text-xs text-emerald-900/60">
              Saved header image included
            </p>
          )}
          {attachment && (
            <div className="m-2 flex items-center gap-2 rounded-lg bg-white/65 px-3 py-3 text-xs text-slate-700">
              <FileText className="h-5 w-5 shrink-0 text-red-500" />
              <span className="min-w-0 break-words">{attachment}</span>
            </div>
          )}
          {message !== null ? (
            <p
              data-testid="broadcast-message-preview"
              className="whitespace-pre-wrap break-words px-4 py-4 text-sm leading-6 text-slate-800"
            >
              {parseWhatsAppBoldSegments(message).map((part, index) =>
                part.bold ? (
                  <strong key={index}>{part.text}</strong>
                ) : (
                  <span key={index}>{part.text}</span>
                ),
              )}
            </p>
          ) : (
            <div className="space-y-3 p-4">
              <Skeleton className="h-4 w-2/3" />
              <Skeleton className="h-24" />
            </div>
          )}
        </div>
        <p className="mt-4 text-center text-[11px] text-slate-500">
          Sent privately to each selected recipient
        </p>
      </div>
    </section>
  );
}
