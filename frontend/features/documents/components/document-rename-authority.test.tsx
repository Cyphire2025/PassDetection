import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth.store";
import { createRenameAuthorityContext, nextRenameActor, renameActor } from "../test-support/rename-authority.test-fixture";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/features/tour-operations/services/offline-snapshot", () => ({ purgeAllCoordinatorOfflineSnapshots: vi.fn(async () => undefined) }));
vi.mock("@/features/tour-operations/services/browser-offline-authorization", () => ({ purgeAllBrowserOfflineAuthorizations: vi.fn(async () => undefined) }));
vi.mock("@/components/shared/processing-motion", () => ({ ProcessingMotion: () => <div aria-hidden="true" /> }));
vi.mock("@/components/shared/intent-prefetch-link", () => ({ IntentPrefetchLink: ({ children }: { children: import("react").ReactNode }) => <span>{children}</span> }));

const contexts: ReturnType<typeof createRenameAuthorityContext>[] = [];
beforeEach(() => {
  window.localStorage.clear(); window.sessionStorage.clear();
  useAuthStore.setState({ user: null, hasHydrated: false, isAuthenticated: false, sessionVersion: 0 });
  useAuthStore.getState().setSession(renameActor);
});
afterEach(() => {
  cleanup(); contexts.splice(0).forEach(context => context.cleanup());
  vi.restoreAllMocks(); window.localStorage.clear(); window.sessionStorage.clear();
});
function mount(failure: Parameters<typeof createRenameAuthorityContext>[0] = null) {
  const context = createRenameAuthorityContext(failure); contexts.push(context);
  const view = context.mount(); return { ...context, ...view };
}
async function initiate(operation: "analyze" | "delete", fileCount = 1) {
  const context = mount();
  await screen.findByRole("button", { name: "Open" });
  if (operation === "delete") fireEvent.click(screen.getByRole("button", { name: "Delete" }));
  else {
    fireEvent.change(screen.getByLabelText("Batch title"), { target: { value: "Synthetic trip" } });
    fireEvent.change(context.container.querySelector('input[type="file"]')!, { target: { files: Array.from({ length: fileCount }, (_, i) =>
      new File(["%PDF-1.4 synthetic"], `synthetic-${i}.pdf`, { type: "application/pdf" })) } });
    fireEvent.click(screen.getByRole("button", { name: `Analyze And Rename (${fileCount})` }));
  }
  await waitFor(() => expect(context.entered).toHaveLength(1));
  expect(context.writes).toEqual([]);
  return context;
}

it.each(["analyze", "delete"] as const)("does not dispatch queued %s after actual account reset/remount", async operation => {
  const context = await initiate(operation);
  act(() => useAuthStore.getState().setSession(nextRenameActor));
  await waitFor(() => expect(screen.getByTestId("rename-page-owner")).toHaveTextContent(nextRenameActor.id));
  expect(context.unmounts).toEqual([renameActor.id]);
  await act(async () => context.release());
  await waitFor(() => expect(context.settled).toHaveLength(1));
  expect(context.writes, JSON.stringify(context.writes)).toEqual([]);
});

it.each(["analyze", "delete"] as const)("preserves same-owner %s across profile refresh", async operation => {
  const context = await initiate(operation);
  act(() => useAuthStore.getState().setSession({ ...renameActor, full_name: "Updated synthetic name" }));
  await act(async () => context.release());
  await waitFor(() => expect(context.settled).toHaveLength(1));
  expect(context.writes).toHaveLength(1);
  expect(context.writes[0]).toMatchObject({ actor: renameActor.id,
    authority: JSON.stringify([renameActor.id, renameActor.role, renameActor.agency_id]) });
  expect(context.mounts).toEqual([renameActor.id]);
  if (operation === "analyze") expect(await screen.findByRole("heading", { name: "Rename Results" })).toBeInTheDocument();
  else await waitFor(() => expect(screen.getByText("No rename batches yet.")).toBeInTheDocument());
});

