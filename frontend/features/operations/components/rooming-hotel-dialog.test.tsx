import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { ModalFocusTracker } from "@/components/ui/modal-focus-return";
import type { RoomingHotel } from "../api/operations.api";
import { CreateHotelDialog, EditHotelDialog } from "./rooming-hotel-dialog";

describe("rooming hotel dialogs", () => {
  it("isolates the hotel form, contains programmatic focus and returns to its opener", async () => {
    function Host() {
      const [open, setOpen] = useState(false);
      return <><ModalFocusTracker /><button onClick={() => setOpen(true)}>Open hotel</button>
        {open && <CreateHotelDialog isLoading={false} onCreate={vi.fn()} onClose={() => setOpen(false)} />}</>;
    }
    render(<Host />);
    const opener = screen.getByRole("button", { name: "Open hotel" });
    await userEvent.click(opener);
    const dialog = screen.getByRole("dialog", { name: "Add hotel stay" });
    expect(opener).toHaveAttribute("inert");
    opener.focus();
    expect(dialog.contains(document.activeElement)).toBe(true);
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).not.toHaveAttribute("inert");
    expect(opener).toHaveFocus();
  });

  it("submits trimmed hotel details and preserves the checkout minimum", async () => {
    const create = vi.fn().mockResolvedValue(undefined);
    render(<CreateHotelDialog isLoading={false} onCreate={create} onClose={vi.fn()} />);
    await userEvent.type(screen.getByRole("textbox", { name: "Hotel name" }), "  Synthetic hotel  ");
    await userEvent.type(screen.getByRole("textbox", { name: "City" }), "  Bangkok  ");
    fireEvent.change(screen.getByLabelText("Check-in"), { target: { value: "2026-11-02" } });
    fireEvent.change(screen.getByLabelText("Check-out"), { target: { value: "2026-11-06" } });
    expect(screen.getByLabelText("Check-out")).toHaveAttribute("min", "2026-11-02");
    await userEvent.click(screen.getByRole("button", { name: "Add hotel" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith({
      hotel_name: "Synthetic hotel", city: "Bangkok", check_in_date: "2026-11-02", check_out_date: "2026-11-06",
    }));
  });

  it("loads existing values and keeps a rejected edit available for retry", async () => {
    const hotel: RoomingHotel = {
      id: "synthetic-hotel", hotel_name: "Existing hotel", city: "Bangkok",
      check_in_date: "2026-11-02", check_out_date: "2026-11-06",
      rooms: [], unallocated_passengers: [], selected_passengers: [], selected_passenger_count: 0,
      allocation_priority_fields: [], allocation_revision: 1, allocation_is_current: false,
      allocated_passenger_count: 0, capacity_total: 0,
    };
    const save = vi.fn().mockRejectedValueOnce(new Error("Hotel changed. Refresh and retry.")).mockResolvedValue(undefined);
    render(<EditHotelDialog hotel={hotel} isLoading={false} onSave={save} onClose={vi.fn()} />);
    expect(screen.getByRole("textbox", { name: "Hotel name" })).toHaveValue(hotel.hotel_name);
    await userEvent.clear(screen.getByRole("textbox", { name: "City" }));
    await userEvent.click(screen.getByRole("button", { name: "Save hotel" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Hotel changed. Refresh and retry."));
    expect(screen.getByRole("dialog")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Save hotel" }));
    expect(save).toHaveBeenLastCalledWith({
      hotel_name: hotel.hotel_name, city: undefined, check_in_date: hotel.check_in_date, check_out_date: hotel.check_out_date,
    });
    expect(save).toHaveBeenCalledTimes(2);
  });

  it("keeps a pending mutation open through Escape, close and backdrop actions", async () => {
    const close = vi.fn();
    render(<CreateHotelDialog isLoading onCreate={vi.fn()} onClose={close} />);
    expect(screen.getByRole("button", { name: "Close hotel dialog" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    fireEvent.mouseDown(screen.getByRole("presentation"));
    expect(close).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeVisible();
  });
});
