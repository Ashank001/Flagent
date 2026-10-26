"""
exceptions.py — Flagent SDK Exceptions
"""


class FlagentError(Exception):
    """Base exception for all Flagent SDK errors."""
    pass


class FlagentBlocked(FlagentError):
    """Raised in enforce mode when raise_on_alert=True and the session is
    classified as 'alert'.

    Attributes:
        score_result:  The full ScoreResult that triggered the block.
    """

    def __init__(self, message: str, score_result=None):
        super().__init__(message)
        self.score_result = score_result
