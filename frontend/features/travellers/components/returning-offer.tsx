"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowRight, FileCheck2, MessageCircle, BadgeCheck, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useReturningCapabilities } from "../hooks/use-returning-capabilities";
import type { ReturningCapabilities, ReturningMethod } from "../types";

export function ReturningTravellerOffer({ token, onSelect, onFresh }: { token: string; onSelect: (method: ReturningMethod, capabilities: ReturningCapabilities) => void; onFresh?: () => void }) {
  const capabilities = useReturningCapabilities(token);
  const [pending, setPending] = useState<ReturningMethod | null>(null), [notice, setNotice] = useState<string>();
  const selection = useRef<symbol | null>(null);
  useEffect(() => () => { selection.current = null; }, [token]);
  const select = async (method: ReturningMethod) => {
    if (selection.current) return;
    const request = Symbol(); selection.current = request; setPending(method); setNotice(undefined);
    const result = capabilities.data ?? (await capabilities.refetch({ cancelRefetch: false })).data;
    if (selection.current !== request) return;
    selection.current = null; setPending(null);
    if (!result?.enabled) return;
    if (method === "code" && !result.code_label) { setNotice("Code verification is not enabled for this trip. Choose WhatsApp OTP or passport number."); return; }
    onSelect(method, result);
  };
  if (capabilities.data?.enabled === false) return <section className="rounded-3xl border border-slate-200 bg-white p-6 text-sm text-slate-600" aria-live="polite">
    <h2 className="text-lg font-semibold text-slate-900">Upload documents for this trip</h2><p className="mt-2 leading-6">Saved-document access is not available for this link. You can continue with a fresh submission.</p>{onFresh && <Button className="mt-5 w-full" onClick={onFresh}>Continue as a new traveller</Button>}
  </section>;
  const options = [
    { method: "phone" as const, label: "WhatsApp OTP", detail: "Use your saved WhatsApp number.", icon: MessageCircle },
    { method: "passport" as const, label: "Passport number", detail: "Verify with a detail from your passport.", icon: FileCheck2 },
    ...(!capabilities.data || capabilities.data.code_label ? [{ method: "code" as const, label: "Agent / employee code", detail: "Use your individual code and passport number.", icon: BadgeCheck }] : []),
  ];
  return <section aria-label="Returning traveller" className="rounded-3xl border border-slate-200/80 bg-white p-5 shadow-[0_12px_48px_-24px_rgba(15,45,90,0.28)] sm:p-8">
    <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-600">Welcome back</p>
    <h2 className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">Find your saved passport</h2>
    <p className="mt-2 text-sm leading-6 text-slate-500">Choose a way to verify your details securely.</p>
    {capabilities.isError && !capabilities.data && <div role="alert" className="mt-4 rounded-xl bg-red-50 p-4 text-sm text-red-700">We couldn’t connect. Select your preferred option to try again.</div>}
    {notice && <p role="status" className="mt-4 text-sm text-slate-600">{notice}</p>}
    <div className="mt-6 grid gap-3">{options.map(({ method, label, detail, icon: Icon }) => <button key={method} type="button" disabled={pending !== null} aria-busy={pending === method} onClick={() => void select(method)} className="group flex min-h-20 items-center gap-3 rounded-2xl border border-slate-200 px-4 py-4 text-left transition-colors hover:border-blue-400 hover:bg-blue-50/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 disabled:cursor-wait"><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-blue-600"><Icon className="h-5 w-5" aria-hidden="true" /></span><span className="min-w-0 flex-1"><span className="block text-sm font-semibold text-slate-900">{label}</span><span className="mt-1 block text-xs leading-5 text-slate-500">{pending === method ? "Opening verification…" : detail}</span></span>{pending === method ? <Loader2 className="h-4 w-4 shrink-0 animate-spin text-blue-600" aria-hidden="true" /> : <ArrowRight className="h-4 w-4 shrink-0 text-slate-400 group-hover:text-blue-600" aria-hidden="true" />}</button>)}</div>
    {onFresh && <div className="mt-6 border-t border-slate-100 pt-4"><Button variant="ghost" className="w-full" onClick={onFresh}>Continue as a new traveller</Button></div>}
  </section>;
}
