"use client";
import type { Dispatch, SetStateAction } from "react";
import { MessageCircle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CustomDetailFields, CustomQuestionFields } from "@/features/upload/components/upload-flow-fields";
import { ReviewFields } from "@/features/upload/components/upload-flow-review";
import type { useReturningDraft } from "../hooks/use-returning-draft";
import type { ReturningHistory } from "../types";
import { ReturningCurrentDetails } from "./returning-current-details";
type DraftForm = ReturnType<typeof useReturningDraft>;
type EditProps = {
  form: DraftForm;
  payload: NonNullable<DraftForm["payload"]>;
  setConfirmed: Dispatch<SetStateAction<boolean>>
};

export function ReturningPassportDetails({ displayName, extracting, draft, payload, form, setConfirmed }: EditProps & { displayName: string; extracting: boolean; draft: NonNullable<DraftForm["draft"]> }) {
  return (<section className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
    <div className="mb-5 flex items-center justify-between gap-3">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-slate-400">Passport details</p>
        <h2 className="mt-1 break-words text-lg font-semibold text-slate-950">
          {displayName}
        </h2>
      </div>
      <span className="rounded-full bg-slate-50 px-3 py-1 text-xs text-slate-500">Review & edit</span>
    </div>
    {extracting && <p
      role="status"
      className="mb-4 flex items-center gap-2 rounded-xl bg-blue-50 p-3 text-sm text-blue-800"
    >
      <RefreshCw className="h-4 w-4 animate-spin" />Reading your updated details page…</p>}
    {draft.extraction_status === "failed" && <p role="alert" className="mb-4 rounded-xl bg-amber-50 p-3 text-sm leading-6 text-amber-900">We couldn’t read this page reliably. Upload a clearer details page to continue.</p>}
    <fieldset disabled={form.pending || extracting}>
      <ReviewFields
        fields={payload.passport_fields}
        onChange={(key, value) => {
          setConfirmed(false);
          form.update("passport_fields", key, value);
        }}
      />
    </fieldset>
    <p className="mt-4 text-xs leading-5 text-slate-500">Check that these details match the document shown. Changes stay in your draft until you submit.</p>
  </section>);
}

export function ReturningContactDetails({ contact, draft, form, setContactOpen }: {
  contact: string | null;
  draft: NonNullable<DraftForm["draft"]>;
  form: DraftForm;
  setContactOpen: Dispatch<SetStateAction<boolean>>
}) {
  return (<section className="rounded-2xl border border-blue-200 bg-blue-50/80 p-5 sm:p-6">
    <div className="flex items-start gap-3">
      <MessageCircle className="mt-0.5 h-5 w-5 shrink-0 text-blue-600" />
      <div className="min-w-0 flex-1">
        <h2 className="text-sm font-semibold text-slate-950">Current WhatsApp contact</h2>
        <p className="mt-2 break-words text-lg font-semibold text-slate-900">
          {contact || "Add your current number"}
        </p>
        <p className="mt-1 text-xs leading-5 text-slate-600">
          {draft.verified_phone ? "Verified for this draft. Your contact updates when you submit." : "Use the number you want your travel team to contact for this trip."}
        </p>
      </div>
    </div>
    <Button
      type="button"
      variant="secondary"
      className="mt-4 min-h-11"
      disabled={form.pending}
      onClick={() => {
        void form.flush().then(() => setContactOpen(true)).catch(() => undefined);
      }}
    >
      {contact ? "Change WhatsApp number" : "Add WhatsApp number"}
    </Button>
  </section>);
}

export function ReturningTripFields({ history, payload, form, setConfirmed }: EditProps & { history: ReturningHistory }) {
  return (<section className="rounded-2xl border border-slate-200 bg-white p-5 sm:p-6">
    <h2 className="text-lg font-semibold text-slate-950">Details for this trip</h2>
    <p className="mt-1 text-sm leading-6 text-slate-500">Please complete the information requested by your travel team.</p>
    <fieldset disabled={form.pending}>
      <ReturningCurrentDetails
        fields={history.group_requirements.current_detail_fields ?? []}
        values={payload.current_details}
        onChange={(key, value) => {
          setConfirmed(false);
          form.update("current_details", key, value);
        }}
      />
      <CustomQuestionFields
        questions={history.group_requirements.custom_questions.filter((question) => question.enabled)}
        answers={payload.custom_answers}
        onChange={(key, value) => {
          setConfirmed(false);
          form.update("custom_answers", key, value);
        }}
      />
      <CustomDetailFields
        details={history.group_requirements.custom_details.filter((detail) => detail.enabled)}
        answers={payload.custom_detail_answers}
        onChange={(key, value) => {
          setConfirmed(false);
          form.update("custom_detail_answers", key, value);
        }}
      />
    </fieldset>
  </section>);
}
