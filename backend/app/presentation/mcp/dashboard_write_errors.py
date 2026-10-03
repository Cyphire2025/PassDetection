"""Actionable public failures without exception text, source cells or credentials."""

DASHBOARD_WRITE_ERRORS = {
    "invalid_dashboard_edit": "Inspect this workflow's documented fields and current revision, then provide only the requested changes.",
    "workflow_revision_changed": "This record changed after inspection. Review its current values and revision before submitting a new intended edit.",
    "workflow_resource_unavailable": "The selected record is unavailable in that agency or group. Resolve the exact current target before changing it.",
    "workflow_invalid_configuration": "The current dashboard rules reject this configuration. Review the documented options and correct the selected values.",
    "workflow_access_denied": "The current account or selected resource no longer allows this workflow.",
    "workflow_retired": "This dashboard action has been retired. Inspect the current supported workflow instead.",
    "workflow_history_limit": "This edit exceeds the bounded retained-history limit. Select a smaller group or plan; no change was applied.",
    "workflow_result_limit": "This edit exceeds the bounded response limit. No change was applied; choose a smaller target.",
    "workflow_receipt_unavailable": "The original resource has moved or is no longer available. This saved receipt does not authorize access to its new scope.",
    "invalid_broadcast_write": "Choose valid broadcast details, support contacts and bounded contacts. Recipient opt-in must be explicitly confirmed.",
    "broadcast_unavailable": "The selected broadcast is unavailable or archived in that agency.",
    "broadcast_revision_changed": "The broadcast changed after inspection. Review its current details before applying a new intended change.",
    "broadcast_source_limit": "This broadcast exceeds the bounded edit limit. Select a smaller list; no change was applied.",
    "document_assignment_source_limit": "The complete document lane exceeds this workflow's review limit. Select a smaller lane or use the dashboard to review it.",
    "document_assignment_revision_changed": "Files, batches or assignments changed after review. Inspect the complete lane again before saving.",
    "document_assignment_lane_empty": "This group has no uploaded batches in the selected document lane.",
    "document_assignment_processing": "Document processing is still running. Wait for it to finish, then inspect and review the assignments again.",
    "document_assignment_receipt_unavailable": "The saved batches are no longer available in their original group and document lane.",
}
