import { AxiosError } from "axios";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { QualifierSelectionState } from "@/features/passports/api/upload-links.api";
import { runUploadFlowBootstrap } from "./upload-flow-bootstrap";
import { qualifierChoiceKey } from "./relation-qualifier";
import { readQualifierSelectionToken, writeQualifierSelectionToken } from "./upload-flow-session";

const api = vi.hoisted(() => ({ getQualifierSelection: vi.fn() }));
vi.mock("@/features/passports/api/upload-links.api", () => ({ uploadLinksApi: api }));
vi.mock("../api/upload.api", () => ({
  uploadApi: { getUploadStatus: vi.fn(), reconcileUpload: vi.fn() },
}));

const token = "test-group-token";
const selectionToken = "private-selection-token";
const selection: QualifierSelectionState = {
  is_self: false,
  relation_code: "other",
  relation_label: "Family friend",
  selected_at: "2026-09-08T10:00:00Z",
  expires_at: "2026-09-08T11:00:00Z",
  status: "active",
  submission_id: null,
};

function createActions() {
  return {
    setSingleUploadIdempotencyKey: vi.fn(), setSubmission: vi.fn(),
    setClientName: vi.fn(), setStep: vi.fn(), setReviewFields: vi.fn(),
    setExtractionNotice: vi.fn(), setCanRetryExtraction: vi.fn(),
    setProcessingProgress: vi.fn(), setProcessingStage: vi.fn(),
    queueSubmissionResume: vi.fn(), setFlowMode: vi.fn(), setUploadError: vi.fn(),
    setQualifierSelectionToken: vi.fn(), setPersistedQualifierChoice: vi.fn(),
    setQualifierPath: vi.fn(), setQualifierRelationCode: vi.fn(),
    setQualifierOtherRelation: vi.fn(),
  };
}

describe("qualifier relationship recovery", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.sessionStorage.clear();
    writeQualifierSelectionToken(token, selectionToken);
  });

  it.each([
    { ...selection, expectedPath: "other", expectedCode: "", expectedText: "Family friend" },
    { ...selection, relation_code: "spouse", relation_label: "Spouse", expectedPath: "relation", expectedCode: "spouse", expectedText: "" },
    { ...selection, is_self: true, relation_code: null, relation_label: "Self", expectedPath: "self", expectedCode: "", expectedText: "" },
  ])("restores $expectedPath without stale values from another entry method", async (saved) => {
    api.getQualifierSelection.mockResolvedValue(saved);
    const actions = createActions();
    await runUploadFlowBootstrap({
      token, relationWithQualifierEnabled: true, isCancelled: () => false,
      reportPublicFlowOnce: vi.fn(), actions,
    });

    expect(api.getQualifierSelection).toHaveBeenCalledWith(token, selectionToken);
    expect(actions.setQualifierPath).toHaveBeenCalledWith(saved.expectedPath);
    expect(actions.setQualifierRelationCode).toHaveBeenCalledWith(saved.expectedCode);
    expect(actions.setQualifierOtherRelation).toHaveBeenCalledWith(saved.expectedText);
    expect(actions.setQualifierSelectionToken).toHaveBeenCalledWith(selectionToken);
    expect(actions.setPersistedQualifierChoice).toHaveBeenCalledWith(qualifierChoiceKey(
      saved.expectedPath as "self" | "relation" | "other", saved.expectedCode, saved.expectedText,
    ));
    expect(actions.setStep).toHaveBeenLastCalledWith("METHOD_SELECT");
  });

  it("requires a new choice when the server rejects a method disabled since selection", async () => {
    const error = new AxiosError("This relationship entry option is no longer enabled.");
    error.response = { status: 422 } as AxiosError["response"];
    api.getQualifierSelection.mockRejectedValue(error);
    const actions = createActions();
    await runUploadFlowBootstrap({
      token, relationWithQualifierEnabled: true, isCancelled: () => false,
      reportPublicFlowOnce: vi.fn(), actions,
    });

    expect(readQualifierSelectionToken(token)).toBeNull();
    expect(actions.setQualifierSelectionToken).toHaveBeenCalledWith(null);
    expect(actions.setPersistedQualifierChoice).toHaveBeenCalledWith(null);
    expect(actions.setQualifierOtherRelation).not.toHaveBeenCalled();
    expect(actions.setStep).toHaveBeenLastCalledWith("QUALIFIER_SELECT");
  });

  it("preserves the private selection on temporary connection failures", async () => {
    api.getQualifierSelection.mockRejectedValue(new AxiosError("Network unavailable"));
    const actions = createActions();
    await runUploadFlowBootstrap({
      token, relationWithQualifierEnabled: true, isCancelled: () => false,
      reportPublicFlowOnce: vi.fn(), actions,
    });

    expect(readQualifierSelectionToken(token)).toBe(selectionToken);
    expect(actions.setQualifierOtherRelation).not.toHaveBeenCalled();
    expect(actions.setStep).toHaveBeenLastCalledWith("RECOVERY_ERROR");
  });
});
