"""Plan admission: fragment the *problem*, never the text.

``swarmbly_v0``'s planner is a measurement harness: it honours ``N`` exactly
because ``N`` is the independent variable of its sweeps, and when a prompt has
no structure it falls back to slicing by tokens. That fallback is right for an
experiment and wrong for a product: it produces partial sub-requests ("comets,
drums, electrons. List 5"), which SPEC §14b.7 forbids and
``FINDING_2026-09-04`` documents.

This adapter (upstream untouched) admits a distributed plan only when the
upstream segmenter takes a *structural* path:

1. **enumerated** — a batch of labelled items; the operation (preamble)
   travels with every fragment (``planner.split_enumerated``);
2. **reference** — questions linked to the material that answers them
   (``planner.reference_map``).

A prompt with an inline list ("…the following items: apples, bridges,
comets…") is normalised locally into labelled items first, which is a
lossless rewrite of the same request. Anything else is not admitted and runs
locally, with the reason shown in the monitor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

MIN_ITEMS = 3
ATTACHMENT_MARKER = "Attached file `"
MAX_ITEM_WORDS = 8

# "<operation> <noun phrase>: a, b, c, d and e. <rest>"
_INLINE_LIST = re.compile(
    r"^(?P<pre>.*?:)\s*(?P<items>[^:.;\n]+?(?:,\s*[^:.;\n]+?){2,}(?:,?\s+(?:and|y|e)\s+[^:.;\n]+?)?)"
    r"(?P<post>\.(?:\s.*)?|\s*)$",
    re.S | re.I)


@dataclass
class Admission:
    admitted: bool
    path: str                       # enumerated | reference | none
    reason: str
    prompt: str                     # the (possibly normalised) prompt planned
    n_tasks: int = 0
    normalised: bool = False
    preamble: str = ""              # the operation shared by every fragment
    items: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"admitted": self.admitted, "path": self.path,
                "reason": self.reason, "n_tasks": self.n_tasks,
                "normalised_inline_list": self.normalised,
                "n_items": len(self.items)}


def normalise_inline_list(prompt: str) -> str | None:
    """Rewrite "op: a, b, c and d. rest" as labelled items, or return None.

    Lossless: the same items, in order, with the operation unchanged. Only
    short items (≤ 8 words) qualify, so prose with commas is left alone.
    """
    text = (prompt or "").strip()
    if "\n1." in text or "\n1)" in text:
        return None
    match = _INLINE_LIST.match(text)
    if not match:
        return None
    raw = re.split(r",\s*|\s+(?:and|y|e)\s+", match.group("items").strip())
    items = [i.strip().strip(".") for i in raw if i and i.strip().strip(".")]
    if len(items) < MIN_ITEMS:
        return None
    if any(len(i.split()) > MAX_ITEM_WORDS for i in items):
        return None
    pre = match.group("pre").strip()
    post = (match.group("post") or "").strip().lstrip(".").strip()
    body = "\n".join(f"{n}. {item}" for n, item in enumerate(items, 1))
    out = f"{pre}\n{body}"
    if post:
        out += f"\n\n{post}"
    return out


def admit(prompt: str, *, n_max: int, n_workers: int) -> Admission:
    """Decide whether (and how) a prompt may be fragmented.

    ``n_workers`` is the swarm's concurrent capacity (sum of the workers'
    advertised slots); N never exceeds ``n_max`` nor twice that capacity.
    """
    from swarmbly_v0 import planner

    if ATTACHMENT_MARKER in (prompt or ""):
        # The material of an attached file must travel with the question that
        # refers to it; splitting it is not yet safe. Answered locally.
        return Admission(False, "none", "messages with attached files are answered "
                         "locally in this version", prompt, 1)
    candidate = prompt
    normalised = False
    enumerated = planner.split_enumerated(candidate)
    if enumerated is None:
        rewritten = normalise_inline_list(prompt)
        if rewritten is not None:
            enumerated = planner.split_enumerated(rewritten)
            if enumerated is not None:
                candidate, normalised = rewritten, True

    upper = max(1, min(int(n_max), max(2, int(n_workers))))
    if enumerated is not None:
        preamble, items, _post = enumerated
        n = min(upper, len(items), planner.suggest_n_tasks(candidate, maximum=upper))
        n = max(2, n) if len(items) >= 2 else 1
        if n < 2:
            return Admission(False, "enumerated", "too few items to fragment",
                             candidate, 1, normalised, preamble, items)
        return Admission(True, "enumerated",
                         f"enumerated batch of {len(items)} items; the operation "
                         "travels with every fragment", candidate, n, normalised,
                         preamble, items)

    mapping = planner.reference_map(candidate)
    if mapping is not None and planner.references_are_recoverable(candidate):
        n = min(upper, len(mapping))
        if n >= 2:
            return Admission(True, "reference",
                             "questions linked to the material that answers them",
                             candidate, n)
    return Admission(False, "none",
                     "no structural partition (only text slicing would split it; "
                     "SPEC §14b.7 forbids partial sub-requests)", prompt, 1)
