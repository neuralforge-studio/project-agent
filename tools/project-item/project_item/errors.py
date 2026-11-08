"""Errors of the item domain, independent of session and provider adapters."""


class ItemError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
