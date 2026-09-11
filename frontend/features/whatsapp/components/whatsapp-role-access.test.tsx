import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DashboardWhatsAppPage from "@/app/(dashboard)/whatsapp/page";
import { Sidebar } from "@/components/layout/sidebar";
import {
  GroupWhatsAppBroadcastPanel,
  GroupWhatsAppBroadcastTrackingPage,
} from "@/features/passports/components/group-whatsapp-broadcast-panel";
import { useAuthStore } from "@/stores/auth.store";
import type { User, UserRole } from "@/types";

const { router, links, updateLinks, idleMutation } = vi.hoisted(() => ({
  router: { replace: vi.fn(), prefetch: vi.fn() },
  links: {
    can_manage: true,
    broadcast_count: 1,
    recipient_count: 2,
    broadcasts: [{ id: "broadcast-1", name: "Autumn travellers", recipient_count: 2 }],
  },
  updateLinks: { mutate: vi.fn(), isPending: false },
  idleMutation: { mutate: vi.fn(), isPending: false },
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/whatsapp",
  useRouter: () => router,
}));
vi.mock("@/components/brand/brand-logo", () => ({ BrandLogo: () => null }));
vi.mock("./whatsapp-page", () => ({ WhatsAppPage: () => <p>WhatsApp communication workspace</p> }));
vi.mock("@/features/passports/hooks/use-upload-links", () => ({
  useGroupWhatsAppLinks: () => ({ data: links, isLoading: false }),
  useGroupWhatsAppMatches: () => ({ data: undefined, isLoading: false }),
  useRejectUnidentifiedUpload: () => idleMutation,
  useRestoreRosterResolution: () => idleMutation,
  useUpdateGroupWhatsAppLinks: () => updateLinks,
}));
vi.mock("@/features/passports/hooks/use-passports", () => ({
  useExportWhatsAppTracking: () => idleMutation,
}));
vi.mock("@/features/passports/components/whatsapp-broadcast-selector", () => ({
  WhatsAppBroadcastSelector: ({ onChange }: { onChange: (ids: string[]) => void }) => (
    <button onClick={() => onChange(["broadcast-2"])}>Select new broadcast</button>
  ),
}));

function signIn(role: UserRole) {
  useAuthStore.setState({
    user: { id: `${role}-1`, role, agency_id: "agency-1", is_active: true } as User,
    isAuthenticated: true,
    hasHydrated: true,
  });
}

beforeEach(() => {
  router.replace.mockReset();
  updateLinks.mutate.mockReset();
  links.can_manage = true;
  links.broadcast_count = 1;
  signIn("agency_staff");
});

describe("staff WhatsApp access", () => {
  it("shows Communication navigation and mounts the direct WhatsApp route", () => {
    render(<><Sidebar /><DashboardWhatsAppPage /></>);
    expect(screen.getByText("Communication")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "WhatsApp" })).toHaveAttribute("href", "/whatsapp");
    expect(screen.getByText("WhatsApp communication workspace")).toBeInTheDocument();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it("opens group tracking and keeps broadcast management available", () => {
    render(<GroupWhatsAppBroadcastTrackingPage groupId="group-1" />);
    expect(screen.getByRole("heading", { name: "WhatsApp Submission Tracking" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Manage broadcasts" })).toBeEnabled();
    expect(router.replace).not.toHaveBeenCalled();
  });

  it.each([true, false])("lets staff link or manage broadcasts from the group when already linked=%s", (alreadyLinked) => {
    links.broadcast_count = alreadyLinked ? 1 : 0;
    render(<GroupWhatsAppBroadcastPanel groupId="group-1" />);
    if (alreadyLinked) {
      expect(screen.getByRole("link", { name: "View tracking" }))
        .toHaveAttribute("href", "/passports/groups/group-1/whatsapp");
    }
    fireEvent.click(screen.getByRole("button", { name: alreadyLinked ? "Manage broadcasts" : "Link broadcasts" }));
    expect(screen.getByRole("dialog", { name: "Link WhatsApp broadcasts" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Select new broadcast" }));
    fireEvent.click(screen.getByRole("button", { name: "Save linked broadcasts" }));
    expect(updateLinks.mutate).toHaveBeenCalledWith({
      whatsappBroadcastGroupIds: ["broadcast-2"],
      matchingFieldsByBroadcast: {},
    }, expect.any(Object));
  });

  it("respects the server group-management permission even when staff can view broadcasts", () => {
    links.can_manage = false;
    render(<GroupWhatsAppBroadcastPanel groupId="group-1" />);
    expect(screen.getByRole("link", { name: "View tracking" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Manage broadcasts" })).not.toBeInTheDocument();
  });

  it("keeps coordinators out of WhatsApp navigation and direct routes", () => {
    signIn("agency_coordinator");
    render(<><Sidebar /><DashboardWhatsAppPage /><GroupWhatsAppBroadcastTrackingPage groupId="group-1" /></>);
    expect(screen.queryByRole("link", { name: "WhatsApp" })).not.toBeInTheDocument();
    expect(screen.queryByText("WhatsApp communication workspace")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "WhatsApp Submission Tracking" })).not.toBeInTheDocument();
    expect(router.replace).toHaveBeenCalledWith("/coordinator");
  });
});
