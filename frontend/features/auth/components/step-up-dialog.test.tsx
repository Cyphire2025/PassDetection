import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { StepUpDialog } from "./step-up-dialog";
import { requestAuthenticationStepUp } from "../services/step-up-coordinator";

vi.mock("../api/auth.api", () => ({
  authApi: { stepUp: vi.fn() },
}));

describe("StepUpDialog keyboard boundary", () => {
  it("focuses the code, traps both tab directions, closes with Escape, and restores focus", async () => {
    const user = userEvent.setup();
    render(
      <>
        <button type="button">Sensitive action</button>
        <StepUpDialog />
      </>,
    );
    const trigger = screen.getByRole("button", { name: "Sensitive action" });
    trigger.focus();
    const pending = requestAuthenticationStepUp().catch((error: unknown) => error);

    const dialog = await screen.findByRole("dialog", { name: "Confirm this sensitive action" });
    const code = screen.getByRole("textbox", { name: "Verification code" });
    await waitFor(() => expect(code).toHaveFocus());

    const close = screen.getByRole("button", { name: "Cancel identity confirmation" });
    const cancel = screen.getByRole("button", { name: /^Cancel$/ });
    close.focus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(cancel).toHaveFocus();
    await user.keyboard("{Tab}");
    expect(close).toHaveFocus();

    await user.keyboard("{Escape}");
    await waitFor(() => expect(dialog).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
    await expect(pending).resolves.toMatchObject({
      code: "STEP_UP_CANCELLED",
      message: "Identity confirmation was cancelled.",
    });
  });
});
