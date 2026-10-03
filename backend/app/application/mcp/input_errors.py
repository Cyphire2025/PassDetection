"""Code-owned public input failures shared by services and MCP transports."""


class MCPInputError(ValueError):
    """Only raise with reviewed messages, never provider/database or business text."""

    def __init__(self, code: str, message: str):
        self.code, self.message = code, message
        super().__init__(message)
