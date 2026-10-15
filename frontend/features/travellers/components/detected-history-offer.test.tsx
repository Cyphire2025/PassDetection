import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { returningApi } from "../api/returning.api";
import { DetectedHistoryOffer } from "./detected-history-offer";

vi.mock("../api/returning.api", () => ({ returningApi: { detectedHistory: vi.fn() } }));
beforeEach(() => vi.resetAllMocks());
const props = { token: "group", submissionId: "submission", extractionRevision: 4, uploadSessionId: "private-attempt", onVerify: vi.fn() };
describe("fresh upload history hint", () => {
  it("offers normal verification without exposing or prefilling any historical answer", async () => {
    vi.mocked(returningApi.detectedHistory).mockResolvedValue({ available: true });
    render(<DetectedHistoryOffer {...props} />);
    fireEvent.click(await screen.findByRole("button", { name: "Verify to review saved information" }));
    expect(returningApi.detectedHistory).toHaveBeenCalledExactlyOnceWith({ group_token: "group", source_submission_id: "submission", expected_extraction_revision: 4 }, "private-attempt", expect.any(AbortSignal));
    expect(props.onVerify).toHaveBeenCalledOnce();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("drops a late hint for an old extraction and leaves an unavailable new upload unchanged", async () => {
    let finish!: (result: { available: boolean }) => void;
    let signal: AbortSignal | undefined;
    vi.mocked(returningApi.detectedHistory).mockImplementationOnce((_body, _attempt, requestSignal) => { signal = requestSignal; return new Promise((resolve) => { finish = resolve; }); }).mockResolvedValueOnce({ available: false });
    const view = render(<DetectedHistoryOffer {...props} />);
    view.rerender(<DetectedHistoryOffer {...props} extractionRevision={5} />);
    expect(signal?.aborted).toBe(true);
    await act(async () => finish({ available: true }));
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
