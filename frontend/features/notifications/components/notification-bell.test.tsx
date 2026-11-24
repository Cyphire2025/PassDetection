import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useAuthStore } from "@/stores/auth.store";
import type { User } from "@/types";
import { GlobalSearch } from "@/features/search/components/global-search";
import { NotificationBell } from "./notification-bell";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("../hooks/use-notifications", () => ({
  useNotificationFeed: () => ({ data: { pages: [{ items: [], unread_count: 0 }] }, isLoading: false, isError: false, isFetching: false, hasNextPage: false }),
  useMarkNotificationRead: () => ({ isPending: false, isError: false, reset: vi.fn(), mutate: vi.fn() }),
  useMarkAllNotificationsRead: () => ({ isPending: false, isError: false, reset: vi.fn(), mutate: vi.fn() }),
}));
const initialAuth = useAuthStore.getState();
beforeEach(() => useAuthStore.setState({ user: { id: "notification-actor", role: "agency_admin", agency_id: "agency" } as User }));
afterEach(() => { cleanup(); useAuthStore.setState(initialAuth); });

describe("Notification dialog keyboard boundary", () => {
  it("keeps shortcut/programmatic focus inside its modal and restores the bell on close", async () => {
    const user = userEvent.setup();
    render(<><GlobalSearch /><NotificationBell /><button>Background action</button></>);
    const bell = screen.getByRole("button", { name: "Notifications, 0 unread" });
    const search = screen.getByRole("combobox");
    await user.click(bell);
    const dialog = screen.getByRole("dialog", { name: "Notifications" });
    await user.keyboard("{Control>}k{/Control}");
    expect(dialog.contains(document.activeElement)).toBe(true);
    expect(search.closest("[inert]")).not.toBeNull();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(bell).toHaveFocus();
    expect(search.closest("[inert]")).toBeNull();
  });
});
