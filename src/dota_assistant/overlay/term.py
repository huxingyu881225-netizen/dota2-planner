"""Terminal fallback output for the coach loop (no GUI needed)."""
from __future__ import annotations


class TermDisplay:
    def __init__(self, quiet: bool = False):
        self.quiet = quiet

    def show(self, minute: float, text: str):
        if self.quiet:
            return
        print(f"[{minute:04.1f}min] {text}")

    def ask_position(self, hero: str, options: list[str]) -> str:
        """终端选择位置：列出库里该英雄已有的位置供用户选。"""
        print(f"英雄 {hero} 在库里有多个位置，请选择：")
        for i, o in enumerate(options):
            print(f"  [{i}] {o}")
        chosen = None
        while chosen not in options:
            raw = input(f"输入序号或位置名 {options}: ").strip()
            if raw.isdigit() and int(raw) < len(options):
                chosen = options[int(raw)]
            else:
                chosen = raw
        return chosen
