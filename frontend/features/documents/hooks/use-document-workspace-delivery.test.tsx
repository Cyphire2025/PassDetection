import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { DocumentDeliveryPreview } from "@/types/document-distribution.types";
import { VISA_DISTRIBUTION_LANE } from "../config/document-distribution-lanes";
import { documentPreview } from "../components/traveller-welcome.test-fixtures";
import { useDocumentWorkspaceDelivery } from "./use-document-workspace-delivery";

const mocks = vi.hoisted(() => ({ send: vi.fn(), register: vi.fn(), reset: vi.fn(),
  preview: {} as DocumentDeliveryPreview, fetching: false,
}));
vi.mock("./use-document-distribution", () => ({
  useDocumentDeliveryPreview: () => ({ data: mocks.preview, isFetching: mocks.fetching, error: null }),
  useSendDocumentWhatsAppBroadcast: () => ({ mutate: mocks.send, reset: mocks.reset, isPending: false }),
}));
vi.mock("@/features/whatsapp/components/whatsapp-activity-tracker", () => ({
  useWhatsAppActivityTracker: () => ({ registerActivity: mocks.register }),
}));

beforeEach(() => { vi.clearAllMocks(); mocks.preview = documentPreview(); mocks.fetching = false; });

describe("document delivery admission", () => {
  it("suppresses a second same-turn send and retains the reviewed token and document selection", () => {
    const { result } = renderHook(() => useDocumentWorkspaceDelivery("trip", VISA_DISTRIBUTION_LANE, "Synthetic Trip"));
    act(() => result.current.openDelivery());
    act(() => { result.current.sendDelivery(); result.current.sendDelivery(); });
    expect(mocks.send).toHaveBeenCalledTimes(1);
    expect(mocks.send.mock.calls[0][0]).toEqual({ batchId: "batch", previewToken: "a".repeat(64),
      documentIds: ["visa-1"], resendDocumentIds: [], messageContent1: "Your visa is attached.", messageContent2: "Have a good journey.",
    });
    const callbacks = mocks.send.mock.calls[0][1];
    act(() => callbacks.onSettled());
    expect(mocks.send).toHaveBeenCalledTimes(1);
    act(() => result.current.sendDelivery());
    expect(mocks.send).toHaveBeenCalledTimes(2);
  });

  it.each(["refreshing", "ineligible"] as const)("blocks a send while the preview is %s", (state) => {
    mocks.fetching = state === "refreshing";
    if (state === "ineligible") mocks.preview = documentPreview({ can_send: false });
    const { result } = renderHook(() => useDocumentWorkspaceDelivery("trip", VISA_DISTRIBUTION_LANE));
    act(() => result.current.openDelivery());
    act(() => result.current.sendDelivery());
    expect(mocks.send).not.toHaveBeenCalled();
  });
});
