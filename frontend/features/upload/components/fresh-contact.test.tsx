import { useState } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FreshDraft, FreshPayload } from "../api/fresh-draft.api";
import { useFreshDraft } from "../hooks/use-fresh-draft";
import { FreshContact } from "./fresh-contact";
import type { FreshProof } from "../hooks/use-fresh-contact";

const api = vi.hoisted(() => ({ start: vi.fn(), read: vi.fn(), save: vi.fn(), requestCode: vi.fn(), verifyCode: vi.fn() }));
vi.mock("../api/fresh-draft.api", () => ({ freshDraftApi: () => api }));
const initial = { acquisition_mode: "file" as const, submission_mode: "single" as const };
const member = { sessionId: "synthetic-member", submissionKey: "synthetic-final-key", completed: false };
let server: FreshDraft;
const snapshot = () => structuredClone(server);
function Harness() {
  const state = useFreshDraft("synthetic-trip", member, initial);
  const [proof, setProof] = useState<FreshProof | null>(null);
  if (!state.payload) return <p role="status">Loading synthetic private draft</p>;
  return <>
    {state.error && <p role="alert">{state.error}</p>}
    <FreshContact state={state} onProof={setProof} />
    <output data-testid="contact-proof">{proof?.id ?? "unverified"}</output>
  </>;
}
async function contact() {
  render(<Harness />);
  await screen.findByLabelText("Email");
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "synthetic@example.test" } });
  fireEvent.change(screen.getByLabelText("WhatsApp number"), { target: { value: "9999999999" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "Verify WhatsApp number" })).toBeEnabled());
}
async function request() {
  await contact();
  fireEvent.click(screen.getByRole("button", { name: "Verify WhatsApp number" }));
  await screen.findByLabelText("Verification code");
}
beforeEach(() => {
  vi.resetAllMocks();
  server = { id: "synthetic-draft", revision: 1, expires_at: "2099-01-01", status: "active", collection: initial,
    verified_phone: null, phone_verification_id: null, phone_verification_expires_at: null, passport_fields: {},
    current_details: {}, custom_answers: {}, custom_detail_answers: {}, documents: [], extracted_fields: {}, extraction_status: "none" };
  api.start.mockImplementation(async () => snapshot());
  api.read.mockImplementation(async () => snapshot());
  api.save.mockImplementation(async (payload: FreshPayload) => { server = { ...server, ...payload, revision: server.revision + 1 }; return snapshot(); });
  api.requestCode.mockResolvedValue({ challenge_id: "challenge-1", expires_in_seconds: 300, resend_after_seconds: 60 });
  api.verifyCode.mockImplementation(async () => {
    server = { ...server, revision: server.revision + 1, phone_verification_id: "proof-1", phone_verification_expires_at: "2099-01-01" };
    return { phone_verification_id: "proof-1", phone_number: "+919999999999", expires_in_seconds: 3600 };
  });
});
afterEach(() => vi.useRealTimers());

