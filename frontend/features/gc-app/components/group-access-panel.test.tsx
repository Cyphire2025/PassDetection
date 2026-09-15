import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GcAppControlPatch, GcAppGroupControl } from "../types";
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

describe("GC App availability and access window", () => {
  it("restores a paused closed-collection trip without resetting roles or dates", async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderPanel({ control: { ...CONTROL, lifecycle: "closed", gc_app_enabled: false,
      access_revoked_at: "2026-09-15T12:00:00Z", passenger_access_enabled: false,
      access_expires_at: "2026-12-01T12:00:00Z", app_availability: "paused", app_availability_reason: "app_disabled" }, onUpdate });
    await user.click(screen.getByRole("button", { name: "Restore app access" }));
    expect(onUpdate).toHaveBeenCalledExactlyOnceWith({ enabled: true });
    expect(screen.getByRole("switch", { name: "Passenger access" })).toHaveAttribute("aria-checked", "false");
  });

  it("pauses access with one explicit enablement change", async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    renderPanel({ onUpdate });
    await userEvent.setup().click(screen.getByRole("button", { name: "Pause app access" }));
    expect(onUpdate).toHaveBeenCalledExactlyOnceWith({ enabled: false });
  });

  it("explains missing My Photos prerequisites while allowing an existing feature to be disabled", async () => {
    const onSetMyPhotosEnabled = vi.fn().mockResolvedValue(undefined);
    const paused = { ...CONTROL, gc_app_enabled: false, passenger_access_enabled: false };
    const view = renderPanel({ control: paused, onSetMyPhotosEnabled });
    expect(screen.getByRole("switch", { name: "My Photos" })).toBeDisabled();
    expect(screen.getByText(/Enable GC App and Passenger access/)).toBeVisible();
    view.rerender(panel({ control: { ...paused, my_photos_enabled: true }, onSetMyPhotosEnabled }));
    await userEvent.setup().click(screen.getByRole("switch", { name: "My Photos" }));
    expect(onSetMyPhotosEnabled).toHaveBeenCalledExactlyOnceWith(false);
  });

  it("keeps date edits after unrelated settings refresh and saves only the window", async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    const view = renderPanel({ onUpdate });
    fireEvent.change(screen.getByLabelText("Access expires"), { target: { value: "2026-12-01T18:00" } });
    view.rerender(panel({ control: { ...CONTROL, revision: 8, my_photos_enabled: true }, onUpdate }));
    expect(screen.getByLabelText("Access expires")).toHaveValue("2026-12-01T18:00");
    await userEvent.setup().click(screen.getByRole("button", { name: "Save access window" }));
    expect(onUpdate).toHaveBeenCalledExactlyOnceWith({
      access_starts_at: null, access_expires_at: new Date("2026-12-01T18:00").toISOString(),
    });
  });

  it("keeps conflicting edits visible and requires loading remotely changed dates before saving", async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    const view = renderPanel({ onUpdate });
    fireEvent.change(screen.getByLabelText("Access expires"), { target: { value: "2026-12-01T18:00" } });
    view.rerender(panel({ control: { ...CONTROL, revision: 8, access_expires_at: "2027-01-01T12:00:00Z" }, onUpdate }));
    expect(screen.getByLabelText("Access expires")).toHaveValue("2026-12-01T18:00");
    expect(screen.getByRole("alert")).toHaveTextContent("saved access dates changed");
    expect(screen.getByRole("button", { name: "Save access window" })).toBeDisabled();
    expect(onUpdate).not.toHaveBeenCalled();
    await userEvent.setup().click(screen.getByRole("button", { name: "Load latest saved dates" }));
    expect(screen.getByLabelText("Access expires")).not.toHaveValue("2026-12-01T18:00");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("preserves dates on failed save and rejects an expiry before the start", async () => {
    const onUpdate = vi.fn().mockRejectedValue({ message: "GC App settings changed; refresh and retry" });
    renderPanel({ onUpdate });
    fireEvent.change(screen.getByLabelText("Access starts"), { target: { value: "2026-12-01T18:00" } });
    fireEvent.change(screen.getByLabelText("Access expires"), { target: { value: "2026-11-01T18:00" } });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Save access window" }));
    expect(onUpdate).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("expiry must be after");
    fireEvent.change(screen.getByLabelText("Access expires"), { target: { value: "2027-01-01T18:00" } });
    await user.click(screen.getByRole("button", { name: "Save access window" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("GC App settings changed");
    expect(screen.getByLabelText("Access expires")).toHaveValue("2027-01-01T18:00");
  });
});

type PanelOverrides = Partial<{
  control: GcAppGroupControl;
  isUpdating: boolean;
  onSetMyPhotosEnabled: (enabled: boolean) => Promise<void>;
  onUpdate: (patch: GcAppControlPatch) => Promise<void>;
}>;

function panel(overrides: PanelOverrides = {}) {
  return (
    <GroupAccessPanel
      control={overrides.control ?? CONTROL}
      isUpdating={overrides.isUpdating ?? false}
      onUpdate={overrides.onUpdate ?? vi.fn().mockResolvedValue(undefined)}
      onSetMyPhotosEnabled={overrides.onSetMyPhotosEnabled ?? vi.fn().mockResolvedValue(undefined)}
      onRevoke={vi.fn().mockResolvedValue(undefined)}
    />
  );
}

function renderPanel(overrides: PanelOverrides = {}) {
  return render(panel(overrides));
}
