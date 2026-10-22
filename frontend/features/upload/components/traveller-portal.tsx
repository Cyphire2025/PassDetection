"use client";

import { useState, useSyncExternalStore } from "react";
import dynamic from "next/dynamic";
import { ArrowLeft, FilePlus2, FolderCheck } from "lucide-react";
import { useUploadLinkByToken } from "@/features/passports/hooks/use-upload-links";
import { ReturningTravellerOffer } from "@/features/travellers/components/returning-offer";
import { useReturningCapabilities } from "@/features/travellers/hooks/use-returning-capabilities";
import type { ReturningCapabilities, ReturningMethod } from "@/features/travellers/types";
import { CenteredLoader, UploadHeader } from "./upload-flow-shell";
import { TravellerShell } from "./traveller-shell";
import { TravellerEntryChoice } from "./traveller-entry-choice";
import { UploadLinkErrorScreen } from "./upload-link-error-screen";
import { draftResumeText, parseDraftResume, subscribeDraftResume } from "@/features/travellers/services/draft-resume";
import styles from "./traveller-landing.module.css";

const ReturningFlow = dynamic(() => import("@/features/travellers/components/returning-flow").then((module) => module.ReturningFlow), { loading: () => <CenteredLoader /> });
const ReturningResume = dynamic(() => import("@/features/travellers/components/returning-resume").then((module) => module.ReturningResume), { loading: () => <CenteredLoader /> });
const FreshFlow = dynamic(() => import("./fresh-flow").then((module) => module.FreshFlow), { loading: () => <CenteredLoader /> });

/** Entry decisions never imply identity or authorize access to saved records. */
export function TravellerPortal({ token }: { token: string }) {
  const { data: group, isLoading, error, refetch, isFetching } = useUploadLinkByToken(token);
  const [path, setPath] = useState<"start" | "returning" | "new" | "resume">("start");
  const [resumeFresh, setResumeFresh] = useState(false);
  useReturningCapabilities(token, Boolean(group));
  const resumeText = useSyncExternalStore(subscribeDraftResume, () => draftResumeText(token), () => null);
  const resume = parseDraftResume(resumeText);
  const [selection, setSelection] = useState<{ method: ReturningMethod; capabilities: ReturningCapabilities } | null>(null);
  const fresh = () => { setResumeFresh(false); setSelection(null); setPath("new"); };
  if (isLoading) return <CenteredLoader />;
  if (error || !group) return <UploadLinkErrorScreen error={error} isRetrying={isFetching} onRetry={() => { void refetch(); }} />;
  if (path === "new") return <FreshFlow key={String(resumeFresh)} token={token} group={group} resumeExisting={resumeFresh} onBack={() => setPath("start")} />;
  if (path === "resume") return <ReturningResume token={token} groupName={group.name} group={group} onFresh={fresh} onVerify={() => setPath("returning")} />;
  if (selection) return <ReturningFlow token={token} group={group} initialMethod={selection.method} capabilities={selection.capabilities} onFresh={fresh} onReplace={fresh} onBack={() => setSelection(null)} />;
  return <TravellerShell landing={path === "start"}>
    <UploadHeader compact={path === "start"} groupName={group.name} departureDate={group.travel_date} returnDate={group.return_date} />
    {path === "returning" ? <>
      <button type="button" onClick={() => setPath("start")} className="mb-4 inline-flex min-h-11 items-center gap-2 text-sm font-medium text-slate-600 hover:text-blue-700"><ArrowLeft className="h-4 w-4" />Back</button>
      <ReturningTravellerOffer key={token} token={token} onSelect={(method, capabilities) => setSelection({ method, capabilities })} onFresh={fresh} />
    </> : <section className={`${styles.card} rounded-3xl border border-white bg-white/95 shadow-[0_12px_48px_-24px_rgba(15,45,90,0.28)]`} aria-labelledby="traveller-welcome">
      <h2 id="traveller-welcome" className="text-xl font-semibold tracking-tight text-slate-950">Let’s get you ready.</h2>
      <div className={styles.choices}>
        <TravellerEntryChoice icon={<FolderCheck className="h-6 w-6" />} title="Travelled with us before" description="Find and review your saved passport." onClick={() => setPath("returning")} />
        <TravellerEntryChoice icon={<FilePlus2 className="h-6 w-6" />} title="New traveller" description="Upload your documents for this trip." onClick={fresh} />
      </div>
      {resume && <button type="button" onClick={() => { setResumeFresh(true); setPath(resume.mode === "new" ? "new" : "resume"); }} className={`${styles.resume} w-full rounded-xl border border-blue-200 bg-blue-50 text-left text-sm font-medium text-blue-700`}>Continue from where you left<span className="mt-1 block text-xs font-normal text-slate-500">Your temporary draft is available on this device for 24 hours.</span></button>}
    </section>}
  </TravellerShell>;
}