it("stops the original file selection before a second chunk after authority changes following acknowledgement", async () => {
  const originalPost = apiClient.post.bind(apiClient);
  let acknowledged = 0;
  vi.spyOn(apiClient, "post").mockImplementation(async (...args) => {
    const response = await originalPost(...args);
    if (args[0] === "/api/v1/document-rename/batches" && ++acknowledged === 1) useAuthStore.getState().setSession(nextRenameActor);
    return response;
  });
  const context = await initiate("analyze", 51);
  await act(async () => context.release());
  await waitFor(() => expect(context.settled).toHaveLength(1));
  expect(context.writes).toHaveLength(1);
  expect(context.writes[0].filenames).toHaveLength(50);
  expect(context.writes[0].actor).toBe(renameActor.id);
  expect(screen.queryByRole("heading", { name: "Rename Results" })).not.toBeInTheDocument();
});

it("distinguishes a failed batch list from successful empty results and exposes retry", async () => {
  const context = mount("list");
  expect(await screen.findByRole("alert")).toHaveTextContent("Synthetic rename service unavailable");
  expect(screen.queryByText("No rename batches yet.")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Retry saved batches" })).toBeEnabled();
  context.setFailure(null);
  fireEvent.click(screen.getByRole("button", { name: "Retry saved batches" }));
  expect(await screen.findByRole("button", { name: "Open" })).toBeEnabled();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it.each(["open", "delete"] as const)("shows recoverable %s errors while retaining the saved batch", async failure => {
  const context = mount(failure);
  fireEvent.click(await screen.findByRole("button", { name: failure === "open" ? "Open" : "Delete" }));
  await waitFor(() => expect(context.entered).toHaveLength(1));
  await act(async () => context.release());
  await waitFor(() => expect(context.settled).toHaveLength(1));
  expect(await screen.findByRole("alert")).toHaveTextContent("Synthetic rename service unavailable");
  expect(screen.getByRole("button", { name: "Open" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Delete" })).toBeEnabled();
  context.setFailure(null);
  fireEvent.click(screen.getByRole("button", { name: failure === "open" ? "Open" : "Delete" }));
  await waitFor(() => expect(context.settled).toHaveLength(2));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  if (failure === "open") expect(screen.getByRole("heading", { name: "Rename Results" })).toBeInTheDocument();
  else expect(screen.getByText("No rename batches yet.")).toBeInTheDocument();
});

it("keeps one upload identity, ordered unique chunk IDs and every original file for a valid two-chunk upload", async () => {
  const context = await initiate("analyze", 51);
  await act(async () => context.release());
  await waitFor(() => expect(context.settled).toHaveLength(1));
  expect(context.writes).toHaveLength(2);
  expect(new Set(context.writes.map(write => write.uploadId)).size).toBe(1);
  expect(new Set(context.writes.map(write => write.chunkId)).size).toBe(2);
  expect(context.writes.map(write => write.chunkIndex)).toEqual(["0", "1"]);
  expect(context.writes.every(write => write.expectedFiles === "51" && write.actor === renameActor.id)).toBe(true);
  expect(context.writes.flatMap(write => write.filenames)).toEqual(Array.from({ length: 51 }, (_, i) => `synthetic-${i}.pdf`));
  expect(screen.getByRole("heading", { name: "Rename Results" })).toBeInTheDocument();
});

it.each([
  { operation: "analyze" as const, user: { ...renameActor, role: "agency_staff" as const } },
  { operation: "delete" as const, user: { ...renameActor, agency_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" } },
])("rejects queued $operation when the same user's authority changes", async ({ operation, user }) => {
  const context = await initiate(operation);
  act(() => useAuthStore.getState().setSession(user));
  await waitFor(() => expect(context.mounts).toHaveLength(2));
  expect(context.unmounts).toEqual([renameActor.id]);
  await act(async () => context.release());
  await waitFor(() => expect(context.settled).toHaveLength(1));
  expect(context.writes).toEqual([]);
});
