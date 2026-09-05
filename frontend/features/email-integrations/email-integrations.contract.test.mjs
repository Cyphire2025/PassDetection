import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), "utf8");
}

const routes = read("../../constants/routes.ts");
const endpoints = read("../../lib/api/endpoints.ts");
const proxy = read("../../proxy.ts");
const roles = read("../../lib/utils/role-access.ts");
const sidebar = read("../../components/layout/sidebar.tsx");
const routeCapabilities = read("../auth/config/route-capabilities.ts");
const shell = read("./components/email-integrations-shell.tsx");
const connections = read("./components/connections-page.tsx");
const review = read("./components/review-queue-page.tsx");
const inbox = read("./components/operational-inbox-page.tsx");
const message = ['message-activity-page.tsx', 'message-intelligence-brief.tsx', 'use-message-feedback-controller.ts', 'message-activity-model.ts', 'message-deadline-decisions.tsx', 'message-proposal-decisions.tsx', 'message-draft-editor.tsx', 'message-intelligence-feedback.tsx'].map((file) => read(`./components/${file}`)).join("\n");
const activity = read("./components/activity-page.tsx");
const dialog = read("./components/email-integrations-ui.tsx");
const hooks = read("./hooks/use-email-integrations.ts");
const api = read("./api/email-integrations.api.ts");
const types = read("./types.ts");
const inboxRoute = read(
  "../../app/(dashboard)/email-integrations/inbox/page.tsx",
);
const detailRoute = read(
  "../../app/(dashboard)/email-integrations/activity/[messageId]/page.tsx",
);

test("email integration routes and API endpoints are centralized", () => {
  assert.match(routes, /emailIntegrations: "\/email-integrations"/);
  assert.match(routes, /emailIntegrationsInbox: "\/email-integrations\/inbox"/);
  assert.match(routes, /emailIntegrationsReview: "\/email-integrations\/review"/);
  assert.match(routes, /emailIntegrationsActivity: "\/email-integrations\/activity"/);
  assert.match(endpoints, /inbox: "\/api\/v1\/email-integrations\/inbox"/);
  assert.match(endpoints, /status: "\/api\/v1\/email-integrations\/status"/);
  assert.match(endpoints, /connections: "\/api\/v1\/email-integrations\/connections"/);
  assert.match(endpoints, /oauth\/gmail\/authorize/);
  assert.match(endpoints, /oauth\/outlook\/authorize/);
  assert.match(endpoints, /connections\/\$\{connectionId\}\/ai-settings/);
  assert.match(endpoints, /connections\/\$\{connectionId\}\/data/);
  assert.match(endpoints, /reviews\/\$\{reviewId\}\/resolve/);
  assert.match(endpoints, /messages\/\$\{messageId\}/);
  assert.match(endpoints, /messages\/\$\{messageId\}\/intelligence/);
  assert.match(endpoints, /proposals\/\$\{proposalId\}\/decision/);
  assert.match(endpoints, /deadlines\/\$\{deadlineId\}\/decision/);
  assert.match(endpoints, /drafts\/\$\{draftId\}/);
  assert.match(endpoints, /drafts\/\$\{draftId\}\/decision/);
  assert.match(endpoints, /analyses\/\$\{analysisId\}\/feedback/);
  assert.match(endpoints, /analyses\/\$\{analysisId\}\/retry/);
});

