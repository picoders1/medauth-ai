"""Enumerate every provision in a policy document, at every hierarchy level.

Span verification answers *"is this criterion faithful to the source?"*. It cannot
answer *"did we identify every criterion that should have been represented?"* -
nothing about checking the criteria you wrote down tells you about the ones you did
not.

Answering the second question needs the denominator: every provision the document
contains, enumerated mechanically rather than by re-reading and hoping. This module
produces that denominator. Classification of each provision is a human judgement and
is recorded separately, but the *list* must be exhaustive or a completeness claim is
an impression.

Provisions carry their full hierarchical path - ``(d)(1)(i)`` - resolved through
:class:`~app.policy.hierarchy.HierarchyTracker`, because markers overlap and a path
built from markers read in isolation would collide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.policy.criteria import SectionLike
from app.policy.hierarchy import HierarchyTracker

__all__ = ["Provision", "extract_provisions", "provision_id"]

_MARKER = re.compile(r"^\(([A-Za-z0-9]{1,5})\)\s*")

#: Provisions shorter than this are structural fragments - a heading echo, a
#: cross-reference stub - rather than statements that could bear on a decision.
#: They are still enumerated; the flag lets a reviewer skip them deliberately
#: rather than them being silently dropped.
_SUBSTANTIVE_CHARS = 60


@dataclass(frozen=True, slots=True)
class Provision:
    """One enumerated provision, addressable and classifiable."""

    policy_id: str
    policy_version: str
    section_path: str
    path: str
    level: int
    text: str
    page: int
    #: Words a coverage requirement tends to use. A weak signal, recorded to help a
    #: reviewer prioritise - never used to decide relevance automatically.
    obligation_markers: tuple[str, ...] = field(default_factory=tuple)

    @property
    def id(self) -> str:
        return provision_id(self.policy_id, self.policy_version, self.section_path, self.path)

    @property
    def is_substantive(self) -> bool:
        return len(self.text.strip()) >= _SUBSTANTIVE_CHARS

    @property
    def looks_obligatory(self) -> bool:
        return bool(self.obligation_markers)


def provision_id(policy_id: str, policy_version: str, section_path: str, path: str) -> str:
    policy = re.sub(r"[^A-Z0-9]+", "_", policy_id.upper()).strip("_")
    version = re.sub(r"[^0-9]+", "", policy_version)
    section = re.sub(r"[^A-Za-z0-9]+", "", section_path)[:20] or "root"
    marker = re.sub(r"[^A-Za-z0-9]+", "", path) or "0"
    return f"{policy}_{version}_{section}_{marker}"


#: Language that signals a requirement, a condition or an exclusion. Deliberately
#: broad: a false positive costs a reviewer a glance, a false negative hides a
#: provision from the completeness walk entirely.
_OBLIGATION_TERMS = (
    "must",
    "shall",
    "may not",
    "is not covered",
    "are not covered",
    "excluded",
    "required",
    "requires",
    "only if",
    "only when",
    "except",
    "unless",
    "conditions",
    "reasonable and necessary",
    "documented",
    "prior to",
    "no more than",
    "at least",
    "within",
    "eligible",
    "qualif",
)


def _markers(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(term for term in _OBLIGATION_TERMS if term in lowered)


def extract_provisions(
    sections: tuple[SectionLike, ...], *, policy_id: str, policy_version: str
) -> tuple[Provision, ...]:
    """Enumerate every marked provision across every section.

    Text before the first marker in a section is emitted as the section's own
    provision with an empty path, so a lead-in paragraph carrying a condition is
    not lost simply because it is unnumbered.
    """
    provisions: list[Provision] = []

    for section in sections:
        tracker = HierarchyTracker()
        stack: dict[int, str] = {}
        pending: list[str] = []
        current_path = ""
        current_level = 0

        def flush(path: str, level: int, *, lines: list[str], sec: SectionLike) -> None:
            # `lines` and `sec` are passed explicitly rather than closed over:
            # `pending` is rebound on every marker, and a closure that reads the
            # enclosing binding would be correct only by accident of call order.
            body = " ".join(line.strip() for line in lines if line.strip()).strip()
            if not body:
                return
            provisions.append(
                Provision(
                    policy_id=policy_id,
                    policy_version=policy_version,
                    section_path=sec.path,
                    path=path,
                    level=level,
                    text=body,
                    page=sec.page_from,
                    obligation_markers=_markers(body),
                )
            )

        for raw_line in section.text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            classified = tracker.classify(line)
            if classified is None:
                pending.append(line)
                continue

            marker, level = classified
            flush(current_path, current_level, lines=pending, sec=section)
            pending = [_MARKER.sub("", line, count=1)]

            depth = int(level)
            stack[depth] = marker
            for deeper in [k for k in stack if k > depth]:
                del stack[deeper]
            current_path = "".join(f"({stack[k]})" for k in sorted(stack))
            current_level = depth

        flush(current_path, current_level, lines=pending, sec=section)

    return tuple(provisions)
