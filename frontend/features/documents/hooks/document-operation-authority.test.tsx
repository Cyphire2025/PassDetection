import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import { documentDistributionApi } from "../api/document-distribution.api";
import {
  createDocumentAuthorityContext, initialDocumentActor, replacementDocumentActor,
} from "../test-support/operation-authority.test-fixture";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock(
  "@/features/tour-operations/services/offline-snapshot",
  () => ({ purgeAllCoordinatorOfflineSnapshots: vi.fn(async () => undefined) })
);
vi.mock(
  "@/features/tour-operations/services/browser-offline-authorization",
  () => ({ purgeAllBrowserOfflineAuthorizations: vi.fn(async () => undefined) })
);
vi.mock(
  "@/features/whatsapp/components/whatsapp-activity-tracker",
  () => ({ useWhatsAppActivityTracker: () => ({ registerActivity: vi.fn() }) })
);
vi.mock(
  "../components/document-workspace-bindings",
  async () => ({
    AbortIncompleteUploadDialog: (await vi.importActual<typeof import("../components/abort-incomplete-upload-dialog")>("../components/abort-incomplete-upload-dialog")).AbortIncompleteUploadDialog,
    DocumentDeliveryPreviewDialog: () => null,
    RemoveAssignmentsDialog: () => null,
  })
);

const contexts: ReturnType<typeof createDocumentAuthorityContext>[] = [];
beforeEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  useAuthStore.setState({ user: null, hasHydrated: false, isAuthenticated: false, sessionVersion: 0 });
  useAuthStore.getState().setSession(initialDocumentActor);
});
afterEach(() => {
  cleanup();
  contexts.splice(0).forEach(context => context.cleanup());
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.restoreAllMocks();
});

async function initiateNormalDiscard() {
  const context = createDocumentAuthorityContext();
  contexts.push(context);
  context.mount();
  const open = await screen.findByRole("button", { name: "Open discard confirmation" });
  await waitFor(() => expect(open).toBeEnabled());
  fireEvent.click(open);
  fireEvent.click(await screen.findByRole("button", { name: "Discard incomplete uploads" }));
  await waitFor(() => expect(context.entered).toHaveLength(1));
  expect(context.writes).toEqual([]);
  return context;
}

it(
  "does not dispatch an old confirmed discard after real account reset and authority-key workspace remount",
  async () => {
    const context = await initiateNormalDiscard();
    act(() => useAuthStore.getState().setSession(replacementDocumentActor));
    await waitFor(() => expect(screen.getByTestId("workspace-owner")).toHaveTextContent(replacementDocumentActor.id));
    expect(context.unmounts).toContain(initialDocumentActor.id);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await act(async () => {
      context.release();
    });
    await waitFor(() => expect(context.settled.length).toBeGreaterThan(0));
    expect(context.writes, `Synthetic stale discard dispatches: ${JSON.stringify(context.writes)}`).toEqual([]);
  }
);

it.each([false, true])(
  "keeps normal confirmed same-owner discard working across a profile update=%s",
  async profileUpdate => {
    const context = await initiateNormalDiscard();
    if (profileUpdate) act(() => useAuthStore.getState().setSession({ ...initialDocumentActor, full_name: "Updated synthetic profile", updated_at: "2026-10-31" }));
    await act(async () => {
      context.release();
    });
    await waitFor(() => expect(context.settled.length).toBeGreaterThan(0));
    expect(context.writes).toHaveLength(2);
    expect(context.writes.every(write => write.actor === initialDocumentActor.id)).toBe(true);
    expect(context.writes.every(write => write.authority === JSON.stringify([initialDocumentActor.id, initialDocumentActor.role, initialDocumentActor.agency_id]))).toBe(true);
    expect(context.mounts).toEqual([initialDocumentActor.id]);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  }
);

it(
  "does not continue acknowledged bulk cleanup after authority changes between real API calls",
  async () => {
    const originalAbort = documentDistributionApi.abortUpload;
    vi.spyOn(documentDistributionApi, "abortUpload").mockImplementation(async (...args) => {
      const response = await originalAbort(...args);
      useAuthStore.getState().setSession(replacementDocumentActor);
      return response;
    });
    const context = await initiateNormalDiscard();
    await act(async () => {
      context.release();
    });
    await waitFor(() => expect(context.settled.length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByTestId("workspace-owner")).toHaveTextContent(replacementDocumentActor.id));
    expect(context.writes.map(write => write.actor)).toEqual([initialDocumentActor.id]);
    expect(context.writes[0].url).toContain("synthetic-upload-a/abort");
  }
);

