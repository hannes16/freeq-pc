"""Small, failure-safe bridge for speech routed through Prism."""

from __future__ import annotations


class ScreenReader:
    """Use Prism's best available speech backend without blocking startup."""

    def __init__(self) -> None:
        self.context = None
        self.output = None
        try:
            from prism import Context

            self.context = Context()
            candidate = self.context.create_best()
            if candidate.features.supports_speak:
                self.output = candidate
        except Exception:
            # The game and its original recorded accessibility audio remain
            # usable when Prism or a speech backend is unavailable.
            self.context = None
            self.output = None

    def speak(self, text: str, *, interrupt: bool = True) -> bool:
        if self.output is None:
            return False
        try:
            self.output.speak(text, interrupt=interrupt)
        except Exception:
            return False
        return True
