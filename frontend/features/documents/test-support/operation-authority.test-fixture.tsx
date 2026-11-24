import { createDocumentOperationTransport, type DocumentOperationMode } from "./operation-transport.test-fixture";
import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider, MutationCache } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import apiClient from "@/lib/api/client";
import { AuthenticatedContent } from "@/features/auth/components/authenticated-content";
import { SessionLifecycle } from "@/providers/session-lifecycle";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { DOCUMENT_DISTRIBUTION_LANES } from "../config/document-distribution-lanes";
import { useDocumentWorkspace } from "../hooks/use-document-workspace";
import { DocumentWorkspaceActions } from "../components/document-workspace-actions";

export const initialDocumentActor: User = {
  id: "11111111-1111-4111-8111-111111111111",
  email: "actor-a@example.test",
  full_name: "Synthetic A",
  role: "agency_admin",
  agency_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  is_active: true,
  created_at: "2026-10-01",
  updated_at: "2026-10-01",
  last_login_at: null,
};
export const replacementDocumentActor = { ...initialDocumentActor, id: "22222222-2222-4222-8222-222222222222", email: "actor-b@example.test" };
const groupId = "synthetic-group";

function deferred() {
  let resolve!: () => void;
  return {
    promise: new Promise<void>(done => {
      resolve = done;
    }), resolve: () => resolve()
  };
}

export function createDocumentAuthorityContext(operation: DocumentOperationMode = "discard") {
  const gate = deferred();
  const { adapter, writes, manualVerificationSignals, releaseManualVerification } = createDocumentOperationTransport(operation, groupId);
  const entered: unknown[] = [];
  const settled: unknown[] = [];
  const mounts: string[] = [], unmounts: string[] = [];
  const publicManualState: Array<{ variables: unknown; context: unknown; error: unknown }> = [];
  const previousAdapter = apiClient.defaults.adapter;
  const client = new QueryClient({
    mutationCache: new MutationCache({
      onMutate: async variables => {
        entered.push(variables);
        await gate.promise;
      },
      onSettled: (_data, error) => {
        settled.push(error);
      },
    }),
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  });
  // The real client's synchronous owner capture, cookie wrapper and owner-bound
  // adapter still execute; only the final network delegate is synthetic.
  apiClient.defaults.adapter = adapter;

  function Workspace() {
    const controller = useDocumentWorkspace(groupId, DOCUMENT_DISTRIBUTION_LANES.visa);
    const [mountedActor] = useState(() => useAuthStore.getState().user!.id);
    useEffect(
      () => {
        mounts.push(mountedActor);
        return () => {
          unmounts.push(mountedActor);
        };
      },
      [mountedActor]
    );
    useEffect(
      () => {
        publicManualState.push({
          variables: controller.manualUpload.variables,
          context: controller.manualUpload.context,
          error: controller.manualUpload.error
        });
      },
      [controller.manualUpload.variables, controller.manualUpload.context, controller.manualUpload.error]
    );
    return <>
      <output data-testid="workspace-owner">
        {mountedActor}
      </output>
      <button
        disabled={!controller.hasIncompleteUploads}
        onClick={() => controller.setIsAbortUploadDialogOpen(true)}
      >
        Open discard confirmation
      </button>
      <button
        disabled={!controller.review.data?.review_rows[0] || controller.manualUpload.isPending}
        onClick={() => {
          controller.manualUpload.reset();
          controller.setManualUploadTarget({ row: controller.review.data!.review_rows[0], mode: "add" });
        }}
      >Open manual passenger upload</button>
      <input
        aria-label="Synthetic verification PDF"
        type="file"
        onChange={event => controller.resetSelection(Array.from(event.target.files ?? []))}
      />
      <button
        disabled={!controller.selectedFiles.length || controller.preparingCheck}
        onClick={() => void controller.checkDocuments()}
      >Check selected synthetic PDF</button>
      <output data-testid="manual-candidate-count">
        {controller.manualReview.candidates.size}
      </output>
      <output data-testid="manual-approval-pending">
        {String(controller.manualReview.pending)}
      </output>
      <button
        disabled={!controller.manualReview.candidates.has(0)}
        onClick={() => controller.manualReview.openReview(0)}
      >Review selected synthetic PDF type</button>
      <button
        disabled={!controller.manualReview.reviewCandidates.length || controller.manualReview.pending}
        onClick={() => {
          if (controller.verification) void controller.manualReview.approve(controller.verification, controller.updateManualVerification);
        }}
      >Approve selected synthetic PDF type</button>
      <DocumentWorkspaceActions controller={controller} />
    </>;
  }
  function mount() {
    return render(<QueryClientProvider client={client}>
      <SessionLifecycle queryClient={client} />
      <AuthenticatedContent>
        <Workspace />
      </AuthenticatedContent>
    </QueryClientProvider>);
  }
  return {
    client,
    entered,
    settled,
    writes,
    mounts,
    unmounts,
    mount,
    publicManualState,
    release: gate.resolve,
    manualVerificationSignals,
    releaseManualVerification,
    cleanup: () => {
      client.clear();
      apiClient.defaults.adapter = previousAdapter;
    }
  };
}
