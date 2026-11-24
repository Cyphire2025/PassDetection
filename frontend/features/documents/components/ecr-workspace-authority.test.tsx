import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import apiClient from "@/lib/api/client";
import { useAuthStore } from "@/stores/auth.store";
import { ecrKeys } from "../hooks/use-ecr-checker";
import { createEcrAuthorityContext, ecrActor, ecrBatch, replacementEcrActor } from "../test-support/ecr-authority.test-fixture";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/features/tour-operations/services/offline-snapshot", () => ({ purgeAllCoordinatorOfflineSnapshots: vi.fn(async () => undefined) }));
vi.mock("@/features/tour-operations/services/browser-offline-authorization", () => ({ purgeAllBrowserOfflineAuthorizations: vi.fn(async () => undefined) }));
vi.mock("@/components/shared/intent-prefetch-link", () => ({ IntentPrefetchLink: ({ children }: { children: import("react").ReactNode }) => <span>{children}</span> }));

const contexts: ReturnType<typeof createEcrAuthorityContext>[] = [];
beforeEach(() => {
  localStorage.clear(); sessionStorage.clear();
  window.history.replaceState(null, "", "/documents/ecr");
  useAuthStore.setState({ user: null, hasHydrated: false, isAuthenticated: false, sessionVersion: 0 });
  useAuthStore.getState().setSession(ecrActor);
});
afterEach(() => {
  cleanup(); contexts.splice(0).forEach(context => context.cleanup());
  vi.restoreAllMocks(); localStorage.clear(); sessionStorage.clear();
});

function mount(existing: boolean) {
  const context = createEcrAuthorityContext(existing); contexts.push(context);
  return { ...context, ...context.mount() };
}
async function initiate(kind: "create" | "retry") {
  const context = mount(kind === "retry");
  if (kind === "retry") fireEvent.click(await screen.findByRole("button", { name: "Retry failed checks" }));
  else {
    fireEvent.change(screen.getByLabelText("Select passport back-page images"), { target: { files: [
      new File(["synthetic image"], "synthetic.jpg", { type: "image/jpeg" }),
    ] } });
    fireEvent.click(screen.getByRole("button", { name: "Upload & check ECR" }));
  }
  return context;
}

it.each(["create", "retry"] as const)("does not republish %s evidence after actual actor reset and page remount", async kind => {
  const original = apiClient.post.bind(apiClient);
  let crossed = false;
  vi.spyOn(apiClient, "post").mockImplementation(async (...args) => {
    const response = await original(...args);
    if (args[0] === `/api/v1/ecr-checker/batches${kind === "retry" ? `/${ecrBatch.batch_id}/retry` : ""}`) {
      crossed = true;
      await act(async () => useAuthStore.getState().setSession(replacementEcrActor));
    }
    return response;
  });
  const context = await initiate(kind);
  await waitFor(() => expect(crossed).toBe(true));
  await waitFor(() => expect(screen.getByTestId("ecr-page-owner")).toHaveTextContent(replacementEcrActor.id));
  expect(context.unmounts).toEqual([ecrActor.id]);
  await waitFor(() => expect(context.client.isFetching()).toBe(0));
  expect(context.client.getQueryData(ecrKeys.batch(ecrBatch.batch_id))).toBeUndefined();
  expect(sessionStorage.getItem(`passdetection:ecr-upload:${ecrBatch.batch_id}`)).toBeNull();
  expect(context.writes).toHaveLength(1);
  expect(context.writes[0].actor).toBe(ecrActor.id);
});

it.each(["create", "retry"] as const)("preserves %s through a same-authority profile refresh", async kind => {
  const original = apiClient.post.bind(apiClient);
  vi.spyOn(apiClient, "post").mockImplementation(async (...args) => {
    const response = await original(...args);
    act(() => useAuthStore.getState().setSession({ ...ecrActor, full_name: "Updated synthetic profile" }));
    return response;
  });
  const context = await initiate(kind);
  await waitFor(() => expect(context.client.getQueryData(ecrKeys.batch(ecrBatch.batch_id))).toMatchObject({ status: "queued" }));
  expect(context.mounts).toEqual([ecrActor.id]);
  expect(context.writes).toHaveLength(kind === "create" ? 3 : 1);
  expect(context.writes.every(write => write.actor === ecrActor.id)).toBe(true);
  expect(sessionStorage.getItem(`passdetection:ecr-upload:${ecrBatch.batch_id}`)).toBeNull();
});

it.each(["items", "start"] as const)("stops publication after %s acknowledgement when the initiating actor changes", async phase => {
  const original = apiClient.post.bind(apiClient);
  vi.spyOn(apiClient, "post").mockImplementation(async (...args) => {
    const response = await original(...args);
    if (args[0] === `/api/v1/ecr-checker/batches/${ecrBatch.batch_id}/${phase}`) {
      await act(async () => useAuthStore.getState().setSession(replacementEcrActor));
    }
    return response;
  });
  const context = await initiate("create");
  await waitFor(() => expect(screen.getByTestId("ecr-page-owner")).toHaveTextContent(replacementEcrActor.id));
  await waitFor(() => expect(context.client.isFetching()).toBe(0));
  expect(context.client.getQueryData(ecrKeys.batch(ecrBatch.batch_id))).toBeUndefined();
  expect(context.writes).toHaveLength(phase === "items" ? 2 : 3);
  expect(context.writes.every(write => write.actor === ecrActor.id)).toBe(true);
  expect(screen.queryByText(ecrBatch.title)).not.toBeInTheDocument();
});

it.each([
  { label: "role", actor: { ...ecrActor, role: "agency_staff" as const } },
  { label: "agency", actor: { ...ecrActor, agency_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" } },
])("does not republish retry evidence after same-user $label changes", async ({ actor }) => {
  const original = apiClient.post.bind(apiClient);
  vi.spyOn(apiClient, "post").mockImplementation(async (...args) => {
    const response = await original(...args);
    await act(async () => useAuthStore.getState().setSession(actor));
    return response;
  });
  const context = await initiate("retry");
  await waitFor(() => expect(context.mounts).toHaveLength(2));
  await waitFor(() => expect(context.client.isFetching()).toBe(0));
  expect(context.client.getQueryData(ecrKeys.batch(ecrBatch.batch_id))).toBeUndefined();
  expect(context.writes).toHaveLength(1);
  expect(screen.queryByText(ecrBatch.title)).not.toBeInTheDocument();
});
