"""Persisted standalone ECR states shared by application and model validation.

Cancellation currently removes an unclaimed batch; it is not a persisted state.
Retries move failed items back to queued and clear their result.
"""

ECR_BATCH_STATES = ("uploading", "queued", "processing", "completed", "completed_with_errors")
ECR_ITEM_STATES = ("queued", "processing", "completed", "failed")
ECR_RESULTS = ("ECR", "NA", "NEEDS_REVIEW")


def sql_values(values: tuple[str, ...]) -> str:
    """Render only the fixed, developer-owned state vocabulary, never user input."""
    return ",".join(repr(value) for value in values)
