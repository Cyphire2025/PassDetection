"use client";

import { useEffect, useRef, useState } from "react";
import { TravellerShell } from "@/features/upload/components/traveller-shell";
import { ReviewDetailsColumn } from "@/features/upload/components/review-details-column";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import { useReturningDraft } from "../hooks/use-returning-draft";
import { returningApi } from "../api/returning.api";
import type { CompletionResult, ReplacementRequest, ReturningHistory, ReturningOwnedSource } from "../types";
import { ReturningContactDialog } from "./returning-contact-dialog";
import { ReturningDraftImages } from "./returning-draft-images";
import { ReturningCollection } from "./returning-collection";
import { draftReviewReadiness } from "../services/draft-readiness";
import { ReturningReviewHeader } from "./returning-review-header";
import { ReturningPassportDetails, ReturningContactDetails, ReturningTripFields } from "./returning-review-fields";
import { ReturningReviewDeclaration, ReturningReviewSuccess } from "./returning-review-confirmation";

type Props = {
  history: ReturningHistory;
  groupName: string;
  group?: UploadLinkResponse;
  groupToken?: string;
  onFresh: () => void;
  onReplace: (request: ReplacementRequest) => void;
  ownedSource?: ReturningOwnedSource;
  onCompleted?: (result: CompletionResult) => void
};

export function ReturningReview(props: Props) {
  const [history, setHistory] = useState(props.history);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string>();
  const operation = useRef<AbortController | null>(null);
  useEffect(() => () => operation.current?.abort(), []);
  const reload = async (passportId?: string) => {
    if (operation.current) return;
    const controller = new AbortController();
    operation.current = controller;
    setLoading(true);
    setLoadError(undefined);
    try {
      const result = passportId ? await returningApi.selectPassport(passportId, controller.signal, props.groupToken) : await returningApi.history(controller.signal, props.groupToken);
      if (!controller.signal.aborted) setHistory(result);
    } catch {
      if (!controller.signal.aborted) setLoadError("The latest details could not be loaded. Your draft is still saved; please retry.");
    }
    finally {
      operation.current = null;
      if (!controller.signal.aborted) setLoading(false);
    }
  };
  return <ReturningReviewContent
    key={history.review_version}
    {...props}
    history={history}
    loading={loading}
    loadError={loadError}
    reload={reload}
  />;
}

function ReturningReviewContent({
  history,
  groupName,
  group,
  groupToken = "",
  ownedSource,
  onFresh,
  onCompleted,
  loading,
  loadError,
  reload
}: Props & { loading: boolean; loadError?: string; reload: (id?: string) => Promise<void> }) {
  const form = useReturningDraft(history, groupToken, ownedSource);
  const [replacement, setReplacement] = useState(false);
  const [contactOpen, setContactOpen] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [result, setResult] = useState<CompletionResult>();
  const draft = form.draft;
  const payload = form.payload;
  const displayName = [payload?.passport_fields.given_names, payload?.passport_fields.surname].filter(Boolean).join(" ") || history.display_name;
  const { extracting, contact, needsContact, needsReplacement, needsBack, canSubmit } = draftReviewReadiness(history, draft, form.pending, confirmed, group);
  const photoRequired = (history.missing_requirements ?? []).some((key) => key === "fresh_photo" || key === "visa_photo");
  const qualifierRequired = (history.missing_requirements ?? []).includes("qualifier_relationship");
  if (result || draft?.status === "submitted") return <ReturningReviewSuccess result={result} draft={draft} groupName={groupName} onFresh={onFresh} />;
  return <TravellerShell wide>
    <ReturningReviewHeader
      history={history}
      groupName={groupName}
      form={form}
      draft={draft}
      loading={loading}
      loadError={loadError}
      reload={reload}
      replacement={replacement}
      setReplacement={setReplacement}
    />
    {!draft || !payload ? <div
      role="status"
      className="rounded-2xl border border-slate-200 bg-white p-8 text-center text-sm text-slate-500"
    >Preparing your secure review…</div> : <form
      onSubmit={(event) => {
        event.preventDefault();
        if (!canSubmit || uploadBusy) return;
        void form.complete().then((saved) => {
          setResult(saved);
          onCompleted?.(saved);
        }).catch(() => undefined);
      }}
    >
      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,0.92fr)_minmax(0,1.08fr)]">
        <div className="min-w-0 space-y-5">
          {group ? <ReturningCollection
            form={form}
            group={group}
            token={groupToken}
            documents={history.documents}
            updatesEnabled={replacement}
            qualifier={qualifierRequired}
            onChange={() => setConfirmed(false)}
            onUploadBusyChange={setUploadBusy}
          /> : <>
            <p
              role="alert"
              className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"
            >The trip’s document settings could not be loaded. Refresh the link before completing these requirements.</p>
            <ReturningDraftImages documents={history.documents} draft={draft} hidePhoto={photoRequired} />
          </>}
        </div>
        <ReviewDetailsColumn>
          <ReturningPassportDetails
            displayName={displayName}
            extracting={extracting}
            draft={draft}
            payload={payload}
            form={form}
            setConfirmed={setConfirmed}
          />
          <ReturningContactDetails contact={contact} draft={draft} form={form} setContactOpen={setContactOpen} />
          <ReturningTripFields history={history} payload={payload} form={form} setConfirmed={setConfirmed} />
        </ReviewDetailsColumn>
      </div>
      <ReturningReviewDeclaration
        needsReplacement={needsReplacement}
        needsContact={needsContact}
        needsBack={needsBack}
        confirmed={confirmed}
        setConfirmed={setConfirmed}
        form={form}
        extracting={extracting}
        uploadBusy={uploadBusy}
        canSubmit={canSubmit}
      />
    </form>}
    {contactOpen && draft && <ReturningContactDialog
      draftId={draft.id}
      onClose={() => setContactOpen(false)}
      onSaved={() => {
        setConfirmed(false);
        setContactOpen(false);
        void form.refresh().catch(() => undefined);
      }}
    />}
  </TravellerShell>;
}
