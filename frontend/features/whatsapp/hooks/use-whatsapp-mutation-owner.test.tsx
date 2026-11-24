import { webcrypto } from "node:crypto";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { whatsappApi, type WhatsAppBroadcastGroupDetail } from "../api/whatsapp.api";
import { composerApi } from "../workspace/composer.api";
import { useNormalWhatsAppSend } from "./use-normal-send";
import { useUpdateWhatsAppGroup, WHATSAPP_QUERY_KEYS } from "./use-whatsapp";

const { post } = vi.hoisted(() => ({ post: vi.fn() }));
vi.mock("@/lib/api/client", () => ({ default: { post } }));
const actor: User = { id: "actor-a", email: "a@example.test", full_name: "Synthetic A", role: "agency_admin", agency_id: "agency-a",
  is_active: true, last_login_at: null, created_at: "2026-01-01", updated_at: "2026-01-01" };
const group: WhatsAppBroadcastGroupDetail = { id: "group-a", name: "A private passenger group", recipients: [], support_contacts: [],
  recipient_count: 0, total_contact_count: 0, recipient_opt_in_confirmed: true, rejected_contact_count: 0, created_at: "2026-01-01", updated_at: "2026-01-01" };
function deferred() { let resolve!: () => void; const promise = new Promise<void>((finish) => { resolve = finish; }); return { promise, resolve }; }
const clients: QueryClient[] = [];
function wrapper(cache: MutationCache) {
  const client = new QueryClient({ mutationCache: cache, defaultOptions: { mutations: { retry: false } } }); clients.push(client);
  return { client, wrapper: ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> };
}
beforeEach(() => { vi.stubGlobal("crypto", webcrypto); window.sessionStorage.clear(); post.mockReset().mockResolvedValue({ data: { queued: 1 } }); useAuthStore.setState({ user: actor, sessionVersion: 1 }); });
afterEach(() => { clients.splice(0).forEach((client) => client.clear()); vi.restoreAllMocks(); vi.unstubAllGlobals(); window.sessionStorage.clear(); });

it("retains the caller before global onMutate so old reviewed content cannot dispatch as B", async () => {
  const gate = deferred(), entered = vi.fn();
  const context = wrapper(new MutationCache({ onMutate: async () => { entered(); await gate.promise; } }));
  const { result } = renderHook(() => useNormalWhatsAppSend("welcome", composerApi.send), context);
  let pending!: Promise<unknown>; let failure: unknown;
  act(() => { pending = result.current.mutateAsync({ groupId: "group-a", recipientIds: ["recipient-a"], image: null, draft: { message_type: "welcome", message_content: "A reviewed private message" } }); });
  await waitFor(() => expect(entered).toHaveBeenCalledOnce());
  useAuthStore.setState({ user: { ...actor, id: "actor-b" }, sessionVersion: 2 });
  await act(async () => { gate.resolve(); try { await pending; } catch (error) { failure = error; } });
  expect(post).not.toHaveBeenCalled();
  expect(failure).toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
});

it("does not repopulate B's cleared group cache with A's result after global success awaits", async () => {
  const gate = deferred(), entered = vi.fn();
  vi.spyOn(whatsappApi, "updateGroup").mockResolvedValue(group);
  const context = wrapper(new MutationCache({ onSuccess: async () => { entered(); await gate.promise; } }));
  const { result } = renderHook(useUpdateWhatsAppGroup, context);
  let pending!: Promise<unknown>; let failure: unknown;
  act(() => { pending = result.current.mutateAsync({ groupId: group.id, name: group.name }); });
  await waitFor(() => expect(entered).toHaveBeenCalledOnce());
  useAuthStore.setState({ user: { ...actor, id: "actor-b" }, sessionVersion: 2 });
  context.client.clear();
  await act(async () => { gate.resolve(); try { await pending; } catch (error) { failure = error; } });
  expect(context.client.getQueryData(WHATSAPP_QUERY_KEYS.group(group.id))).toBeUndefined();
  expect(failure).toMatchObject({ code: "AUTH_REQUEST_OWNER_CHANGED" });
});
