"use client";
import { useCallback, useState } from "react";
import { ArrowLeft, CheckCircle2, UserRound, UsersRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { clearDraftResume, readDraftResume, saveFreshResume, type FreshResume } from "@/features/travellers/services/draft-resume";
import { TravellerShell } from "./traveller-shell";
import { UploadHeader } from "./upload-flow-shell";
import { FreshMember } from "./fresh-member";
import { MAX_FAMILY_MEMBERS, MIN_FAMILY_MEMBERS } from "./upload-flow.constants";

export function FreshFlow({ token, group, onBack, resumeExisting = false }: { token: string; group: UploadLinkResponse; onBack: () => void; resumeExisting?: boolean }) {
  const [resume, setResume] = useState<FreshResume | undefined>(() => resumeExisting ? readDraftResume(token)?.fresh : undefined);
  const [mode, setMode] = useState<"single" | "family">("single"), [count, setCount] = useState(2), [finished, setFinished] = useState(false);
  const start = () => {
    const value: FreshResume = { mode, familyGroupId: crypto.randomUUID(), active: 0, members: Array.from({ length: mode === "single" ? 1 : count }, () => ({ sessionId: crypto.randomUUID(), submissionKey: crypto.randomUUID(), completed: false })) };
    clearDraftResume(token); saveFreshResume(token, value); setResume(value);
  };
  const onStarted = useCallback((expires: string) => {
    if (resume) saveFreshResume(token, resume, expires);
  }, [token, resume]);
  const complete = () => {
    if (!resume) return;
    const members = resume.members.map((member, index) => index === resume.active ? { ...member, completed: true } : member);
    const next = members.findIndex((member) => !member.completed);
    if (next < 0) { clearDraftResume(token); setFinished(true); return; }
    const value = { ...resume, members, active: next }; saveFreshResume(token, value); setResume(value);
  };
  return <TravellerShell wide>
    <UploadHeader groupName={group.name} departureDate={group.travel_date} returnDate={group.return_date} />
    {(!resume || finished) && <button type="button" onClick={onBack} className="mb-4 inline-flex min-h-11 items-center gap-2 text-sm font-medium text-slate-600 hover:text-blue-700"><ArrowLeft className="h-4 w-4" />Back</button>}
    {finished ? <section className="mx-auto max-w-2xl rounded-2xl border border-emerald-100 bg-white p-8 text-center"><CheckCircle2 className="mx-auto h-12 w-12 text-emerald-600" /><h1 className="mt-4 text-2xl font-semibold text-slate-950">You’re all set</h1><p className="mt-2 text-sm leading-6 text-slate-500">{resume?.mode === "family" ? "Your family’s details have been submitted." : "Your details have been submitted."} Your travel team will review them.</p></section> : resume ? <>
      <div className="mb-5"><p className="text-xs font-semibold uppercase tracking-wider text-blue-600">{resume.mode === "family" ? `Family member ${resume.active + 1} of ${resume.members.length}` : "New traveller"}</p><h1 className="mt-1 text-2xl font-semibold tracking-tight text-slate-950">{resume.mode === "family" && resume.active === 0 ? "Head of family" : "Your travel details"}</h1></div>
      <FreshMember key={resume.members[resume.active].sessionId} token={token} group={group} resume={resume} onStarted={onStarted} onComplete={complete} onBack={onBack} />
    </> : <section className="mx-auto max-w-2xl rounded-3xl border border-slate-200 bg-white p-5 sm:p-8">
      <h1 className="text-2xl font-semibold tracking-tight text-slate-950">Who are you submitting for?</h1><p className="mt-2 text-sm leading-6 text-slate-500">Add one traveller, or complete each family member’s details together.</p>
      <div className="mt-6 grid gap-3 sm:grid-cols-2">{(["single", "family"] as const).map((value) => <button key={value} type="button" aria-pressed={mode === value} onClick={() => setMode(value)} className={`flex min-h-24 items-center gap-3 rounded-2xl border p-4 text-left ${mode === value ? "border-blue-500 bg-blue-50 text-blue-900" : "border-slate-200 text-slate-700"}`}>{value === "single" ? <UserRound className="h-6 w-6" /> : <UsersRound className="h-6 w-6" />}<span className="font-semibold">{value === "single" ? "Only me" : "Family"}</span></button>)}</div>
      {mode === "family" && <label className="mt-5 block text-sm font-medium text-slate-700">Number of travellers<select className="mt-2 h-12 w-full rounded-xl border border-slate-200 bg-white px-3 text-base" value={count} onChange={(event) => setCount(Number(event.target.value))}>{Array.from({ length: MAX_FAMILY_MEMBERS - MIN_FAMILY_MEMBERS + 1 }, (_, index) => index + MIN_FAMILY_MEMBERS).map((value) => <option key={value} value={value}>{value}</option>)}</select></label>}
      <Button type="button" className="mt-6 min-h-12 w-full" onClick={start}>Continue</Button>
    </section>}
  </TravellerShell>;
}
