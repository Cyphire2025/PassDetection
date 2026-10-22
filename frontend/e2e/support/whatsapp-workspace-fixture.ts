import type { Page, Route } from "@playwright/test";

const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
const now = "2026-10-16T10:30:00Z";
export const broadcastId = "workspace-trip";
export const batchId = "update-oct-16";
const names = [
  "Aarav Shah",
  "Diya Mehta",
  "Ishaan Kapoor",
  "Meera Rao",
  "Rohan Desai",
  "Sara Malhotra",
  "Anaya Patel",
  "Arjun Nair",
  "Avni Joshi",
  "Dev Shah",
  "Ira Sen",
  "Kabir Das",
];
const makeStatus = (type: string, status: string) => ({
  message_type: type,
  status,
  already_sent: ["read", "delivered", "sent"].includes(status),
  latest_resend_status: null,
  resend_blocked: false,
  submitted_at: now,
  status_updated_at: now,
});
export const fixtureGroup = () => ({
  id: broadcastId,
  name: "Dubai · October delegates",
  recipient_count: names.length,
  total_contact_count: names.length,
  created_at: now,
  updated_at: now,
  recipient_opt_in_confirmed: true,
  is_archived: false,
  rejected_contact_count: 0,
  linked_client_groups: [
    { id: "source-trip", name: "Dubai delegates", status: "active" },
  ],
  support_contacts: [
    {
      id: "support",
      name: "Trip support",
      phone_number: "+919800001000",
      normalized_phone_number: "919800001000",
    },
  ],
  recipients: names.map((name, i) => ({
    id: `person-${i}`,
    name,
    phone_number: `+91980000${String(i).padStart(4, "0")}`,
    normalized_phone_number: `91980000${String(i).padStart(4, "0")}`,
    imported_fields: {
      company: "Example Industries",
      departure_city: i % 2 ? "Mumbai" : "Delhi",
      passport: `TEST${String(i).padStart(4, "0")}`,
      travel_date: "21 October 2026",
    },
    welcome_status: i === 1 ? "failed" : "read",
    welcome_delivered: i !== 1,
    message_statuses: [
      makeStatus("welcome", i === 1 ? "failed" : "read"),
      makeStatus("passport_link", i === 0 ? "read" : "not_sent"),
    ],
  })),
});
const field = (key: string, label: string, kind = "textarea") => ({
  key,
  label,
  kind,
  required: true,
  max_length: kind === "url" ? 2048 : 600,
});
export const catalog = [
  {
    id: "text_update",
    message_type: "update",
    label: "Text trip update",
    description: "Write a text update and filter recipients by submission and document delivery.",
    category: "Trip updates",
    image_required: false,
    audience: "update",
    repeatable: true,
    fields: [field("message_content", "Update message")],
  },
  {
    id: "welcome",
    message_type: "welcome",
    label: "Welcome message",
    description: "Introduce the trip and welcome new recipients.",
    category: "Getting started",
    image_required: true,
    audience: "standard",
    repeatable: false,
    fields: [field("message_content", "Welcome message")],
  },
  {
    id: "passport_link",
    message_type: "passport_link",
    label: "Passport link",
    description: "Share the document upload link and instructions.",
    category: "Documents",
    image_required: true,
    audience: "standard",
    repeatable: false,
    fields: [
      field("passport_link", "Passport upload link", "url"),
      field("passport_intro", "Introduction"),
      field("message_content", "Instructions"),
    ],
  },
  {
    id: "reminder",
    message_type: "reminder",
    label: "Reminder",
    description:
      "Follow up with everyone or only people who have not submitted.",
    category: "Follow-ups",
    image_required: false,
    audience: "reminder",
    repeatable: true,
    fields: [field("message_content", "Reminder message")],
  },
  {
    id: "group_invite",
    message_type: "group_invite",
    label: "Group invitation",
    description: "Invite recipients to the official WhatsApp group.",
    category: "Getting started",
    image_required: true,
    audience: "standard",
    repeatable: false,
    fields: [
      field("group_invite_link", "WhatsApp group invite link", "url"),
      field("message_content", "Invitation message"),
    ],
  },
  {
    id: "update",
    message_type: "update",
    label: "Trip update",
    description:
      "Send an update using submission and document delivery filters.",
    category: "Trip updates",
    image_required: false,
    audience: "update",
    repeatable: true,
    fields: [field("message_content", "Update message")],
  },
];
export const historyCounts = {
  all: 12,
  sent: 9,
  not_sent: 1,
  delivery_left: 2,
  failed: 2,
};
export const historyEntry = {
  id: batchId,
  message_type: "document_update",
  message_preview:
    "Airport transfer details · Please meet the coordinator at Terminal 3 at 08:30. Your pickup time is confirmed.",
  created_at: now,
  updated_at: now,
  counts: historyCounts,
  rendered_message:
    "Dear Delegates\n\nAirport transfer details. Please meet the coordinator at Terminal 3 at 08:30.\n\nTeam Global Connect Travels",
};

