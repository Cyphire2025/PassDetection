"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, FileCheck2, MessageCircle, BadgeCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { returningApi } from "../api/returning.api";
import type { ReturningCapabilities, ReturningMethod } from "../types";

export function ReturningTravellerOffer({ token, onSelect, onFresh }: { token: string; onSelect: (method: ReturningMethod, capabilities: ReturningCapabilities) => void; onFresh?: () => void }) {
  const capabilities = useQuery({ queryKey: ["returning-capabilities", token], queryFn: ({ signal }) => returningApi.capabilities(token, signal), staleTime: 60_000, gcTime: 300_000, retry: false, refetchOnWindowFocus: false });
  if (!capabilities.data?.enabled) return <section className="rounded-3xl border border-slate-200 bg-white p-6 text-sm text-slate-600" aria-live="polite">
    {capabilities.isPending ? <p>Checking saved-document options…</p> : <><h2 className="text-lg font-semibold text-slate-900">Upload documents for this trip</h2><p className="mt-2 leading-6">Saved-document access is not available for this link. You can continue with a fresh submission.</p>{onFresh && <Button className="mt-5 w-full" onClick={onFresh}>Continue as a new traveller</Button>}</>}
  </section>;
  const options = [
    { method: "phone" as const, label: "WhatsApp OTP", detail: "Use your saved WhatsApp number.", icon: MessageCircle },
    { method: "passport" as const, label: "Passport number", detail: "Verify with a detail from your passport.", icon: FileCheck2 },
    ...(capabilities.data.code_label ? [{ method: "code" as const, label: "Agent / employee code", detail: "Use your individual code and passport number.", icon: BadgeCheck }] : []),
  ];
  return <section aria-label="Returning traveller" className="rounded-3xl border border-slate-200/80 bg-white p-5 shadow-[0_12px_48px_-24px_rgba(15,45,90,0.28)] sm:p-8">
    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-600">Welcome back</p>
    <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">Find your saved passport</h2>
    <p className="mt-2 text-sm leading-6 text-slate-500">Choose a way to verify your details securely.</p>
    <div className="mt-6 grid gap-3">{options.map(({ method, label, detail, icon: Icon }) => <button key={method} type="button" onClick={() => onSelect(method, capabilities.data!)} className="group flex min-h-20 items-center gap-3 rounded-2xl border border-slate-200 px-4 py-4 text-left transition-colors hover:border-blue-400 hover:bg-blue-50/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600"><Icon className="h-5 w-5" aria-hidden="true" /></span><span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-slate-900">{label}</span><span className="mt-1 block text-xs leading-5 text-slate-500">{detail}</span></span><ArrowRight className="h-4 w-4 shrink-0 text-slate-400 group-hover:text-blue-600" aria-hidden="true" /></button>)}</div>
    {onFresh && <div className="mt-6 border-t border-slate-100 pt-4"><Button variant="ghost" className="w-full" onClick={onFresh}>Continue as a new traveller</Button></div>}
  </section>;
}
