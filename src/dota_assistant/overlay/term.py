"""Terminal fallback output for the coach loop (no GUI needed)."""
from __future__ import annotations


class TermDisplay:
    def __init__(self, quiet: bool = False):
        self.quiet = quiet

    def show(self, minute: float, text: str):
        if self.quiet:
            return
        print(f"[{minute:04.1f}min] {text}")
