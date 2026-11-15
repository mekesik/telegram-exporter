"""Tiny terminal progress helper (no external dependencies)."""

from __future__ import annotations

import sys


class Progress:
    def __init__(self, enabled: bool = True, stream=None) -> None:
        self.stream = stream or sys.stderr
        self.enabled = bool(enabled and getattr(self.stream, "isatty", lambda: False)())
        self._last_len = 0

    def status(self, text: str) -> None:
        if not self.enabled:
            return
        padding = " " * max(0, self._last_len - len(text))
        self.stream.write("\r" + text + padding)
        self.stream.flush()
        self._last_len = len(text)

    def clear(self) -> None:
        if not self.enabled or not self._last_len:
            return
        self.stream.write("\r" + " " * self._last_len + "\r")
        self.stream.flush()
        self._last_len = 0

    def line(self, text: str = "") -> None:
        self.clear()
        if self.enabled:
            self.stream.write(text + "\n")
            self.stream.flush()
        else:
            print(text)

    def done(self) -> None:
        if self.enabled and self._last_len:
            self.stream.write("\n")
            self.stream.flush()
            self._last_len = 0
