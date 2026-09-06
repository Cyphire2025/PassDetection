// @vitest-environment jsdom
import type { ComponentProps, ReactNode } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RenameDocumentBatch } from "@/types/document-rename.types";
import type { DocumentDeliveryPreview } from "@/types/document-distribution.types";
import { documentRenameApi } from "../api/document-rename.api";
import type { DocumentUploadProgress } from "../services/document-upload-batching";
import { DocumentRenamePage } from "./document-rename-page";
import { DocumentWorkspaceUploadStatus } from "./document-workspace-upload-status";
import { DocumentDeliveryPreviewDialog } from "./document-workspace-dialogs";

vi.mock("@/components/shared/processing-motion", () => ({
  ProcessingMotion: ({ variant }: { variant: string }) => (
    <div data-testid="processing-motion" data-variant={variant} aria-hidden="true" />
  ),
}));

vi.mock("@/components/shared/intent-prefetch-link", () => ({
  IntentPrefetchLink: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("../api/document-rename.api", () => ({
  documentRenameApi: {
    listBatches: vi.fn(),
    analyze: vi.fn(),
    getBatch: vi.fn(),
    deleteBatches: vi.fn(),
  },
}));

const processingProgress: DocumentUploadProgress = {
  phase: "processing", percent: 42, completedFiles: 3, totalFiles: 8,
  chunkNumber: 2, chunkCount: 3,
};

const uploadProps: ComponentProps<typeof DocumentWorkspaceUploadStatus> = {
  phase: "idle", progress: 42, progressDetail: processingProgress,
  uploadPending: false, verifyPending: false, uploadError: null,
  selectionError: null, verifyError: null, reuploadError: null,
  deleteError: null, unassignError: null, verification: null,
};

describe("document processing motion follows real work", () => {
  it("shows analysis only while document checking is processing, then yields to results", () => {
    const { rerender } = render(
      <DocumentWorkspaceUploadStatus {...uploadProps} phase="checking" verifyPending />,
    );
    expect(screen.getByTestId("processing-motion")).toHaveAttribute("data-variant", "analysis");
    expect(screen.getByRole("status")).toHaveTextContent("Checking PDFs in parallel — 3/8 complete");
    expect(screen.getByRole("status")).toHaveTextContent("42%");

    rerender(<DocumentWorkspaceUploadStatus {...uploadProps} verification={{
      group_id: "group-test", document_type: "visa",
      total_count: 8, accepted_count: 8, rejected_count: 0, files: [],
    }} />);
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    expect(screen.getByText("Document Check Results")).toBeInTheDocument();
  });

  it("switches to distribution for accepted PDFs being matched and saved", () => {
    render(<DocumentWorkspaceUploadStatus {...uploadProps} phase="uploading" uploadPending />);
    expect(screen.getByTestId("processing-motion")).toHaveAttribute("data-variant", "distribution");
    expect(screen.getByRole("status")).toHaveTextContent("Matching and saving PDFs — 3/8 complete");
  });

  it("does not animate during byte upload or after a request ends with stale phase data", () => {
    const { rerender } = render(<DocumentWorkspaceUploadStatus {...uploadProps}
      phase="checking" verifyPending progressDetail={{ ...processingProgress, phase: "uploading" }} />);
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Preparing parallel PDF checks");

    rerender(<DocumentWorkspaceUploadStatus {...uploadProps} phase="checking" />);
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    rerender(<DocumentWorkspaceUploadStatus {...uploadProps} phase="uploading" uploadPending
      progressDetail={{ ...processingProgress, phase: "completed", percent: 100 }} />);
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
  });

  it("removes the scene on failure and preserves the resumable partial-upload count", () => {
    const { rerender } = render(<DocumentWorkspaceUploadStatus {...uploadProps} phase="uploading" uploadPending />);
    rerender(<DocumentWorkspaceUploadStatus {...uploadProps} uploadError={new Error("Connection interrupted.")} />);
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    expect(screen.getByText(/3 of 8 PDFs are safely committed/)).toBeInTheDocument();
    expect(screen.getByText(/click Upload Accepted again to resume/)).toBeInTheDocument();
  });
});

const preview: DocumentDeliveryPreview = {
  group_id: "group-test", batch_id: "batch-test", document_type: "visa",
  template_name: "documents_v1", template_configured: true, linked_broadcast_count: 1,
  can_send: true, configuration_error: null, message_content_1: "Your document is attached.",
  message_content_2: "Please review it before departure.",
  summary: { total_passengers: 1, ready: 1, retryable: 0, already_sent: 0, in_progress: 0, blocked: 0 },
  recipients: [],
};

function deliveryProps(): ComponentProps<typeof DocumentDeliveryPreviewDialog> {
  return {
    preview, loading: false, loadError: null, selectedDocumentIds: ["doc-test"], resendDocumentIds: [],
    sending: false, sendError: null, messageContent1: preview.message_content_1,
    messageContent2: preview.message_content_2, onMessageContent1Change: vi.fn(),
    onMessageContent2Change: vi.fn(), onToggleDocument: vi.fn(), onToggleResend: vi.fn(),
    onClose: vi.fn(), onSend: vi.fn(),
  };
}

describe("document delivery animation preserves queue semantics", () => {
  it("shows distribution while preparing the preview and stops when review is ready", () => {
    const props = deliveryProps();
    const { rerender } = render(<DocumentDeliveryPreviewDialog {...props} loading preview={undefined} />);
    expect(screen.getByTestId("processing-motion")).toHaveAttribute("data-variant", "distribution");
    expect(screen.getByRole("status")).toHaveTextContent("Preparing the delivery preview");
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
    expect(props.onSend).not.toHaveBeenCalled();

    rerender(<DocumentDeliveryPreviewDialog {...props} />);
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send individually to 1" })).toBeEnabled();
  });

  it("labels a pending send as queueing and restores controls and errors on failure", () => {
    const props = deliveryProps();
    const { rerender } = render(<DocumentDeliveryPreviewDialog {...props} sending />);
    expect(screen.getByTestId("processing-motion")).toHaveAttribute("data-variant", "distribution");
    expect(screen.getByRole("status")).toHaveTextContent("Queueing document messages");
    expect(screen.getByRole("status")).toHaveTextContent("Delivery status will update separately.");
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();

    rerender(<DocumentDeliveryPreviewDialog {...props} sendError={new Error("Queue request failed.")} />);
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    expect(screen.getByText("Queue request failed.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
  });

  it("does not keep motion running after a preview-load error", () => {
    render(<DocumentDeliveryPreviewDialog {...deliveryProps()} preview={undefined}
      loadError={new Error("Preview unavailable.")} />);
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    expect(screen.getAllByText("Preview unavailable.").length).toBeGreaterThan(0);
  });
});

const renamedBatch: RenameDocumentBatch = {
  batch_id: "rename-test", title: "Test documents", status: "completed", total_count: 1,
  visa_count: 1, ticket_count: 0, unknown_count: 0, zip_download_url: "/test.zip",
  created_at: "2026-09-06T12:00:00Z", items: [],
};

async function beginRename() {
  let resolve!: (result: RenameDocumentBatch) => void;
  let reject!: (reason: Error) => void;
  const pending = new Promise<RenameDocumentBatch>((done, fail) => { resolve = done; reject = fail; });
  vi.mocked(documentRenameApi.analyze).mockReturnValue(pending);
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const { container } = render(<QueryClientProvider client={queryClient}><DocumentRenamePage /></QueryClientProvider>);
  fireEvent.change(screen.getByLabelText("Batch title"), { target: { value: "Test documents" } });
  fireEvent.change(container.querySelector('input[type="file"]')!, {
    target: { files: [new File(["%PDF-1.4 test"], "test.pdf", { type: "application/pdf" })] },
  });
  fireEvent.click(screen.getByRole("button", { name: "Analyze And Rename (1)" }));
  await waitFor(() => expect(documentRenameApi.analyze).toHaveBeenCalledOnce());
  const reportProgress = vi.mocked(documentRenameApi.analyze).mock.calls[0][2]!;
  return { resolve, reject, reportProgress };
}

describe("rename motion uses the combined operation without inventing a stage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(documentRenameApi.listBatches).mockResolvedValue([]);
  });

  it("waits for server processing, shows the rename scene, and disappears when real results arrive", async () => {
    const work = await beginRename();
    expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument();
    act(() => work.reportProgress(processingProgress));
    expect(screen.getByTestId("processing-motion")).toHaveAttribute("data-variant", "rename");
    expect(screen.getByRole("status")).toHaveTextContent("Analysing and renaming PDFs — 3/8 complete");
    await act(async () => work.resolve(renamedBatch));
    await waitFor(() => expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Rename Results" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Download ZIP" })).toHaveAttribute("href", "/test.zip");
  });

  it("stops immediately after an analysis failure and retains the resume guidance", async () => {
    const work = await beginRename();
    act(() => work.reportProgress(processingProgress));
    expect(screen.getByTestId("processing-motion")).toHaveAttribute("data-variant", "rename");
    await act(async () => work.reject(new Error("Document service unavailable.")));
    await waitFor(() => expect(screen.queryByTestId("processing-motion")).not.toBeInTheDocument());
    expect(screen.getByText(/Document service unavailable/)).toHaveTextContent("3 of 8 PDFs are safely committed");
    expect(screen.getByRole("button", { name: "Analyze And Rename (1)" })).toBeEnabled();
  });
});