test("email integration routes use both optimistic and direct role gates", () => {
  assert.match(proxy, /"\/email-integrations"/);
  const roleList = roles.match(
    /EMAIL_INTEGRATION_ROLES[\s\S]*?= \[([\s\S]*?)\];/,
  );
  assert.ok(roleList);
  assert.match(roleList[1], /"super_admin"/);
  assert.match(roleList[1], /"agency_admin"/);
  assert.match(roleList[1], /"agency_manager"/);
  assert.match(roleList[1], /"agency_staff"/);
  assert.doesNotMatch(roleList[1], /"agency_coordinator"/);
  assert.match(shell, /canAccessEmailIntegrations\(role\)/);
  assert.match(shell, /router\.replace\(/);
  assert.match(shell, /if \(!hasHydrated \|\| !canAccess\) return null/);
});

test("sidebar and section navigation expose accessible normal links", () => {
  const emailNav = sidebar.match(/\{\s*label: "Operations Inbox",[\s\S]*?\}/)?.[0];
  assert.ok(emailNav);
  assert.match(emailNav, /emailIntegrationsInbox/);
  assert.match(emailNav, /icon: Mail/);
  assert.match(sidebar, /canAccessApplicationPath\(user, item\.href\)/);
  assert.match(routeCapabilities, /agency_staff:[\s\S]*?"email\.integrations\.view"/);
  assert.match(routeCapabilities, /agency_coordinator: \["coordinator_app\.use"\]/);
  assert.match(shell, /<Link/);
  assert.match(shell, /aria-current=\{isActive \? "page" : undefined\}/);
  assert.doesNotMatch(shell, /role="tab"/);
  assert.ok(
    shell.indexOf('label: "Operations inbox"')
      < shell.indexOf('label: "Review queue"'),
  );
  assert.ok(
    shell.indexOf('label: "Activity"')
      < shell.indexOf('label: "Connections"'),
  );
});

test("OAuth handoff never stores credentials in browser-managed storage", () => {
  assert.match(connections, /window\.location\.assign\(authorizationUrl\)/);
  assert.match(connections, /isSafeOAuthAuthorizationUrl\(authorizationUrl\)/);
  assert.match(connections, /Connect Outlook/);
  assert.doesNotMatch(connections, /connection\.agency_name/);
  for (const source of [connections, review, message, types]) {
    assert.doesNotMatch(source, /localStorage|sessionStorage/);
    assert.doesNotMatch(source, /access_token|refresh_token|client_secret/);
  }
});

test("review decisions are revision-safe and email content renders as text", () => {
  assert.match(review, /expected_revision: item\.revision/);
  assert.match(review, /action: "assign"/);
  assert.match(message, /\{data\.body_excerpt \|\|/);
  assert.match(message, /whitespace-pre-wrap/);
  assert.doesNotMatch(review, /dangerouslySetInnerHTML/);
  assert.doesNotMatch(message, /dangerouslySetInnerHTML/);
});

test("operations inbox and intelligence remain explicitly read-only", () => {
  assert.match(inboxRoute, /EmailOperationalInboxPage/);
  assert.match(inbox, /Needs attention/);
  assert.match(inbox, /Deadlines/);
  assert.match(inbox, /Drafts ready/);
  assert.match(inbox, /Waiting/);
  assert.match(inbox, /Analysis complete/);
  assert.match(inbox, /sending remains\s+manual/);
  assert.match(inbox, /cannot send, edit, or delete mail/);
  assert.match(inbox, /useEmailOperationalInbox\(user\?\.id, view\)/);
  assert.doesNotMatch(inbox, /dangerouslySetInnerHTML/);
  assert.match(message, /AI operational brief/);
  assert.match(message, /Prepared actions/);
  assert.match(message, /Prepared reply draft/);
  assert.match(message, /ProposalDecisionButtons/);
  assert.match(message, /DeadlineDecisionButtons/);
  assert.match(message, /revision: proposal\.revision/);
  assert.match(message, /expected_revision: selection\.revision/);
  assert.match(message, /expected_status: selection\.status/);
  assert.match(message, /updatedAt: deadline\.updated_at/);
  assert.match(message, /expected_updated_at: selection\.updatedAt/);
  assert.match(message, /expected_revision: editorRevision/);
  assert.match(message, /expected_revision: decision\.revision/);
  assert.match(message, /Approve draft/);
  assert.match(message, /Dismiss AI brief/);
  assert.match(message, /useCreateEmailIntelligenceFeedback/);
  assert.match(message, /useRetryEmailIntelligence/);
  assert.match(message, /Retry analysis/);
  assert.match(message, /Open original email/);
  assert.match(message, /rel="noopener noreferrer"/);
  assert.match(message, /Prepared draft — sending remains manual/);
  assert.match(message, /does not send email/);
  assert.doesNotMatch(message, /dangerouslySetInnerHTML/);
});

test("operations inbox and intelligence mirror the owner-only backend DTOs", () => {
  for (const view of [
    "needs_attention",
    "upcoming_deadlines",
    "drafts_ready",
    "waiting",
    "completed_automatically",
    "all_activity",
  ]) {
    assert.match(types, new RegExp(`"${view}"`));
  }
  assert.doesNotMatch(types, /waiting_for_response/);
  for (const field of [
    "analysis_id",
    "intent",
    "confidence",
    "next_deadline",
    "proposal_count",
    "draft_status",
    "linked_group_name",
    "linked_passengers",
    "candidate_links",
    "human_review_confirmed",
  ]) {
    assert.match(types, new RegExp(`\\b${field}\\b`));
  }
  assert.match(types, /sending_available: false/);
  assert.match(types, /allowed_actions: EmailProposalDecisionAction\[\]/);
  assert.match(message, /useEmailMessageIntelligence/);
  assert.match(message, /The optional AI operational brief could not be loaded/);
  assert.match(message, /AI operational brief is not available yet/);
  assert.match(message, /Refresh brief/);
});

test("AI lifecycle mutations invalidate owner-scoped inbox and detail caches", () => {
  assert.match(hooks, /useDecideEmailDeadline/);
  assert.match(hooks, /emailIntegrationsApi\.decideDeadline/);
  assert.match(hooks, /useDecideEmailReplyDraft/);
  assert.match(hooks, /emailIntegrationsApi\.decideDraft/);
  assert.match(
    hooks,
    /useCreateEmailIntelligenceFeedback\(\)[\s\S]*?onSuccess: invalidate/,
  );
  assert.match(
    hooks,
    /useRetryEmailIntelligence\(\)[\s\S]*?onSuccess: invalidate/,
  );
  assert.match(message, /AI linked group/);
  assert.match(message, /AI linked passengers/);
  assert.match(message, /Should have notified me/);
  assert.match(message, /Should not notify me/);
  assert.match(message, /Add missing group/);
  assert.match(message, /Add missing passenger/);
  assert.match(message, /Add missing deadline/);
  assert.match(message, /Visible match candidates/);
  assert.match(message, /Selection needs review/);
});

test("mailbox AI assistance requires an explicit owner opt-in", () => {
  assert.match(types, /\bai_enabled: boolean/);
  assert.match(types, /\bai_effective_enabled: boolean/);
  assert.match(types, /\boriginal_email_url: string \| null/);
  assert.match(types, /\bai_notifications_enabled: boolean/);
  assert.match(types, /\bai_processing_enabled: boolean/);
  assert.match(types, /\beffective_enabled: boolean/);
  assert.match(hooks, /useUpdateEmailAiSettings/);
  assert.match(
    hooks,
    /useUpdateEmailAiSettings\(\)[\s\S]*?onSettled: invalidate/,
  );
  assert.match(connections, /Enable AI assistance/);
  assert.match(connections, /Turn off AI/);
  assert.match(connections, /Prepared drafts remain unsent/);
  assert.match(connections, /shadow mode/);
  assert.match(connections, /updateAiSettings\.isPending/);
  assert.match(connections, /could not be confirmed/);
  assert.doesNotMatch(connections, /No mailbox setting was\s+changed/);
});

test("account removal is explicit, confirmed, and invalidates email views", () => {
  assert.match(types, /export interface RemoveEmailConnectionResponse/);
  assert.match(api, /confirmation_email: confirmationEmail/);
  assert.match(api, /connectionData\(connectionId\)/);
  assert.match(hooks, /useRemoveEmailConnection/);
  assert.match(hooks, /useRemoveEmailConnection\(\)[\s\S]*?onSettled: invalidate/);
  assert.match(connections, /Permanently remove email account\?/);
  assert.match(connections, /Type \{removeTarget\.email_address\} to confirm/);
  assert.match(connections, /This cannot be undone/);
  assert.match(connections, /manually uploaded documents are not changed/);
  assert.doesNotMatch(connections, /Previously processed activity is retained/);
});

test("review queue exposes full history and confirms whole-email unrelated scope", () => {
  const statusList = review.match(
    /const REVIEW_STATUSES = \[([\s\S]*?)\] as const;/,
  );
  assert.ok(statusList);
  for (const status of [
    "open",
    "deferred",
    "resolved",
    "rejected",
    "cancelled",
    "all",
  ]) {
    assert.match(statusList[1], new RegExp(`value: "${status}"`));
  }
  assert.match(review, /Mark this entire email as unrelated\?/);
  assert.match(review, /entire source email as unrelated/);
  assert.match(review, /all other open or deferred review items/);
});

test("message detail route follows the Next 16 asynchronous params contract", () => {
  assert.match(detailRoute, /params: Promise<\{ messageId: string \}>/);
  assert.match(detailRoute, /const \{ messageId \} = await params/);
});

test("connection response type contains only the public contract fields", () => {
  const connection = types.match(
    /export interface EmailConnection \{([\s\S]*?)\n\}/,
  );
  assert.ok(connection);
  for (const field of [
    "id",
    "agency_id",
    "agency_name",
    "provider",
    "email_address",
    "status",
    "last_successful_sync_at",
    "last_sync_attempt_at",
    "last_error_message",
    "ai_processing_enabled",
    "allowed_actions",
  ]) {
    assert.match(connection[1], new RegExp(`\\b${field}\\b`));
  }
  assert.doesNotMatch(connection[1], /token|secret|authorization_code/);
});

test("email connection, review, and activity views refresh near real time", () => {
  assert.match(hooks, /emailRepairIntervalMs/);
  assert.match(hooks, /refetchInterval: \(\) => emailRepairIntervalMs\(\)/);
  assert.match(hooks, /inbox: \(userId: string, view:/);
  assert.match(hooks, /queryKey: EMAIL_INTEGRATION_QUERY_KEYS\.inbox/);
  assert.match(hooks, /useLiveHistoryFeed/);
  assert.match(read("../../lib/hooks/use-live-history-feed.ts"), /maxPages: 5/);
  assert.match(hooks, /refetchIntervalInBackground: false/);
  assert.match(hooks, /useEmailMessageIntelligence/);
  assert.match(hooks, /pollWhileMissing/);
  assert.match(hooks, /missingPollWindow\.current\.messageId !== messageId/);
  assert.match(
    hooks,
    /missingPollWindow\.current\.pollWhileMissing !== pollWhileMissing/,
  );
  assert.doesNotMatch(
    hooks,
    /useEffect\(\(\) => \{[\s\S]*?missingPollStartedAt/,
  );
  assert.match(
    hooks,
    /ACTIVE_INTELLIGENCE_STATUSES = new Set\(\["pending", "processing"\]\)/,
  );
  assert.match(hooks, /retry: false/);
});

test("dialog decisions submit the immutable state captured when opened", () => {
  assert.match(
    message,
    /setSelection\(\{\s*action,\s*revision: proposal\.revision,\s*\}\)/,
  );
  assert.match(message, /expected_revision: selection\.revision/);
  assert.match(
    message,
    /setSelection\(\{\s*action,\s*status: activeStatus,\s*updatedAt: deadline\.updated_at/,
  );
  assert.match(message, /expected_status: selection\.status/);
  assert.match(message, /expected_updated_at: selection\.updatedAt/);
  assert.match(message, /setCorrectionSnapshot\(snapshot\)/);
  assert.match(message, /const expected = correctionSnapshot/);
  assert.match(message, /setDismissSnapshot\(snapshot\)/);
  assert.match(message, /const expected = dismissSnapshot/);
});

test("deadline corrections identify the exact detected deadline", () => {
  assert.match(message, /Deadline to correct/);
  assert.match(message, /value=\{selectedDeadlineId\}/);
  assert.match(message, /deadline_id: selectedDeadlineId \|\| undefined/);
  assert.match(message, /Select a detected deadline/);
  assert.doesNotMatch(message, /deadlines\[0\]/);
});

test("correction choices are message scoped without changing review queue options", () => {
  assert.match(
    api,
    /\.\.\.\(messageId \? \{ message_id: messageId \} : \{\}\)/,
  );
  assert.match(
    message,
    /useEmailReviewOptions\(\s*undefined,\s*isLinkCorrection,\s*messageId/,
  );
  assert.match(
    message,
    /useEmailReviewOptions\(\s*selectedGroupId \|\| undefined,[\s\S]*?messageId/,
  );
  assert.match(review, /const groups = useEmailReviewOptions\(\)/);
  assert.match(
    review,
    /const passengers = useEmailReviewOptions\(groupId \|\| undefined\)/,
  );
});

test("nested email pages avoid duplicate main landmarks and dialog traps reverse tab", () => {
  for (const source of [connections, review, inbox, activity, message]) {
    assert.doesNotMatch(source, /<\/?main\b/);
  }
  assert.match(dialog, /document\.activeElement === dialog/);
});