export async function setupWorkspace(
  page: Page,
  options: { largeCatalog?: boolean; failFirstResend?: boolean } = {},
) {
  const group = fixtureGroup();
  const mutations: { path: string; body: Record<string, unknown> }[] = [];
  const previews: Record<string, unknown>[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  let resendCount = 0;
  const user = {
    id: "workspace-admin",
    email: "admin@example.test",
    full_name: "Workspace Admin",
    role: "agency_admin",
    agency_id: "workspace-agency",
    is_active: true,
    capabilities: [],
  };
  await page.context().addCookies([
    {
      name: "access_token",
      value: "synthetic-workspace-session",
      domain: "127.0.0.1",
      path: "/",
      httpOnly: true,
    },
  ]);
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      url = new URL(request.url()),
      path = url.pathname,
      method = request.method();
    if (path.endsWith("/auth/me")) return json(route, user);
    if (path === "/api/v1/ai-assistant/availability") return json(route, { enabled: false, allowed: false });
    if (path.endsWith("/auth/refresh"))
      return json(route, {
        status: "authenticated",
        user,
        token_type: "bearer",
        access_token_expires_at: "2099-01-01T00:00:00Z",
      });
    if (path.endsWith("/notifications/feed"))
      return json(route, { items: [], unread_count: 0, next_cursor: null });
    if (path.includes("/whatsapp/activities/"))
      return json(route, {
        activity_id: path.split("/").at(-1),
        kind: path.includes("/document/") ? "document" : "broadcast",
        title: "Trip message delivery",
        context_label: group.name,
        source_group_id: path.includes("/document/")
          ? "source-trip"
          : broadcastId,
        document_type: path.includes("/document/") ? "visa" : null,
        total: 2,
        queued: 2,
        sent: 0,
        failed: 0,
        delivery_unknown: 0,
        started_at: now,
        updated_at: now,
      });
    if (path === "/api/v1/whatsapp/groups" && method === "GET")
      return json(
        route,
        url.searchParams.get("archived") === "true"
          ? [
              {
                ...group,
                id: "archived-trip",
                name: "Singapore · September",
                is_archived: true,
              },
            ]
          : [
              group,
              ...[
                "Bali · Team retreat",
                "Prague · Business delegation",
                "Tokyo · Winter programme",
              ].map((name, i) => ({
                ...group,
                id: `other-${i}`,
                name,
                recipient_count: 26 + i * 38,
                total_contact_count: 26 + i * 38,
              })),
            ],
      );
    if (path === `/api/v1/whatsapp/groups/${broadcastId}` && method === "GET")
      return json(route, group);
    if (path.endsWith("/message-catalog"))
      return json(
        route,
        options.largeCatalog
          ? Array.from({ length: 100 }, (_, i) => ({
              ...catalog[0],
              id: `message-${i}`,
              label: `Travel update ${String(i + 1).padStart(3, "0")}`,
            }))
          : catalog,
      );
    if (path.endsWith("/recipient-roster"))
      return json(route, {
        items: [],
        counts: {
          all: 12,
          sent: 11,
          failed: 1,
          rejected: 0,
          replaced: 0,
          unidentified: 0,
        },
      });
    if (path.endsWith("/passenger-links"))
      return json(
        route,
        names.slice(0, 4).map((_, i) => ({
          group_id: "source-trip",
          passenger_id: `passenger-${i}`,
        })),
      );
    if (path.endsWith("/source-contacts"))
      return json(route, { sources: [], contacts: [], total_contacts: 0 });
    if (path.endsWith("/updates/preview") && method === "POST") {
      const body = request.postDataJSON();
      previews.push(body);
      const all = group.recipients.filter((person) => person.welcome_delivered);
      const audience =
        body.submission_status === "not_submitted" ? all.slice(-3) : all;
      return json(route, {
        group_id: "source-trip",
        audience: body,
        preview_token: "update-preview-token",
        template_name: "pending_v1",
        template_language: "en",
        can_send: true,
        configuration_error: null,
        recipients: audience.map((person) => ({
          audience_key: `recipient:${person.id}`,
          name: person.name,
          recipient_id: person.id,
          broadcast_group_id: broadcastId,
          passenger_id: null,
          phone_number: person.normalized_phone_number,
          phone_source: "imported",
          submission_status: "not_submitted",
          document_count: 0,
          confirmed_count: 0,
          eligible: true,
          reason: null,
          latest_update_status: null,
          latest_update_at: null,
        })),
      });
    }
    if (path.endsWith("/updates/send") && method === "POST") {
      const body = request.postDataJSON();
      mutations.push({ path, body });
      return json(route, {
        queued_count: body.audience_keys.length,
        passenger_count: body.audience_keys.length,
        message: "Queued",
        batches: [
          {
            batch_id: batchId,
            broadcast_group_id: broadcastId,
            queued_count: body.audience_keys.length,
          },
        ],
      });
    }
    if (path.endsWith("/preview") && method === "POST") {
      const body = request.postDataJSON();
      previews.push(body);
      const all = group.recipients.filter(
        (person) =>
          person.welcome_delivered &&
          (body.message_type !== "passport_link" ||
            body.include_previous_recipients ||
            person.id !== "person-0"),
      );
      const audience =
        body.update_submission === "not_submitted" ||
        body.audience === "not_submitted"
          ? all.slice(-3)
          : all;
      const ids: string[] =
        body.recipient_ids ?? audience.map((person) => person.id);
      const selected = audience.filter((person) => ids.includes(person.id));
      const content =
        body.message_content ??
        "Your airport transfer is confirmed. Please meet our coordinator at Terminal 3 at 08:30. We look forward to welcoming you to Dubai.";
      return json(route, {
        message_type: body.message_type,
        template_name: `${body.message_type}_approved`,
        recipient_id: body.recipient_id ?? selected[0]?.id ?? all[0].id,
        recipient_name: selected[0]?.name ?? all[0].name,
        recipient_count: ids.length,
        audience_recipient_ids: audience.map((person) => person.id),
        audience_recipient_count: audience.length,
        eligible_recipient_count: selected.length,
        already_sent_count: 0,
        in_progress_count: 0,
        uncertain_recipient_count: 0,
        welcome_required_count: 0,
        header_image_id: ["welcome", "passport_link", "group_invite"].includes(
          body.message_type,
        )
          ? "synthetic-saved-header"
          : null,
        message_content: content,
        passport_intro:
          body.passport_intro ??
          "Please submit your travel documents for the Dubai trip.",
        passport_link:
          body.passport_link ?? "https://example.test/documents/dubai",
        group_invite_link:
          body.group_invite_link ?? "https://chat.whatsapp.com/example",
        rendered_message: `Dear Delegates\n\nGreetings from Global Connect Travels\n\n${content}\n\nRegards,\nTeam Global Connect Travels`,
        content_source: "default",
        header_parameter_values: [],
        parameter_values: [content],
      });
    }
    if (
      path.endsWith("/whatsapp-preview") &&
      path.includes("/document-distribution/")
    )
      return json(route, {
        group_id: "source-trip",
        batch_id: "document-batch",
        preview_token: "frozen-preview-token",
        template_name: "document_approved",
        template_configured: true,
        can_send: true,
        configuration_error: null,
        message_content_1: "Your travel documents are attached.",
        message_content_2: "Please check the details before travelling.",
        summary: {
          total_passengers: 4,
          ready: 2,
          retryable: 0,
          already_sent: 1,
          in_progress: 0,
          blocked: 0,
        },
        recipients: names.slice(0, 4).map((name, i) => ({
          passenger_id: `passenger-${i}`,
          passenger_name: name,
          document_id: `doc-${i}`,
          document_filename: `${name}_Visa.pdf`,
          recipient_id: `person-${i}`,
          broadcast_group_id: i === 3 ? "another-broadcast" : broadcastId,
          phone_number: group.recipients[i].normalized_phone_number,
          delivery_status: i === 0 ? "already_sent" : "ready",
          eligible: i !== 0,
          resend_allowed: i === 0,
          reason: i === 0 ? "Previously delivered" : "Ready to send",
          message_preview: "Your travel documents are attached.",
        })),
      });
    if (method === "POST" && path.endsWith("/whatsapp-send")) {
      mutations.push({ path, body: request.postDataJSON() });
      return json(route, {
        send_batch_id: "document-send",
        queued_count: 2,
        skipped_count: 0,
        message: "Queued",
      });
    }
    if (path.endsWith("/messages"))
      return json(route, {
        items: [
          historyEntry,
          {
            ...historyEntry,
            id: "earlier-update",
            message_preview:
              "Travel document deadline · Please submit your documents by Friday.",
            created_at: "2026-10-15T09:00:00Z",
          },
        ],
        total: 2,
        offset: 0,
        limit: 25,
      });
    if (/\/messages\/[^/]+\/recipients$/.test(path)) {
      const statusFilter = url.searchParams.get("status_filter");
      const rows = group.recipients.map((person, i) => ({
        message_log_id: `log-${i}`,
        recipient_id: person.id,
        name: person.name,
        phone_number: `91980000${String(i).padStart(4, "0")}`,
        current_phone_number: person.normalized_phone_number,
        status:
          i === 1
            ? "failed"
            : i === 2
              ? "delivery_unknown"
              : i === 3
                ? "queued"
                : "read",
        error_message:
          i === 1
            ? "The message could not be delivered. Check the WhatsApp number."
            : i === 2
              ? "Awaiting a confirmed provider outcome. Resending is unavailable."
              : null,
        rendered_message:
          "Saved airport transfer details for this individual send.",
        updated_at: now,
        removed: false,
        can_resend: ![2, 3].includes(i),
      }));
      const items = rows.filter(
        (row) =>
          (statusFilter !== "failed" ||
            ["failed", "delivery_unknown"].includes(row.status)) &&
          (!url.searchParams.get("q") ||
            row.name
              .toLowerCase()
              .includes(url.searchParams.get("q")!.toLowerCase())),
      );
      return json(route, {
        items,
        counts: historyCounts,
        total: items.length,
        offset: 0,
        limit: 50,
      });
    }
    if (/\/messages\/[^/]+$/.test(path)) return json(route, historyEntry);
    if (/\/document-distribution\/groups\/source-trip\/[^/]+$/.test(path))
      return json(route, {
        group_id: "source-trip",
        document_type: "visa",
        unmatched_documents: [],
        review_rows: [
          ...names.slice(0, 5).map((name, i) => ({
            passenger_id: `passenger-${i}`,
            passenger_name:
              i === 4 ? "Unrelated passenger must stay hidden" : name,
            passport_number: `TEST${String(i).padStart(4, "0")}`,
            assigned_pdf_count: i === 3 ? 0 : 1,
            documents:
              i === 3
                ? []
                : [
                    {
                      id: `doc-${i}`,
                      original_filename: `${name.replaceAll(" ", "_")}_Visa.pdf`,
                      match_confidence: 0.97,
                      source: "manual",
                      delivery_status: i === 2 ? "not_sent" : "read",
                      can_resend: i !== 2,
                      sent_to: group.recipients[i].normalized_phone_number,
                      url: "https://example.test/visa.pdf",
                      document_type: "visa",
                      match_status: "matched",
                    },
                  ],
          })),
        ],
      });
    if (method === "PATCH" && /\/recipients\/[^/]+$/.test(path)) {
      const body = request.postDataJSON();
      mutations.push({ path, body });
      const person = group.recipients.find((item) =>
        path.endsWith(`/${item.id}`),
      )!;
      person.phone_number = body.phone_number;
      person.normalized_phone_number = body.phone_number.replace(/\D/g, "");
      return json(route, person);
    }
    if (
      method === "POST" &&
      (path.endsWith("/resend") || path.endsWith("/resend-update"))
    ) {
      const body = request.postDataJSON();
      mutations.push({ path, body });
      resendCount++;
      if (options.failFirstResend && resendCount === 1)
        return json(
          route,
          {
            detail:
              "The send request has not been confirmed. Check its status.",
          },
          503,
        );
      return json(route, {
        batch_id: "resend-batch",
        queued: 1,
        sent: 0,
        failed: 0,
        delivery_unknown: 0,
        results: [],
      });
    }
    if (method === "POST" && path.endsWith("/send")) {
      mutations.push({ path, body: request.postDataJSON() });
      return json(route, {
        batch_id: batchId,
        queued: 11,
        sent: 0,
        failed: 0,
        delivery_unknown: 0,
        results: [],
      });
    }
    if (method === "GET") return json(route, []);
    return json(
      route,
      { detail: "Unexpected synthetic mutation blocked" },
      403,
    );
  });
  return { group, mutations, previews, errors };
}