async function initiateNormalManualUpload(operation: "manual" | "manual-error" = "manual") {
  const context = createDocumentAuthorityContext(operation);
  contexts.push(context);
  context.mount();
  const open = await screen.findByRole("button", { name: "Open manual passenger upload" });
  await waitFor(() => expect(open).toBeEnabled());
  fireEvent.click(open);
  fireEvent.change(
    await screen.findByLabelText("Choose PDF"),
    {
      target: { files: [new File(["%PDF synthetic private document"], "synthetic-personal.pdf", { type: "application/pdf" })] }
    }
  );
  fireEvent.click(screen.getByRole("button", { name: "Upload and save" }));
  await waitFor(() => expect(context.entered).toHaveLength(1));
  expect(context.writes).toEqual([]);
  return context;
}

it(
  "does not upload an abandoned manual PDF under a replacement actor after real reset and remount",
  async () => {
    const context = await initiateNormalManualUpload();
    act(() => useAuthStore.getState().setSession(replacementDocumentActor));
    await waitFor(() => expect(screen.getByTestId("workspace-owner")).toHaveTextContent(replacementDocumentActor.id));
    expect(context.unmounts).toContain(initialDocumentActor.id);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await act(async () => {
      context.release();
    });
    await waitFor(() => expect(context.settled.length).toBeGreaterThan(0));
    expect(context.writes, `Synthetic stale manual dispatches: ${JSON.stringify(context.writes)}`).toEqual([]);
  }
);

it.each([false, true])(
  "keeps manual PDF save working for the same owner across a profile update=%s",
  async profileUpdate => {
    const context = await initiateNormalManualUpload();
    if (profileUpdate) act(() => useAuthStore.getState().setSession({ ...initialDocumentActor, full_name: "Updated synthetic profile", updated_at: "2026-10-31" }));
    await act(async () => {
      context.release();
    });
    await waitFor(() => expect(context.settled.length).toBeGreaterThan(0));
    expect(context.writes).toHaveLength(1);
    expect(context.writes[0]).toMatchObject({ actor: initialDocumentActor.id, filename: "synthetic-personal.pdf" });
    expect(context.mounts).toEqual([initialDocumentActor.id]);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  }
);

it(
  "preserves actual manual-upload public variables, undefined context, ordinary error and retry dialog",
  async () => {
    const context = await initiateNormalManualUpload("manual-error");
    const envelope = context.entered[0] as { variables: { passengerId: string; file: File; mode: string; replacements: unknown[] } };
    await waitFor(() => expect(context.publicManualState.some(state => state.variables !== undefined)).toBe(true));
    expect(context.publicManualState.find(state => state.variables !== undefined)?.variables).toBe(envelope.variables);
    expect(envelope.variables).toMatchObject({ passengerId: "synthetic-passenger", mode: "add", replacements: [] });
    expect(envelope.variables.file.name).toBe("synthetic-personal.pdf");
    await act(async () => {
      context.release();
    });
    await waitFor(() => expect(context.settled.length).toBeGreaterThan(0));
    expect(await screen.findByRole("alert")).toHaveTextContent("Synthetic revision changed");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload and save" })).toBeEnabled();
    const state = context.publicManualState.at(-1)!;
    expect(state.variables).toBe(envelope.variables);
    expect(state.context).toBeUndefined();
    expect(state.error).toMatchObject({ code: "DOC_CONFLICT", status: 409, message: "Synthetic revision changed" });
    expect(context.writes).toHaveLength(1);
  }
);

