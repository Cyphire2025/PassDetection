"use client";

import { useQuery } from "@tanstack/react-query";
import { FileCheck2, MessageCircle, BadgeCheck } from "lucide-react";
import { returningApi } from "../api/returning.api";
import type { ReturningCapabilities, ReturningMethod } from "../types";

export function ReturningTravellerOffer({ token, onSelect }: { token: string; onSelect: (method: ReturningMethod, capabilities: ReturningCapabilities) => void }) {
  const capabilities = useQuery({ queryKey: ["returning-capabilities", token], queryFn: ({ signal }) => returningApi.capabilities(token, signal), staleTime: 0, gcTime: 0, retry: false });
  if (!capabilities.data?.enabled) return null;
  const options = [
    { method: "phone" as const, label: "WhatsApp OTP", icon: MessageCircle },
    { method: "passport" as const, label: "Passport number", icon: FileCheck2 },
    ...(capabilities.data.code_label ? [{ method: "code" as const, label: capabilities.data.code_label, icon: BadgeCheck }] : []),
  ];
  return <section aria-label="Returning traveller" className="mb-4 rounded-2xl border border-blue-100 bg-white p-4 shadow-sm sm:p-6">
    <h2 className="text-lg font-semibold text-slate-950">Travelled with us before?</h2>
    <p className="mt-1 text-sm leading-6 text-slate-600">Verify your saved passport, review the details, and answer this trip’s questions.</p>
    <div className="mt-4 grid gap-2">{options.map(({ method, label, icon: Icon }) => <button key={method} type="button" onClick={() => onSelect(method, capabilities.data!)} className="flex min-h-12 items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3 text-left text-sm font-semibold text-slate-800 hover:border-blue-400 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"><Icon className="h-5 w-5 shrink-0 text-blue-600" aria-hidden="true" /><span className="break-words">{label}</span></button>)}</div>
    <p className="mt-4 text-xs text-slate-500">New traveller / Upload current documents: continue below.</p>
  </section>;
}
