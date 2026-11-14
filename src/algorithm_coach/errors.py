"""Define safe domain errors shared by the core and its adapters."""

from typing import Any


class CoachError(Exception):
    """Carry a stable error code and safe details for clients."""

    def __init__(self, code: str, message: str, details: Any = None) -> None:
        """Inputs: code, message, and optional details. Outputs: a domain error.

        Logic: retain safe client fields and initialize Exception.
        Dependencies: Python's Exception type.
        """
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict:
        """Inputs: none. Outputs: a JSON-ready error object.

        Logic: expose stable fields without a traceback.
        Dependencies: this error's saved attributes.
        """
        return {"code": self.code, "message": self.message, "details": self.details}
