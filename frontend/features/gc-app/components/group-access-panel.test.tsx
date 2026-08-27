import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GcAppGroupControl } from "../types";
import { GroupAccessPanel } from "./group-access-panel";

afterEach(cleanup);

const CONTROL: GcAppGroupControl = {
  id: "019d2a5b-6357-7600-8ed3-98c5ca70bfa2",
  name: "Singapore 2026",
  lifecycle: "active",
  destination: "Singapore",
  start_date: "2026-11-01",
  end_date: "2026-11-08",
  company: { id: "019d2a5b-6357-7600-8ed3-98c5ca70bfa3", name: "Example Client" },
  gc_enabled: true,
  gc_revision: 7,
  gc_app_enabled: true,
  my_photos_enabled: false,
  passenger_access_enabled: true,
  client_manager_access_enabled: true,
  coordinator_access_enabled: true,
  access_starts_at: null,
  access_expires_at: null,
  access_revoked_at: null,
  revision: 7,
  organization_id: "019d2a5b-6357-7600-8ed3-98c5ca70bfa3",
  active_mobile_users: 2,
  synced_device_count: 2,
  last_successful_sync_at: "2026-08-28T10:00:00Z",
  versions: {
    itinerary_version: 1,
    common_document_version: 2,
    announcement_version: 3,
  },
};

describe("GroupAccessPanel My Photos control", () => {
  it("sends one dedicated visibility intent and waits for canonical props", async () => {
    const user = userEvent.setup();
    const onSetMyPhotosEnabled = vi.fn().mockResolvedValue(undefined);
    const view = renderPanel({ onSetMyPhotosEnabled });
    const myPhotos = screen.getByRole("switch", { name: "My Photos" });

    expect(myPhotos).toHaveAttribute("aria-checked", "false");
    await user.click(myPhotos);

    expect(onSetMyPhotosEnabled).toHaveBeenCalledTimes(1);
    expect(onSetMyPhotosEnabled).toHaveBeenCalledWith(true);
    expect(myPhotos).toHaveAttribute("aria-checked", "false");

    view.rerender(panel({
      control: { ...CONTROL, my_photos_enabled: true, revision: 8 },
      onSetMyPhotosEnabled,
    }));
    expect(screen.getByRole("switch", { name: "My Photos" }))
      .toHaveAttribute("aria-checked", "true");
  });

  it("keeps the canonical state and announces a rejected change", async () => {
    const user = userEvent.setup();
    const onSetMyPhotosEnabled = vi.fn().mockRejectedValue({
      message: "GC App settings changed; refresh and retry",
    });
    renderPanel({ onSetMyPhotosEnabled });

    await user.click(screen.getByRole("switch", { name: "My Photos" }));

    await waitFor(() => {
      expect(screen.getByRole("alert"))
        .toHaveTextContent("GC App settings changed; refresh and retry");
    });
    expect(screen.getByRole("switch", { name: "My Photos" }))
      .toHaveAttribute("aria-checked", "false");
  });

  it("blocks the feature switch while settings are pending or group access is unavailable", () => {
    const view = renderPanel({ isUpdating: true });
    expect(screen.getByRole("switch", { name: "My Photos" })).toBeDisabled();

    view.rerender(panel({
      control: { ...CONTROL, lifecycle: "archived" },
      isUpdating: false,
    }));
    expect(screen.getByRole("switch", { name: "My Photos" })).toBeDisabled();
  });
});

type PanelOverrides = Partial<{
  control: GcAppGroupControl;
  isUpdating: boolean;
  onSetMyPhotosEnabled: (enabled: boolean) => Promise<void>;
}>;

function panel(overrides: PanelOverrides = {}) {
  return (
    <GroupAccessPanel
      control={overrides.control ?? CONTROL}
      isUpdating={overrides.isUpdating ?? false}
      onUpdate={vi.fn().mockResolvedValue(undefined)}
      onSetMyPhotosEnabled={overrides.onSetMyPhotosEnabled ?? vi.fn().mockResolvedValue(undefined)}
      onRevoke={vi.fn().mockResolvedValue(undefined)}
    />
  );
}

function renderPanel(overrides: PanelOverrides = {}) {
  return render(panel(overrides));
}
