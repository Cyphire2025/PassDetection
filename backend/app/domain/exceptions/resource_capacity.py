"""Retryable resource admission failures; no framework or transport dependency."""

from app.domain.exceptions.exceptions import DependencyUnavailableError


class ImageProcessingBusy(DependencyUnavailableError):
    retry_after_seconds = 5

    def __init__(self) -> None:
        super().__init__("Image processing is busy. Please try again shortly.")
        self.code = "IMAGE_PROCESSING_BUSY"