describe("current Fresh contact verification obligations", () => {
  it("requires valid email and complete phone input before requesting a code", async () => {
    render(<Harness />);
    await screen.findByLabelText("Email");
    expect(screen.getByLabelText("Email")).toBeRequired();
    expect(screen.getByLabelText("WhatsApp number")).toBeRequired();
    const send = screen.getByRole("button", { name: "Verify WhatsApp number" });
    expect(send).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "invalid" } });
    fireEvent.change(screen.getByLabelText("WhatsApp number"), { target: { value: "+91999999" } });
    expect(send).toBeDisabled();
    fireEvent.change(screen.getByLabelText("WhatsApp number"), { target: { value: "9999999999" } });
    expect(send).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "synthetic@example.test" } });
    expect(send).toBeEnabled();
    expect(api.requestCode).not.toHaveBeenCalled();
  });

  it("suppresses repeated sends and ignores a challenge for edited contact details", async () => {
    const deferred = Promise.withResolvers<{ challenge_id: string; expires_in_seconds: number; resend_after_seconds: number }>();
    api.requestCode.mockReturnValue(deferred.promise);
    await contact();
    const send = screen.getByRole("button", { name: "Verify WhatsApp number" });
    fireEvent.click(send); fireEvent.click(send);
    await waitFor(() => expect(api.requestCode).toHaveBeenCalledOnce());
    fireEvent.change(screen.getByLabelText("WhatsApp number"), { target: { value: "8888888888" } });
    await act(async () => deferred.resolve({ challenge_id: "stale", expires_in_seconds: 300, resend_after_seconds: 0 }));
    expect(screen.queryByLabelText("Verification code")).not.toBeInTheDocument();
    expect(screen.getByTestId("contact-proof")).toHaveTextContent("unverified");
    expect(api.requestCode).toHaveBeenCalledExactlyOnceWith("synthetic@example.test", "+919999999999", expect.any(AbortSignal));
  });

  it("does not accept verification for contact details edited during the request", async () => {
    const deferred = Promise.withResolvers<{ phone_verification_id: string; phone_number: string; expires_in_seconds: number }>();
    api.verifyCode.mockReturnValue(deferred.promise);
    await request();
    fireEvent.change(screen.getByLabelText("Verification code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm code" }));
    await waitFor(() => expect(api.verifyCode).toHaveBeenCalledOnce());
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "changed@example.test" } });
    await act(async () => deferred.resolve({ phone_verification_id: "stale", phone_number: "+919999999999", expires_in_seconds: 3600 }));
    await waitFor(() => expect(api.read).toHaveBeenCalled());
    expect(screen.getByLabelText("Email")).toHaveValue("changed@example.test");
    expect(screen.getByTestId("contact-proof")).toHaveTextContent("unverified");
  });

  it("allows a corrected code on the same challenge only after authoritative revision refresh", async () => {
    api.verifyCode.mockRejectedValueOnce({ code: "OTP_INVALID", message: "Incorrect verification code." });
    await request();
    expect(api.read).toHaveBeenCalledOnce();
    api.read.mockClear();
    fireEvent.change(screen.getByLabelText("Verification code"), { target: { value: "111111" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm code" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect verification code");
    expect(screen.getByTestId("contact-proof")).toHaveTextContent("unverified");
    fireEvent.change(screen.getByLabelText("Verification code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm code" }));
    await waitFor(() => expect(screen.getByTestId("contact-proof")).toHaveTextContent("proof-1"));
    expect(api.verifyCode).toHaveBeenLastCalledWith("challenge-1", "123456", expect.any(AbortSignal));
    expect(api.read).toHaveBeenCalledOnce();
    fireEvent.change(screen.getByLabelText("WhatsApp number"), { target: { value: "8888888888" } });
    expect(screen.getByTestId("contact-proof")).toHaveTextContent("unverified");
  });

  it("expires challenges, enforces successful resend cooldown and uses the replacement challenge", async () => {
    api.requestCode.mockResolvedValueOnce({ challenge_id: "short", expires_in_seconds: 5, resend_after_seconds: 10 });
    vi.useFakeTimers();
    await act(async () => { render(<Harness />); });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "synthetic@example.test" } });
    fireEvent.change(screen.getByLabelText("WhatsApp number"), { target: { value: "9999999999" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Verify WhatsApp number" })));
    expect(screen.getByRole("button", { name: "Resend in 10s" })).toBeDisabled();
    await act(async () => vi.advanceTimersByTime(5000));
    fireEvent.change(screen.getByLabelText("Verification code"), { target: { value: "123456" } });
    expect(screen.getByRole("button", { name: "Confirm code" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("expired");
    await act(async () => vi.advanceTimersByTime(5000));
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Resend code" })));
    fireEvent.change(screen.getByLabelText("Verification code"), { target: { value: "123456" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Confirm code" })));
    expect(api.verifyCode).toHaveBeenCalledWith("challenge-1", "123456", expect.any(AbortSignal));
  });

  it("honors a failed-send server retry interval without allowing immediate repeat requests", async () => {
    api.requestCode.mockRejectedValue({ code: "OTP_UNAVAILABLE", message: "Please try again shortly.", retryAfterMs: 60000 });
    await contact();
    fireEvent.click(screen.getByRole("button", { name: "Verify WhatsApp number" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Please try again shortly");
    expect(screen.getByRole("button", { name: /Resend in/ })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /Resend in/ }));
    expect(api.requestCode).toHaveBeenCalledOnce();
  });

  it("drops a queued old contact before sending and preserves the replacement contact request", async () => {
    const gate = Promise.withResolvers<void>();
    const save = api.save.getMockImplementation()!;
    api.save.mockImplementationOnce(async (...args) => { await gate.promise; return save(...args); });
    await contact();
    const send = screen.getByRole("button", { name: "Verify WhatsApp number" });
    fireEvent.click(send);
    await waitFor(() => expect(api.save).toHaveBeenCalledOnce());
    // Flushing the previous contact is not a foreground OTP request yet.
    expect(send).toBeEnabled();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "replacement@example.test" } });
    fireEvent.click(send);
    await act(async () => gate.resolve());
    await screen.findByLabelText("Verification code");
    expect(api.requestCode).toHaveBeenCalledExactlyOnceWith("replacement@example.test", "+919999999999", expect.any(AbortSignal));
  });

  it("does not impose an old contact's late failed-send cooldown on its replacement", async () => {
    const gate = Promise.withResolvers<never>();
    api.requestCode.mockReturnValueOnce(gate.promise);
    await contact();
    fireEvent.click(screen.getByRole("button", { name: "Verify WhatsApp number" }));
    await waitFor(() => expect(api.requestCode).toHaveBeenCalledOnce());
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "replacement@example.test" } });
    await act(async () => gate.reject({ code: "OTP_UNAVAILABLE", message: "Old contact request failed", retryAfterMs: 60000 }));
    const send = screen.getByRole("button", { name: "Verify WhatsApp number" });
    expect(send).toBeEnabled();
    fireEvent.click(send);
    await screen.findByLabelText("Verification code");
    expect(api.requestCode).toHaveBeenCalledTimes(2);
    expect(api.requestCode).toHaveBeenLastCalledWith("replacement@example.test", "+919999999999", expect.any(AbortSignal));
  });
});
