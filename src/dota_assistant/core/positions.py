"""Position enumeration and normalization.

Canonical positions (from the requirement):
    carry, mid, offline, offlane_support, safelane_support

We accept a few aliases at parse time and normalize to canonical names.
"""
from __future__ import annotations

from enum import Enum


class Position(str, Enum):
    CARRY = "carry"
    MID = "mid"
    OFFLINE = "offline"
    OFFLANE_SUPPORT = "offlane_support"
    SAFELANE_SUPPORT = "safelane_support"

    @property
    def display(self) -> str:
        return {
            "carry": "Carry (1号位)",
            "mid": "Mid (2号位)",
            "offline": "Offline (3号位)",
            "offlane_support": "Offlane Support (4号位)",
            "safelane_support": "Safelane Support (5号位)",
        }[self.value]


# aliases -> canonical
_ALIASES = {
    "carry": "carry",
    "c": "carry",
    "1": "carry",
    "pos1": "carry",
    "safelane": "carry",
    "mid": "mid",
    "m": "mid",
    "2": "mid",
    "pos2": "mid",
    "middle": "mid",
    "offline": "offline",
    "off": "offline",
    "3": "offline",
    "pos3": "offline",
    "offlane": "offline",
    "offlane_support": "offlane_support",
    "pos4": "offlane_support",
    "4": "offlane_support",
    "offlane support": "offlane_support",
    "safelane_support": "safelane_support",
    "pos5": "safelane_support",
    "5": "safelane_support",
    "safelane support": "safelane_support",
    "support": "safelane_support",
    "hard support": "safelane_support",
}


def normalize_position(raw: str) -> str:
    """Return canonical position name, raising ValueError if unknown."""
    key = (raw or "").strip().lower().replace("-", "_")
    canonical = _ALIASES.get(key)
    if canonical is None:
        raise ValueError(
            f"Unknown position {raw!r}. Expected one of: "
            + ", ".join(p.value for p in Position)
        )
    return canonical


def is_valid_position(raw: str) -> bool:
    try:
        normalize_position(raw)
        return True
    except ValueError:
        return False


ALL_POSITIONS = [p.value for p in Position]
