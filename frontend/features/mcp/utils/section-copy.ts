// Presentation text only. The server catalog owns support and permissions.
const READ_DESCRIPTIONS: Record<string, string> = {
  dashboard: "View passport totals, recent passengers and saved dashboard summaries.",
  my_tour: "Look up assigned tour groups, passengers and attendance sessions.",
  all_groups: "Find groups and passengers, review passport details, extraction results and processing status.",
  group_links: "View group link settings, collection fields, custom questions and linked broadcasts.",
  whatsapp: "Review broadcasts, contact matching, saved message status and delivery history.",
  operations_inbox: "View inbox connection status and saved email record information.",
  documents: "Review document matches, passenger assignments, missing documents and delivery or renaming history.",
  coordinators: "View coordinator accounts and their assigned groups.",
  rooming_lists: "View hotels, rooms, passenger selections, room allocations and recorded check-ins.",
  menu: "View menu categories, dishes, meal plans and plan entries.",
  tour_ops: "View coordinator assignments, tour activities, passenger QR codes and attendance records.",
  gc_app: "View app group access, published itineraries, announcements and notification history.",
  manager: "View manager directory information, group access and administrative account counts.",
  staff: "View staff directory information, group access and administrative account counts.",
  analytics: "View passport analytics and group summary totals.",
  audit_logs: "Review saved business activity, account changes and app audit history.",
  old_data: "View retained records, export history and passport retention schedules.",
  settings: "View business settings, defaults and WhatsApp template configuration.",
};

const WRITE_DESCRIPTIONS: Record<string, string> = {
  all_groups: "Correct selected passenger contact details and supported custom fields after reviewing the current record.",
  group_links: "Create groups and configure upload links, collection fields, custom questions and linked broadcasts.",
  coordinators: "Create coordinator accounts. Account activation is completed in the dashboard; group assignments are controlled under Tour Ops.",
  rooming_lists: "Create and configure hotels, select passengers, set VIP preferences and allocate rooms.",
  menu: "Create and update menu categories, dishes and meal plans, and edit plan entries.",
  tour_ops: "Assign coordinators to groups and create attendance activities.",
  gc_app: "Create client manager accounts, configure group access and photos, publish itineraries, and prepare announcements or notifications. Sending notifications requires final confirmation.",
  manager: "Create manager accounts and grant access to selected groups. Account activation is completed in the dashboard.",
  staff: "Create staff accounts and grant access to selected groups. Account activation is completed in the dashboard.",
  whatsapp_broadcasts: "Create and edit broadcasts, import or add contacts, and prepare messages or reminders. Sending requires final confirmation.",
  document_delivery: "Upload PDFs, review passenger matches and save document assignments. Sending documents requires final confirmation.",
  group_excel_imports: "Upload group workbooks, preview the proposed passenger changes and import the reviewed data.",
  exports: "Prepare and download available passenger spreadsheets, passport images, tracking, rooming and document assignment reports.",
};

export function mcpSectionDescription(mode: "read" | "write", id: string, fallback?: string) {
  const descriptions = mode === "read" ? READ_DESCRIPTIONS : WRITE_DESCRIPTIONS;
  return descriptions[id] ?? fallback ?? `Use the available ${mode} actions for this section.`;
}
