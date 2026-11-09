"""Errors exposed by the session CLI and the project API."""


class SessionError(Exception):
    """A command failed without changing its target or hiding partial work."""

    def __init__(self, code, message, exit_code=3, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.details = details or {}

    def as_dict(self):
        return {"code": self.code, "message": self.message, "details": self.details}
