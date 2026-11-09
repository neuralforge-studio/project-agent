"""The error every project-item layer raises. It has no dependency, so each layer can import it."""
from __future__ import annotations


class ItemError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
