import { useState } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { UploadContactVerification, type ContactVerification } from "./upload-contact-verification";

const mocks = vi.hoisted(() => ({ request: vi.fn(), verify: vi.fn(), verified: vi.fn() }));
vi.mock("../api/upload.api", () => ({ uploadApi: { requestContactOtp: mocks.request, verifyContactOtp: mocks.verify } }));

function Harness() {
  const [contact, setContact] = useState({ email: "", phone: "" });
  const [proof, setProof] = useState<ContactVerification | null>(null);
  return <UploadContactVerification token="group-token" submissionId="draft-1" sessionId="session-1" name="Asha" {...contact}
    verification={proof} onContactChange={(email, phone) => { setContact({ email, phone }); setProof(null); }}
    onVerified={(value) => { mocks.verified(value); setProof(value); }} onBack={() => undefined} />;
}

function enterContact(phone = "9999999999") {
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: "asha@example.com" } });
  fireEvent.change(screen.getByLabelText("WhatsApp active number"), { target: { value: phone } });
}

async function sendCode() {
  enterContact();
  fireEvent.click(screen.getByRole("button", { name: "Send OTP" }));
  await screen.findByLabelText("WhatsApp verification code");
}

beforeEach(() => {
  vi.resetAllMocks();
  mocks.request.mockResolvedValue({ challenge_id: "challenge-1", expires_in_seconds: 300, resend_after_seconds: 60 });
  mocks.verify.mockResolvedValue({ phone_verification_id: "proof-1", phone_number: "+919999999999", expires_in_seconds: 3600 });
});
afterEach(() => vi.useRealTimers());

describe("traveller contact verification", () => {
  it("requires email and only offers sending for complete phone numbers", () => {
    render(<Harness />);
    expect(screen.getByLabelText("Email")).toBeRequired();
    expect(screen.getByLabelText("WhatsApp active number")).toBeRequired();
    expect(screen.queryByRole("button", { name: "Send OTP" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("WhatsApp active number"), { target: { value: "+91999999" } });
    expect(screen.queryByRole("button", { name: "Send OTP" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("WhatsApp active number"), { target: { value: "9999999999" } });
    expect(screen.getByRole("button", { name: "Send OTP" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "invalid" } });
    expect(screen.getByRole("button", { name: "Send OTP" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "asha@example.com" } });
    expect(screen.getByRole("button", { name: "Send OTP" })).toBeEnabled();
  });

  it("sends once on repeated clicks and ignores a send response after the contact changes", async () => {
    let resolve!: (value: unknown) => void;
    mocks.request.mockImplementation(() => new Promise((done) => { resolve = done; }));
    render(<Harness />);
    enterContact();
    const send = screen.getByRole("button", { name: "Send OTP" });
    fireEvent.click(send);
    fireEvent.click(send);
    expect(mocks.request).toHaveBeenCalledTimes(1);
    expect(mocks.request).toHaveBeenCalledWith("draft-1", "session-1", { group_token: "group-token", phone_number: "+919999999999", email: "asha@example.com" }, expect.any(AbortSignal));
    fireEvent.change(screen.getByLabelText("WhatsApp active number"), { target: { value: "8888888888" } });
    await act(async () => resolve({ challenge_id: "stale", expires_in_seconds: 300, resend_after_seconds: 60 }));
    expect(screen.queryByLabelText("WhatsApp verification code")).not.toBeInTheDocument();
    expect(mocks.verified).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Send OTP" })).toBeEnabled();
  });

  it("ignores a successful verify response after editing email", async () => {
    let resolve!: (value: unknown) => void;
    mocks.verify.mockImplementation(() => new Promise((done) => { resolve = done; }));
    render(<Harness />);
    await sendCode();
    fireEvent.change(screen.getByLabelText("WhatsApp verification code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify OTP and continue" }));
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "changed@example.com" } });
    await act(async () => resolve({ phone_verification_id: "stale", phone_number: "+919999999999", expires_in_seconds: 3600 }));
    expect(mocks.verified).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("WhatsApp verification code")).not.toBeInTheDocument();
  });

  it("reports invalid codes and can verify the corrected code with the same challenge", async () => {
    mocks.verify.mockRejectedValueOnce({ code: "OTP_INVALID", message: "Incorrect verification code." });
    render(<Harness />);
    await sendCode();
    fireEvent.change(screen.getByLabelText("WhatsApp verification code"), { target: { value: "111111" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify OTP and continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect verification code.");
    expect(mocks.verified).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText("WhatsApp verification code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Verify OTP and continue" }));
    await waitFor(() => expect(mocks.verified).toHaveBeenCalledWith(expect.objectContaining({ id: "proof-1", email: "asha@example.com", phone: "+919999999999", sessionId: "session-1" })));
    expect(mocks.verify).toHaveBeenLastCalledWith("draft-1", "session-1", { group_token: "group-token", challenge_id: "challenge-1", code: "123456" }, expect.any(AbortSignal));
    fireEvent.change(screen.getByLabelText("WhatsApp active number"), { target: { value: "8888888888" } });
    expect(screen.queryByRole("button", { name: "Continue to your details" })).not.toBeInTheDocument();
  });

  it("expires codes, enforces resend cooldown and replaces the challenge on resend", async () => {
    vi.useFakeTimers();
    mocks.request.mockResolvedValue({ challenge_id: "challenge-1", expires_in_seconds: 5, resend_after_seconds: 10 });
    render(<Harness />);
    enterContact();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Send OTP" })));
    expect(screen.getByRole("button", { name: "Resend OTP in 10s" })).toBeDisabled();
    await act(async () => vi.advanceTimersByTime(5000));
    expect(screen.getByRole("status")).toHaveTextContent("This code has expired");
    expect(screen.getByRole("button", { name: "Verify OTP and continue" })).toBeDisabled();
    await act(async () => vi.advanceTimersByTime(5000));
    mocks.request.mockResolvedValue({ challenge_id: "challenge-2", expires_in_seconds: 300, resend_after_seconds: 60 });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Resend OTP" })));
    fireEvent.change(screen.getByLabelText("WhatsApp verification code"), { target: { value: "123456" } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Verify OTP and continue" })));
    expect(mocks.verify).toHaveBeenCalledWith("draft-1", "session-1", expect.objectContaining({ challenge_id: "challenge-2" }), expect.any(AbortSignal));
  });

  it("adopts the server cooldown after a send fails", async () => {
    mocks.request.mockRejectedValue({ code: "OTP_UNAVAILABLE", message: "Please try again shortly.", retryAfterMs: 60000 });
    render(<Harness />);
    enterContact();
    fireEvent.click(screen.getByRole("button", { name: "Send OTP" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Please try again shortly.");
    expect(screen.getByRole("button", { name: /Resend OTP in/ })).toBeDisabled();
  });
});
