"""The label's text as lines, with the government warning separated out.

Field matching searches only non-warning lines, so words inside the warning
(e.g. "alcoholic beverages") can never confirm a field.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .normalize import clean, normalize
from .warning import CANONICAL_WARNING

_WARNING_NORM = normalize(CANONICAL_WARNING)


@dataclass
class Span:
    """One line, or two adjacent lines joined (for values that wrap)."""

    lines: tuple[int, ...]
    text: str  # cleaned, original case
    norm: str  # comparison form


@dataclass
class LabelText:
    lines: list[str]
    warning_lines: set[int] = field(default_factory=set)
    spans: list[Span] = field(default_factory=list)

    @classmethod
    def from_full_text(cls, full_text: str) -> "LabelText":
        lines = [clean(line) for line in full_text.splitlines()]
        lt = cls(lines=lines)
        for i, line in enumerate(lines):
            n = normalize(line)
            if not n:
                continue
            if "government warning" in n or (len(n) >= 12 and fuzz.partial_ratio(n, _WARNING_NORM) >= 90):
                lt.warning_lines.add(i)
        content = [i for i, line in enumerate(lines) if normalize(line) and i not in lt.warning_lines]
        for i in content:
            lt.spans.append(Span((i,), lines[i], normalize(lines[i])))
        for a, b in zip(content, content[1:]):
            if b == a + 1:
                text = f"{lines[a]} {lines[b]}"
                lt.spans.append(Span((a, b), text, normalize(text)))
        return lt

    @property
    def non_warning_text(self) -> str:
        return "\n".join(l for i, l in enumerate(self.lines) if i not in self.warning_lines)
