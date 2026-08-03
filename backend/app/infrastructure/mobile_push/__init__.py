"""Durable mobile push worker integration."""

MOBILE_PUSH_DISPATCH_TASK = "mobile.dispatch_push_notifications"
MOBILE_PUSH_RECEIPT_TASK = "mobile.reconcile_push_receipts"

__all__ = ["MOBILE_PUSH_DISPATCH_TASK", "MOBILE_PUSH_RECEIPT_TASK"]
