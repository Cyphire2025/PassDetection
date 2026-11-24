import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { returningApi } from "../api/returning.api";
import type { ReturningHistory } from "../types";
import { ReturningResume } from "./returning-resume";
const mocks = vi.hoisted(() => ({ review: vi.fn() }));
vi.mock("../api/returning.api", () => ({ returningApi: { history: vi.fn() } }));
vi.mock("./returning-review", () => ({ ReturningReview: (props: { history: ReturningHistory }) => { mocks.review(props); return <h1>{props.history.display_name}</h1>; } }));
beforeEach(() => { vi.clearAllMocks(); }); afterEach(cleanup);
it("opens only the current scoped history and preserves review callbacks", async () => {
  const history = { display_name: "Verified synthetic traveller" } as ReturningHistory, onFresh = vi.fn();
  vi.mocked(returningApi.history).mockResolvedValue(history);
  render(<ReturningResume token="synthetic-trip" groupName="Synthetic trip" onFresh={onFresh} onVerify={vi.fn()} />);
  expect(await screen.findByRole("heading", { name: history.display_name })).toBeVisible();
  expect(returningApi.history).toHaveBeenCalledExactlyOnceWith(expect.any(AbortSignal), "synthetic-trip");
  expect(mocks.review).toHaveBeenLastCalledWith(expect.objectContaining({ history, groupToken: "synthetic-trip", groupName: "Synthetic trip", onFresh, onReplace: onFresh }));
});
it("keeps private history hidden after a failed resume and retains explicit verification", async () => {
  vi.mocked(returningApi.history).mockRejectedValue(new Error("Synthetic expired claim")); const onVerify = vi.fn();
  render(<ReturningResume token="synthetic-trip" groupName="Synthetic trip" onFresh={vi.fn()} onVerify={onVerify} />);
  fireEvent.click(await screen.findByRole("button", { name: "Verify and continue" })); expect(onVerify).toHaveBeenCalledOnce(); expect(mocks.review).not.toHaveBeenCalled();
});
it("does not open a late protected history after leaving the resume screen", async () => {
  let finish!: (history: ReturningHistory) => void;
  vi.mocked(returningApi.history).mockReturnValue(new Promise(resolve => { finish = resolve; }));
  const view = render(<ReturningResume token="synthetic-trip" groupName="Synthetic trip" onFresh={vi.fn()} onVerify={vi.fn()} />);
  const signal = vi.mocked(returningApi.history).mock.calls[0][0]!; view.unmount(); expect(signal.aborted).toBe(true);
  await act(async () => { finish({ display_name: "Private synthetic name" } as ReturningHistory); }); expect(mocks.review).not.toHaveBeenCalled();
});
