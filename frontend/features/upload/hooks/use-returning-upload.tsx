"use client";

import { type ComponentProps, useState } from "react";
import dynamic from "next/dynamic";
import type { UploadLinkResponse } from "@/features/passports/api/upload-links.api";
import type { ReplacementIntent, ReturningCapabilities, ReturningMethod } from "@/features/travellers/types";
import { CenteredLoader } from "../components/upload-flow-shell";
import { UploadSuccessScreen } from "../components/upload-flow-status";
import type { UploadFlowStep } from "../components/upload-flow.types";
import { createIdempotencyKey } from "../services/upload-flow-session";

const ReturningFlow = dynamic(
  () => import("@/features/travellers/components/returning-flow").then((module) => module.ReturningFlow),
  { loading: () => <CenteredLoader /> },
);
const ReturningReplacementStatus = dynamic(
  () => import("@/features/travellers/components/returning-replacement-status").then((module) => module.ReturningReplacementStatus),
  { loading: () => <CenteredLoader /> },
);

/** The verified-person association lives only for the current in-memory flow. */
export function useReturningUpload({ token, group, onReplace }: {
  token: string;
  group: UploadLinkResponse | undefined;
  step: UploadFlowStep;
  onReplace: (intent: ReplacementIntent) => void;
}) {
  const [selection, setSelection] = useState<{ method: ReturningMethod; capabilities: ReturningCapabilities } | null>(null);
  const [replacementIntent, setReplacementIntent] = useState<ReplacementIntent | null>(null);
  const clearReplacement = () => setReplacementIntent(null);
  const verificationPage = selection && group ? <ReturningFlow
    key={token}
    token={token}
    group={group}
    initialMethod={selection.method}
    capabilities={selection.capabilities}
    onFresh={() => { setSelection(null); clearReplacement(); }}
    onReplace={(request) => {
      const intent = { ...request, uploadSessionId: createIdempotencyKey(), idempotencyKey: createIdempotencyKey() };
      setReplacementIntent(intent);
      setSelection(null);
      onReplace(intent);
    }}
  /> : null;
  const introduction = <>
    {replacementIntent && <p role="status" className="mb-4 rounded-xl border border-blue-100 bg-blue-50 p-4 text-sm leading-6 text-blue-900">Updating the passport for {replacementIntent.displayName}. Upload the current document for this person; staff will review it before future reuse.</p>}
  </>;
  const openDetectedHistory = () => { clearReplacement(); setSelection({ method: "passport", capabilities: { enabled: true, code_label: null } }); };
  return { verificationPage, introduction, replacementIntent, clearReplacement, openDetectedHistory };
}

/** A generic/family upload cannot inherit another person's replacement grant. */
export function ReturningUploadSuccess({ intent, uploadSessionId, ...props }: ComponentProps<typeof UploadSuccessScreen> & {
  intent: ReplacementIntent | null;
  uploadSessionId: string;
}) {
  if (intent && props.flowMode === "single" && props.submission && intent.uploadSessionId === uploadSessionId) {
    return <ReturningReplacementStatus intent={intent} submission={props.submission} />;
  }
  return <UploadSuccessScreen {...props} />;
}
