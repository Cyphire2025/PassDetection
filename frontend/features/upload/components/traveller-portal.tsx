"use client";

import { type ReactNode, useState, useSyncExternalStore } from "react";
import dynamic from "next/dynamic";
import { ArrowLeft, ArrowRight, FilePlus2, FolderCheck } from "lucide-react";
import { useUploadLinkByToken } from "@/features/passports/hooks/use-upload-links";
import { ReturningTravellerOffer } from "@/features/travellers/components/returning-offer";
import type { ReturningCapabilities, ReturningMethod } from "@/features/travellers/types";
import { CenteredLoader, UploadHeader } from "./upload-flow-shell";
import { TravellerShell } from "./traveller-shell";
import { draftResumeText, parseDraftResume, subscribeDraftResume } from "@/features/travellers/services/draft-resume";

const UploadFlow = dynamic(() => import("./upload-flow").then((module) => module.UploadFlow), { loading: () => <CenteredLoader /> });
const ReturningFlow = dynamic(() => import("@/features/travellers/components/returning-flow").then((module) => module.ReturningFlow), { loading: () => <CenteredLoader /> });
const ReturningResume = dynamic(() => import("@/features/travellers/components/returning-resume").then((module) => module.ReturningResume), { loading: () => <CenteredLoader /> });
const FreshFlow = dynamic(() => import("./fresh-flow").then((module) => module.FreshFlow), { loading: () => <CenteredLoader /> });

/** Entry decisions never imply identity or authorize access to saved documents. */
export function TravellerPortal({ token }: { token: string }) {
  const { data: group, isLoading, error } = useUploadLinkByToken(token);
  const [path, setPath] = useState<"start" | "returning" | "new" | "resume">("start");
  const resumeText = useSyncExternalStore(subscribeDraftResume, () => draftResumeText(token), () => null);
  const resume = parseDraftResume(resumeText);
  const [selection, setSelection] = useState<{ method: ReturningMethod; capabilities: ReturningCapabilities } | null>(null);
  const fresh = () => { setSelection(null); setPath("new"); };
  if (isLoading) return <CenteredLoader />;
  if (error || !group) return <UploadFlow token={token} onStartOver={() => setPath("start")} />;
  if (path === "new") return <FreshFlow token={token} group={group} onBack={() => setPath("start")} />;
  if (path === "resume") return <ReturningResume token={token} groupName={group.name} group={group} onFresh={fresh} onVerify={() => setPath("returning")} />;
  if (selection) return <ReturningFlow token={token} group={group} initialMethod={selection.method} capabilities={selection.capabilities} onFresh={fresh} onReplace={fresh} onBack={() => setSelection(null)} />;
  return <TravellerShell>
    <UploadHeader groupName={group.name} departureDate={group.travel_date} returnDate={group.return_date} />
    {path === "returning" ? <>
      <button type="button" onClick={() => setPath("start")} className="mb-4 inline-flex min-h-11 items-center gap-2 text-sm font-medium text-slate-600 hover:text-blue-700"><ArrowLeft className="h-4 w-4" />Back</button>
      <ReturningTravellerOffer token={token} onSelect={(method, capabilities) => setSelection({ method, capabilities })} onFresh={fresh} />
    </> : <section className="rounded-3xl border border-white bg-white/95 p-5 shadow-[0_12px_48px_-24px_rgba(15,45,90,0.28)] sm:p-8" aria-labelledby="traveller-welcome">
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-blue-600">Your next journey</p>
      <h2 id="traveller-welcome" className="mt-2 text-2xl font-semibold tracking-tight text-slate-950">Let’s get you ready.</h2>
      <p className="mt-2 text-sm leading-6 text-slate-500">Choose how you’d like to share your travel details.</p>
      <div className="mt-6 space-y-3">
        <EntryChoice icon={<FolderCheck className="h-6 w-6" />} title="Travelled with us before" description="Find and review your saved passport." onClick={() => setPath("returning")} />
        <EntryChoice icon={<FilePlus2 className="h-6 w-6" />} title="New traveller" description="Upload your documents for this trip." onClick={fresh} />
      </div>
      {resume && <button type="button" onClick={() => setPath(resume.mode === "new" ? "new" : "resume")} className="mt-5 min-h-12 w-full rounded-xl border border-blue-200 bg-blue-50 px-4 py-3 text-left text-sm font-medium text-blue-700">Continue from where you left<span className="mt-1 block text-xs font-normal text-slate-500">Your temporary draft is available on this device for 24 hours.</span></button>}
    </section>}
  </TravellerShell>;
}

function EntryChoice({ icon, title, description, onClick }: { icon: ReactNode; title: string; description: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} className="group flex min-h-24 w-full items-center gap-4 rounded-2xl border border-slate-200 bg-white p-4 text-left transition-colors hover:border-blue-400 hover:bg-blue-50/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 sm:p-5">
    <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-blue-50 text-blue-600">{icon}</span>
    <span className="min-w-0 flex-1"><span className="block text-base font-semibold text-slate-900">{title}</span><span className="mt-1 block text-sm leading-5 text-slate-500">{description}</span></span>
    <ArrowRight className="h-5 w-5 shrink-0 text-slate-400 group-hover:text-blue-600" aria-hidden="true" />
  </button>;
}
