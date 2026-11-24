import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";
import { PassportGroupSelectedActions } from "./passport-group-selected-actions";
import { usePassportGroupMenus } from "./use-passport-group-menus";

function Harness({ exported = vi.fn() }: { exported?: ReturnType<typeof vi.fn> }) {
  const menu = usePassportGroupMenus();
  const props = {
    ...menu, selectedPassports: ["selected-one", "selected-two"], documentFollowUp: { canManage: false },
    canEditDisplayName: false, canBulkStaffApprove: false, canPermanentlyDelete: false,
    exportSelected: { isPending: false, mutate: exported }, exportSelectedImages: { isPending: false },
    handleSelectedPassportDownload: vi.fn(), resetBulkSelection: vi.fn(), bulkDelete: { isPending: false },
  } as unknown as ComponentProps<typeof PassportGroupSelectedActions>;
  return <><PassportGroupSelectedActions {...props} /><button type="button">Outside action</button></>;
}

const trigger = () => screen.getByRole("button", { name: "Open bulk actions for 2 selected submissions" });

describe("group selection portal boundary", () => {
  it("keeps pointer actions inside the portal live and sends the exact selection once", async () => {
    const user = userEvent.setup(), exported = vi.fn();
    render(<Harness exported={exported} />);
    await user.click(trigger());
    const popup = screen.getByRole("group", { name: "Bulk submission actions" });
    expect(popup.parentElement).toBe(document.body);
    const button = screen.getByRole("button", { name: "Export Excel (2)" });
    expect(button).toHaveFocus();
    await user.click(button);
    expect(exported).toHaveBeenCalledExactlyOnceWith(["selected-one", "selected-two"]);
    expect(screen.queryByRole("group", { name: "Bulk submission actions" })).not.toBeInTheDocument();
  });

  it("toggles from its trigger, restores focus on Escape and closes on outside pointer", async () => {
    const user = userEvent.setup(); render(<Harness />);
    await user.click(trigger());
    await user.click(trigger());
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    await user.click(trigger());
    await user.keyboard("{Escape}");
    expect(trigger()).toHaveFocus();
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    await user.click(trigger());
    await user.click(screen.getByRole("button", { name: "Outside action" }));
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
  });

  it("allows internal menu scrolling and closes when the underlying viewport changes", async () => {
    const user = userEvent.setup(); render(<Harness />);
    await user.click(trigger());
    fireEvent.scroll(screen.getByRole("group", { name: "Bulk submission actions" }));
    expect(trigger()).toHaveAttribute("aria-expanded", "true");
    fireEvent.scroll(window);
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
    await user.click(trigger());
    fireEvent.resize(window);
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
  });
});
