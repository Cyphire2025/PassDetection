import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ManageBroadcastsDialog } from "./group-whatsapp-dialogs";

const { mutate } = vi.hoisted(() => ({ mutate: vi.fn() }));
vi.mock("../hooks/use-upload-links", () => ({ useUpdateGroupWhatsAppLinks: () => ({ mutate, isPending: false }) }));
vi.mock("./whatsapp-broadcast-selector", () => ({ WhatsAppBroadcastSelector: ({ onChange }: { onChange: (ids: string[]) => void }) => <button onClick={() => onChange([])}>Remove selection</button> }));
beforeEach(() => mutate.mockReset());

describe("broadcast linking dialog orchestration", () => {
  it("requires explicit unlink confirmation and Escape leaves the outer editor intact", async () => {
    const onClose = vi.fn();
    render(<ManageBroadcastsDialog groupId="group" initialBroadcasts={[{ id: "broadcast", name: "Synthetic", recipient_count: 1, created_at: "2026-09-26T00:00:00Z", updated_at: "2026-09-26T00:00:00Z", matching_field_keys: ["phone"] }]} onClose={onClose} />);
    await userEvent.click(screen.getByRole("button", { name: "Remove selection" }));
    const save = screen.getByRole("button", { name: "Save linked broadcasts" });
    await userEvent.click(save);
    expect(mutate).not.toHaveBeenCalled();
    expect(within(screen.getByRole("dialog", { name: "Unlink every WhatsApp broadcast?" })).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(onClose).not.toHaveBeenCalled(); expect(save).toHaveFocus();
    await userEvent.click(save);
    await userEvent.click(screen.getByRole("button", { name: "Unlink all broadcasts" }));
    expect(mutate).toHaveBeenCalledExactlyOnceWith({ whatsappBroadcastGroupIds: [], matchingFieldsByBroadcast: {} }, expect.objectContaining({ onSuccess: onClose }));
  });
});
