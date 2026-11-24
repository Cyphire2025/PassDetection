import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ComponentProps } from "react";
import "../../app/globals.css";
import { MessageComposerReviewDialog } from "../../features/whatsapp/workspace/message-composer-review-dialog";
import { HistoricalResend } from "../../features/whatsapp/workspace/historical-resend-dialog";
import { BroadcastDocumentComposer } from "../../features/whatsapp/workspace/document-composer";
import { TripUpdateComposer } from "../../features/whatsapp/workspace/trip-update-composer";
import { GroupUpdateRecipientDetails } from "../../features/whatsapp/components/group-update-recipient-details";
import { ComposerPreview } from "../../features/whatsapp/workspace/composer-primitives";
import { MessageDeliveryPreview } from "../../features/whatsapp/components/whatsapp-message-composer-ui";
import { DocumentDeliveryPreviewDialog } from "../../features/documents/components/document-workspace-dialogs";

declare global {
  interface Window { messagePaneFixture: { pane: string; message: string }; messagePaneModels: Record<string, unknown> }
}
const { pane, message } = window.messagePaneFixture;
const noop = () => undefined;
const person = { id: "synthetic-person", name: "Synthetic traveller", phone_number: "+12025550100" };
window.messagePaneModels = {
  document: { group: {}, queries: [], pending: false, error: null, loadError: null, loading: false, refreshing: false,
    text1: message, text2: "Check every document.", setContent1: noop, setContent2: noop, rendered: message,
    rows: [], sample: undefined, selected: [{ row: {} }], search: "", matches: [], pageOffset: 0, selectedIds: new Set(),
    setSampleId: noop, setSearch: noop, setOffset: noop, setError: noop, setSelection: noop, reviewing: true, setReviewing: noop, send: noop, ready: true },
  trip: { broadcast: { name: "Synthetic trip" }, audience: { submission_status: "all", document_status: "all", document_type: "visa" },
    setAudience: noop, content: message, setContent: noop, setSelected: noop, setPreviewKey: noop, reviewing: true,
    setReviewing: noop, preview: { data: {}, isFetching: false }, rows: [], chosen: [person], chosenKeys: new Set(), numbers: 1,
    person, message, send: {}, submittedRequest: null, locked: false, ready: true, submit: noop },
};
function Content() {
  if (pane === "review") return <MessageComposerReviewDialog checkedHistory={false} setCheckedHistory={noop} model={{
    definition: { label: "Synthetic welcome" }, group: { id: "synthetic-group", name: "Synthetic trip" },
    reviewedCount: 1, reviewedMessage: message, reviewing: true, setReviewing: noop, pending: false,
    ready: true, count: 1, selected: [person], recovery: null, error: null, uncertain: null, send: noop,
  } as unknown as ComponentProps<typeof MessageComposerReviewDialog>["model"]} />;
  if (pane === "historical") return <HistoricalResend groupId="synthetic-group" entry={{ message_type: "passport_link", created_at: "2026-10-01T00:00:00Z", message_preview: message } as ComponentProps<typeof HistoricalResend>["entry"]} recipient={{ name: person.name, current_phone_number: person.phone_number, status: "failed", rendered_message: message } as ComponentProps<typeof HistoricalResend>["recipient"]} onClose={noop} />;
  if (pane === "document-review") return <BroadcastDocumentComposer documentType="visa" sources={[]} onClose={noop} />;
  if (pane === "trip-review") return <TripUpdateComposer groupId="synthetic-group" />;
  if (pane === "saved-update") return <GroupUpdateRecipientDetails documentLabel="Visa" row={{
    name: person.name, imported_details: {}, latest_update: { message, status: "sent", created_at: "2026-10-01T00:00:00Z" },
    submission_status: "submitted", phone_number: person.phone_number, document_count: 1, confirmed_count: 1,
  } as unknown as ComponentProps<typeof GroupUpdateRecipientDetails>["row"]} />;
  if (pane === "document-delivery") return <DocumentDeliveryPreviewDialog preview={{ document_type: "visa", summary: {}, recipients: [], can_send: true, preview_token: "synthetic-preview", template_name: "synthetic_document_v1" } as unknown as ComponentProps<typeof DocumentDeliveryPreviewDialog>["preview"]} loading={false} loadError={null} selectedDocumentIds={[]} resendDocumentIds={[]} sending={false} sendError={null} messageContent1={message} messageContent2="Check every document." onMessageContent1Change={noop} onMessageContent2Change={noop} onToggleDocument={noop} onToggleResend={noop} onClose={noop} onSend={noop} />;
  if (pane === "inline-preview") return <ComposerPreview message={message} current />;
  return <MessageDeliveryPreview preview={{ recipient_name: person.name, rendered_message: message, template_name: "synthetic_v1" }} previewIsCurrent previewFailed={false} messageType="reminder" headerImagePreview={null} headerImageId={null} />;
}
createRoot(document.getElementById("root")!).render(<QueryClientProvider client={new QueryClient()}><main className="mx-auto w-full max-w-5xl p-4"><Content /></main></QueryClientProvider>);
