import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PassportSubmission } from "@/types/passport.types";
import type { ContactVerification } from "../components/upload-contact-verification";
import { useUploadContactVerification } from "./use-upload-contact-verification";

const proof: ContactVerification = {
  id: "synthetic-proof", sessionId: "synthetic-session", email: "traveller@example.com",
  phone: "+919999999999", expiresAt: 2000,
};

function harness() {
  return renderHook(() => useUploadContactVerification({
    token: "synthetic-token", step: "REVIEW",
    submission: { id: "saved-traveller" } as PassportSubmission,
    sessionId: proof.sessionId, name: "Synthetic Traveller", email: proof.email, phone: proof.phone,
    familyMembers: [], onSingleContact: vi.fn(), onFamilyContact: vi.fn(), onBack: vi.fn(),
  }));
}

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(1000); });
afterEach(() => { vi.restoreAllMocks(); vi.useRealTimers(); });

describe("upload contact proof expiry", () => {
  it("accepts a matching proof only until its exact expiry boundary", () => {
    const { result } = harness();
    act(() => result.current.page!.props.onVerified(proof));
    expect(result.current.page).toBeNull();
    act(() => vi.advanceTimersByTime(999));
    expect(result.current.page).toBeNull();
    act(() => vi.advanceTimersByTime(1));
    expect(result.current.page).not.toBeNull();
    expect(result.current.getProof("saved-traveller", proof.sessionId, proof.email, proof.phone)).toBeNull();
  });

  it("does not lose expiry when the timer fires before the boundary and the effect runs after it", () => {
    const timer = vi.spyOn(window, "setTimeout");
    const { result } = harness();
    act(() => result.current.page!.props.onVerified(proof));
    const callback = timer.mock.calls.at(-1)![0];
    expect(typeof callback).toBe("function");
    vi.clearAllTimers();
    // The callback reads just before expiry; React's render/effect runs after it.
    vi.spyOn(Date, "now").mockReturnValueOnce(1999).mockReturnValue(2000);
    act(() => { if (typeof callback === "function") callback(); });
    expect(vi.getTimerCount()).toBe(1);
    act(() => vi.runOnlyPendingTimers());
    expect(result.current.page).not.toBeNull();
    expect(result.current.getProof("saved-traveller", proof.sessionId, proof.email, proof.phone)).toBeNull();
  });

  it("rejects an expired proof at submission time even when the browser delayed its timer", () => {
    const { result } = harness();
    act(() => result.current.page!.props.onVerified(proof));
    vi.setSystemTime(2000); // No timer callback or React render has run.
    expect(result.current.getProof("saved-traveller", proof.sessionId, proof.email, proof.phone)).toBeNull();
  });

  it("rearms repeated early callbacks even when the observed clock value is unchanged", () => {
    const timer = vi.spyOn(window, "setTimeout");
    const { result } = harness();
    act(() => result.current.page!.props.onVerified(proof));
    const clock = vi.spyOn(Date, "now").mockReturnValue(1999);
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const callback = timer.mock.calls.at(-1)![0];
      vi.clearAllTimers();
      act(() => { if (typeof callback === "function") callback(); });
      expect(result.current.page).toBeNull();
      expect(vi.getTimerCount()).toBe(1);
    }
    clock.mockReturnValue(2000);
    act(() => vi.runOnlyPendingTimers());
    expect(result.current.page).not.toBeNull();
  });

  it("does not accept a proof whose expiry passed before its state update rendered", () => {
    const { result } = harness();
    vi.setSystemTime(2000);
    act(() => result.current.page!.props.onVerified(proof));
    act(() => vi.runOnlyPendingTimers());
    expect(result.current.page).not.toBeNull();
    expect(result.current.getProof("saved-traveller", proof.sessionId, proof.email, proof.phone)).toBeNull();
  });
});
