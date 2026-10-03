"""Transport-neutral failures for the shared office tracker workflow."""


class TravelTrackerError(ValueError):
    def __init__(self, *, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
