import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CreateUploadLinkModal } from "./create-upload-link-modal";

const { createLink } = vi.hoisted(() => ({ createLink: vi.fn() }));

vi.mock("../hooks/use-upload-links", () => ({
  useCreateUploadLink: () => ({ mutateAsync: createLink, isPending: false }),
}));
vi.mock("@/stores/auth.store", () => ({
  selectUserRole: vi.fn(),
  useAuthStore: () => "agency_staff",
}));
vi.mock("@/lib/utils/role-access", () => ({ canAccessWhatsAppBroadcasts: () => false }));
vi.mock("@/lib/utils/public-url", () => ({
  getPassportUploadTargets: () => [{ key: "web", label: "Client", description: "Upload documents", url: "https://example.test/upload/test-token" }],
}));

beforeEach(() => {
  createLink.mockReset().mockResolvedValue({ token: "test-token" });
});

function fillGroupDetails() {
  fireEvent.change(screen.getByRole("textbox", { name: "Group Name" }), { target: { value: "Autumn Group" } });
  fireEvent.change(screen.getByRole("textbox", { name: "Destination" }), { target: { value: "Dubai" } });
  fireEvent.change(screen.getByLabelText(/Travel\/Departure Date/), { target: { value: "2026-10-01" } });
  fireEvent.change(screen.getByLabelText(/Return Date/), { target: { value: "2026-10-08" } });
}

describe("create upload link", () => {
  it("submits renamed optional fields and selected passport pages using the settings shown in the dialog", async () => {
    const user = userEvent.setup();
    render(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    expect(screen.queryByRole("textbox", { name: "Notes" })).not.toBeInTheDocument();
    fillGroupDetails();
    await user.click(screen.getByRole("switch", { name: "Enable Visa Photo" }));
    await user.click(screen.getByRole("switch", { name: "Disable Live Photo Capture" }));
    await user.click(screen.getByRole("checkbox", { name: "Make Visa Photo compulsory" }));
    await user.click(screen.getByText(/Pages to request/));
    await user.click(screen.getByRole("checkbox", { name: /^Passport Front Cover/ }));
    await user.click(screen.getByRole("switch", { name: "Enable Agent/Employee Code" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Code field label" }), { target: { value: "Producer Code" } });
    await user.click(screen.getByRole("checkbox", { name: "Make Agent/Employee Code compulsory" }));
    await user.click(screen.getByRole("button", { name: "Generate Links" }));

    await waitFor(() => expect(createLink).toHaveBeenCalledTimes(1));
    expect(createLink).toHaveBeenCalledWith(expect.objectContaining({
      name: "Autumn Group",
      require_selfie: true,
      agent_employee_code_enabled: true,
      upload_configuration: expect.objectContaining({
        visa_photo_live_capture: false,
        visa_photo_upload: true,
        visa_photo_required: false,
        passport_upload_pages: ["cover", "front", "back"],
        agent_employee_code_label: "Producer Code",
        required_fields: { agent_employee_code: false },
      }),
    }));
    expect(createLink.mock.calls[0][0]).not.toHaveProperty("notes");
    expect(await screen.findByRole("heading", { name: "Links Generated" })).toBeInTheDocument();
  });

  it("blocks creation and explains an enabled section with both methods disabled", async () => {
    const user = userEvent.setup();
    render(<CreateUploadLinkModal isOpen onClose={vi.fn()} />);
    fillGroupDetails();
    await user.click(screen.getByRole("switch", { name: "Disable Live Passport Scan" }));
    await user.click(screen.getByRole("switch", { name: "Disable Passport Document Upload" }));
    await user.click(screen.getByRole("button", { name: "Generate Links" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enable at least one method for Passport.");
    expect(createLink).not.toHaveBeenCalled();
  });
});
