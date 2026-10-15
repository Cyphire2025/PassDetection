import type { ComponentType } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { draftResumeText, readDraftResume, saveDraftResume, saveFreshResume, type FreshResume } from "@/features/travellers/services/draft-resume";
import { TravellerPortal } from "./traveller-portal";

const memberRender = vi.hoisted(() => vi.fn());
vi.mock("@/features/passports/hooks/use-upload-links", () => ({ useUploadLinkByToken: () => ({ data: { name: "Synthetic trip" }, isLoading: false, error: null }) }));
vi.mock("@/features/travellers/hooks/use-returning-capabilities", () => ({ useReturningCapabilities: vi.fn() }));
vi.mock("next/dynamic", async () => {
  const { lazy, Suspense } = await import("react");
  return { default: (load: () => Promise<ComponentType<Record<string, unknown>>>) => {
    const Component = lazy(async () => ({ default: await load() }));
    return function Dynamic(props: Record<string, unknown>) { return <Suspense fallback={null}><Component {...props} /></Suspense>; };
  } };
});
vi.mock("./fresh-member", () => ({ FreshMember: (props: { resume: FreshResume; onBack: () => void; onComplete: () => void }) => {
  memberRender(props.resume);
  return <><output aria-label="Active traveller">{JSON.stringify(props.resume)}</output><button onClick={props.onBack}>Back to start</button><button onClick={props.onComplete}>Complete member</button></>;
} }));
vi.mock("@/features/travellers/components/returning-offer", () => ({ ReturningTravellerOffer: ({ onFresh }: { onFresh: () => void }) => <button onClick={onFresh}>Continue as a new traveller</button> }));
vi.mock("@/features/travellers/components/returning-resume", () => ({ ReturningResume: () => <p>Saved returning review</p> }));

const token = "synthetic-entry";
function existing(mode: "single" | "family") {
  const value: FreshResume = { mode, familyGroupId: "saved-family", active: mode === "family" ? 1 : 0,
    members: Array.from({ length: mode === "family" ? 3 : 1 }, (_, index) => ({ sessionId: `saved-${index}`, submissionKey: `submit-${index}`, completed: mode === "family" && index === 0 })) };
  saveFreshResume(token, value);
  return value;
}
async function openFresh() {
  fireEvent.click(screen.getByRole("button", { name: /^New traveller/ }));
  await screen.findByRole("heading", { name: "Who are you submitting for?" });
}
function active() { return JSON.parse(screen.getByLabelText("Active traveller").textContent!) as FreshResume; }
beforeEach(() => { localStorage.clear(); memberRender.mockClear(); });

describe("traveller entry and explicit resume", () => {
  it("keeps the landing choices separate, then starts Only me only after Continue", async () => {
    render(<TravellerPortal token={token} />);
    expect(screen.queryByRole("button", { name: "Only me" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Family" })).not.toBeInTheDocument();
    await openFresh();
    expect(screen.getByRole("button", { name: "Only me" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Family" })).toBeInTheDocument();
    expect(memberRender).not.toHaveBeenCalled(); expect(readDraftResume(token)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByLabelText("Active traveller");
    expect(active().mode).toBe("single"); expect(active().members).toHaveLength(1);
  });

  it.each(["single", "family"] as const)("shows choices despite a saved %s draft and preserves it when backing out", async (mode) => {
    const saved = existing(mode), stored = draftResumeText(token);
    render(<TravellerPortal token={token} />); await openFresh();
    expect(memberRender).not.toHaveBeenCalled(); expect(draftResumeText(token)).toBe(stored);
    fireEvent.click(screen.getByRole("button", { name: "Back" }));
    fireEvent.click(screen.getByRole("button", { name: /Continue from where you left/ }));
    await screen.findByLabelText("Active traveller"); expect(active()).toEqual(saved);
  });

  it.each(["single", "family"] as const)("resumes the exact saved %s member only through the resume action", async (mode) => {
    const saved = existing(mode); render(<TravellerPortal token={token} />);
    fireEvent.click(screen.getByRole("button", { name: /Continue from where you left/ }));
    await screen.findByLabelText("Active traveller"); expect(active()).toEqual(saved);
    expect(screen.queryByRole("heading", { name: "Who are you submitting for?" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to start" }));
    await openFresh(); expect(screen.queryByLabelText("Active traveller")).not.toBeInTheDocument();
    expect(readDraftResume(token)?.fresh).toEqual(saved);
  });

  it("starts a distinct family after an old single draft, then advances members in order", async () => {
    const saved = existing("single"); render(<TravellerPortal token={token} />); await openFresh();
    fireEvent.click(screen.getByRole("button", { name: "Family" }));
    fireEvent.change(screen.getByLabelText("Number of travellers"), { target: { value: "3" } });
    expect(readDraftResume(token)?.fresh).toEqual(saved); expect(memberRender).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByLabelText("Active traveller"); const started = active();
    expect(started.mode).toBe("family"); expect(started.members).toHaveLength(3);
    expect(started.familyGroupId).not.toBe(saved.familyGroupId);
    expect(new Set(started.members.map(({ sessionId }) => sessionId)).size).toBe(3);
    expect(started.members.every(({ sessionId }) => sessionId !== saved.members[0].sessionId)).toBe(true);
    expect(screen.getByRole("heading", { name: "Head of family" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Complete member" }));
    expect(active().active).toBe(1); expect(active().members[0].completed).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Complete member" }));
    expect(active().active).toBe(2);
    fireEvent.click(screen.getByRole("button", { name: "Complete member" }));
    await screen.findByRole("heading", { name: "You’re all set" }); expect(readDraftResume(token)).toBeNull();
  });

  it.each(["Only me", "Family"])("gives a new %s submission its own draft lifetime", async (label) => {
    const old = existing("single");
    const nearlyExpired = saveFreshResume(token, old, new Date(Date.now() + 60_000).toISOString());
    render(<TravellerPortal token={token} />); await openFresh();
    expect(readDraftResume(token)?.expiresAt).toBe(nearlyExpired.expiresAt);
    fireEvent.click(screen.getByRole("button", { name: label }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await screen.findByLabelText("Active traveller");
    expect(readDraftResume(token)?.expiresAt).toBeGreaterThan(Date.now() + 23 * 60 * 60_000);
    expect(readDraftResume(token)?.submissionKey).not.toBe(nearlyExpired.submissionKey);
  });

  it("opens the chooser when switching from returning verification even with saved fresh progress", async () => {
    existing("single"); render(<TravellerPortal token={token} />);
    fireEvent.click(screen.getByRole("button", { name: /^Travelled with us before/ }));
    fireEvent.click(screen.getByRole("button", { name: "Continue as a new traveller" }));
    await screen.findByRole("heading", { name: "Who are you submitting for?" });
    expect(memberRender).not.toHaveBeenCalled();
  });

  it("keeps a returning draft on its own resume path", async () => {
    saveDraftResume(token, new Date(Date.now() + 60_000).toISOString(), "returning");
    render(<TravellerPortal token={token} />);
    fireEvent.click(screen.getByRole("button", { name: /Continue from where you left/ }));
    await waitFor(() => expect(screen.getByText("Saved returning review")).toBeInTheDocument());
    expect(memberRender).not.toHaveBeenCalled();
  });
});
