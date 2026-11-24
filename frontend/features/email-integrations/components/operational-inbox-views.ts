import { AlertTriangle, CheckCircle2, Clock3, FileEdit, Hourglass, Inbox, type LucideIcon } from "lucide-react";
import type { EmailOperationalInboxView } from "../types";

export const INBOX_VIEWS: ReadonlyArray<{
  value: EmailOperationalInboxView;
  label: string;
  description: string;
  icon: LucideIcon;
}> = [
    {
      value: "needs_attention",
      label: "Needs attention",
      description: "Approvals, failures, uncertain matches, and required replies",
      icon: AlertTriangle,
    },
    {
      value: "upcoming_deadlines",
      label: "Deadlines",
      description: "Upcoming and overdue operational commitments",
      icon: Clock3,
    },
    {
      value: "drafts_ready",
      label: "Drafts ready",
      description: "Prepared replies that still require manual review",
      icon: FileEdit,
    },
    {
      value: "waiting",
      label: "Waiting",
      description: "Analysis still being prepared or awaiting completion",
      icon: Hourglass,
    },
    {
      value: "completed_automatically",
      label: "Analysis complete",
      description: "AI review finished with no open decisions or prepared work",
      icon: CheckCircle2,
    },
    {
      value: "all_activity",
      label: "All activity",
      description: "Every retained operational email outcome",
      icon: Inbox,
    },
  ];