it.each(["role", "agency"] as const)(
  "fences queued manual intent when the same actor changes effective %s",
  async change => {
    const context = await initiateNormalManualUpload();
    const replacement = change === "role"
      ? { ...initialDocumentActor, role: "agency_staff" as const }
      : { ...initialDocumentActor, agency_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" };
    act(() => useAuthStore.getState().setSession(replacement));
    await waitFor(() => expect(context.unmounts).toContain(initialDocumentActor.id));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await act(async () => {
      context.release();
    });
    await waitFor(() => expect(context.settled.length).toBeGreaterThan(0));
    expect(context.writes).toEqual([]);
  }
);

async function initiateNormalVerification(operation: "verify" | "manual-review" = "verify") {
  const context = createDocumentAuthorityContext(operation);
  contexts.push(context);
  context.mount();
  fireEvent.change(
    await screen.findByLabelText("Synthetic verification PDF"),
    {
      target: { files: [new File(["%PDF synthetic verification document"], "synthetic-check.pdf", { type: "application/pdf" })] }
    }
  );
  fireEvent.click(screen.getByRole("button", { name: "Check selected synthetic PDF" }));
  await waitFor(() => expect(context.entered).toHaveLength(1));
  expect(context.writes).toEqual([]);
  return context;
}

it(
  "keeps the existing workspace abort protection for queued verification across reset/remount",
  async () => {
    const context = await initiateNormalVerification();
    act(() => useAuthStore.getState().setSession(replacementDocumentActor));
    await waitFor(() => expect(screen.getByTestId("workspace-owner")).toHaveTextContent(replacementDocumentActor.id));
    await act(async () => {
      context.release();
    });
    await waitFor(() => expect(context.settled.length).toBeGreaterThan(0));
    expect(context.writes).toEqual([]);
  }
);

it(
  "keeps verification and its real receipt path working across a same-owner profile refresh",
  async () => {
    const context = await initiateNormalVerification();
    act(() => useAuthStore.getState().setSession({ ...initialDocumentActor, full_name: "Updated synthetic profile", updated_at: "2026-10-31" }));
    await act(async () => {
      context.release();
    });
    await waitFor(() => expect(context.settled.length).toBeGreaterThan(0));
    expect(context.writes).toHaveLength(1);
    expect(context.writes[0]).toMatchObject({ actor: initialDocumentActor.id, filenames: ["synthetic-check.pdf"] });
    expect(context.mounts).toEqual([initialDocumentActor.id]);
  }
);

async function initiateManualVerification() {
  const context = await initiateNormalVerification("manual-review");
  await act(async () => {
    context.release();
  });
  await waitFor(() => expect(screen.getByTestId("manual-candidate-count")).toHaveTextContent("1"));
  fireEvent.click(screen.getByRole("button", { name: "Review selected synthetic PDF type" }));
  fireEvent.click(screen.getByRole("button", { name: "Approve selected synthetic PDF type" }));
  await waitFor(() => expect(context.writes.filter(write => write.url.endsWith("/manual-verify"))).toHaveLength(1));
  expect(context.manualVerificationSignals).toHaveLength(1);
  expect(JSON.stringify({ ...sessionStorage })).not.toContain("synthetic-manual-type-proof");
  return context;
}

it(
  "aborts in-flight manual type verification and never finalizes its old receipt after actor replacement",
  async () => {
    const context = await initiateManualVerification();
    act(() => useAuthStore.getState().setSession(replacementDocumentActor));
    await waitFor(() => expect(screen.getByTestId("workspace-owner")).toHaveTextContent(replacementDocumentActor.id));
    expect(context.manualVerificationSignals[0].aborted).toBe(true);
    await act(async () => {
      context.releaseManualVerification();
    });
    await waitFor(() => expect(screen.getByTestId("manual-approval-pending")).toHaveTextContent("false"));
    expect(context.writes.filter(write => write.url.endsWith("/upload"))).toEqual([]);
    expect(context.writes.every(write => write.actor === initialDocumentActor.id)).toBe(true);
    expect(JSON.stringify({ ...sessionStorage })).not.toContain("synthetic-approved-receipt");
  }
);

it(
  "preserves manual proof and receipt-only finalization across a same-owner profile refresh",
  async () => {
    const context = await initiateManualVerification();
    act(() => useAuthStore.getState().setSession({ ...initialDocumentActor, full_name: "Updated synthetic profile", updated_at: "2026-10-31" }));
    expect(context.manualVerificationSignals[0].aborted).toBe(false);
    await act(async () => {
      context.releaseManualVerification();
    });
    await waitFor(() => expect(context.writes.filter(write => write.url.endsWith("/upload"))).toHaveLength(1));
    await waitFor(() => expect(screen.getByTestId("manual-approval-pending")).toHaveTextContent("false"));
    expect(context.writes.every(write => write.actor === initialDocumentActor.id)).toBe(true);
    expect(context.mounts).toEqual([initialDocumentActor.id]);
    expect(JSON.stringify({ ...sessionStorage })).not.toContain("synthetic-approved-receipt");
  }
);
