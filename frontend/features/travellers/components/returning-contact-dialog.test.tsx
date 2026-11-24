import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { returningApi } from "../api/returning.api";
import { ReturningContactDialog } from "./returning-contact-dialog";
vi.mock("../api/returning.api", () => ({ returningApi: { requestContact: vi.fn(), verifyContact: vi.fn() } }));
beforeEach(() => { vi.clearAllMocks(); vi.mocked(returningApi.requestContact).mockResolvedValue({ expires_in_seconds: 300, resend_after_seconds: 30 }); vi.mocked(returningApi.verifyContact).mockResolvedValue({ stage: "review" }); });
afterEach(cleanup);
function request() { fireEvent.change(screen.getByLabelText("New WhatsApp number", { exact: false }), { target: { value: "9888888888" } }); fireEvent.click(screen.getByRole("button", { name: "Send WhatsApp code" })); }
async function code() { fireEvent.change(await screen.findByLabelText("WhatsApp verification code", { exact: false }), { target: { value: "123456" } }); fireEvent.click(screen.getByRole("checkbox", { name: /Use this verified number/ })); }
it("admits one OTP request, retains its draft scope and denies pending close/Escape", async () => {
  let finish!: (value: { expires_in_seconds: number; resend_after_seconds: number }) => void;
  vi.mocked(returningApi.requestContact).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const onClose = vi.fn(); render(<ReturningContactDialog draftId="synthetic-draft" onClose={onClose} onSaved={vi.fn()} />);
  fireEvent.change(screen.getByLabelText("New WhatsApp number", { exact: false }), { target: { value: "9888888888" } });
  const form = screen.getByRole("button", { name: "Send WhatsApp code" }).closest("form")!;
  fireEvent.submit(form); fireEvent.submit(form); expect(returningApi.requestContact).toHaveBeenCalledOnce();
  expect(returningApi.requestContact).toHaveBeenCalledWith("+919888888888", "synthetic-draft", expect.any(AbortSignal));
  fireEvent.click(screen.getByRole("button", { name: "Cancel" })); fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" }); expect(onClose).not.toHaveBeenCalled();
  await act(async () => { finish({ expires_in_seconds: 300, resend_after_seconds: 30 }); }); expect(await screen.findByLabelText("WhatsApp verification code", { exact: false })).toBeVisible();
});
it("does not continue a verified contact after the dialog unmounts", async () => {
  let finish!: () => void; vi.mocked(returningApi.verifyContact).mockReturnValue(new Promise(resolve => { finish = () => resolve({ stage: "review" }); }));
  const onSaved = vi.fn(), view = render(<ReturningContactDialog draftId="synthetic-draft" onClose={vi.fn()} onSaved={onSaved} />); request(); await code();
  fireEvent.click(screen.getByRole("button", { name: "Verify for this draft" })); const signal = vi.mocked(returningApi.verifyContact).mock.calls[0][2]!; view.unmount(); expect(signal.aborted).toBe(true);
  await act(async () => { finish(); }); expect(onSaved).not.toHaveBeenCalled();
});
it("retries a failed saved callback without consuming another OTP verification", async () => {
  const onSaved = vi.fn().mockImplementationOnce(() => { throw new Error("Synthetic refresh failure"); });
  render(<ReturningContactDialog draftId="synthetic-draft" onClose={vi.fn()} onSaved={onSaved} />); request(); await code();
  fireEvent.click(screen.getByRole("button", { name: "Verify for this draft" })); await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Use verified contact" })); await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(2)); expect(returningApi.verifyContact).toHaveBeenCalledOnce();
});
