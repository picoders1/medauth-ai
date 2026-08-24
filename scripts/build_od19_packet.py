"""Build an OD-19 reviewer packet: what logic governs one policy version.

FOCUS-001 asked one question about one criterion. OD-19 is the wider one behind it:
six of eight policy versions carry alternative, conditional, exception, exclusion or
threshold wording that nobody has read, so no decision logic is declared for them and
`decide()` refuses to adjudicate anything on them.

This builds the same shape of packet the FOCUS-001 review used - question, verbatim
sources, closed option set, consequences, no recommendation - driven by
`data/review/od19_questions.yaml` so the framing is reviewable data rather than
buried in code.

**Every quoted provision is located in the source document at build time.** A quote
that no longer matches fails the build. That is the lesson from the C08 excerpt,
which over-ran its paragraph and trailed off mid-word in a packet a reviewer was
meant to act on.

    uv run python scripts/build_od19_packet.py --question OD-19-410.33
    uv run python scripts/build_od19_packet.py --question OD-19-410.33 --write

Like `build_focus_decision.py`, `--write` refuses to rebuild over an answered
decision. This script cannot answer the question it asks: the gate it emits is
constructed by `DecisionGate.pending()` and there is no other constructor.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from app.review.decision_gate import DecisionGate

REPO = Path(__file__).resolve().parents[1]
QUESTIONS = REPO / "data/review/od19_questions.yaml"
CRITERIA = REPO / "data/criteria/inventory.jsonl"
LOGIC = REPO / "data/policy_logic/inventory.json"
ADMISSIBILITY = REPO / "data/review/slice_admissibility.json"
CMS = REPO / "data/cms"

#: Which admissibility checks this decision would resolve. Excluded from "other
#: blockers" for the same reason FOCUS-001's own checks are: including them makes
#: the analysis circular - it would tell the reviewer that even after declaring the
#: logic, the policy stays blocked by the logic not being declared.
RESOLVED_BY_THIS_DECISION = ("semantics_declared", "production_semantics_executable")


class PacketBuildError(RuntimeError):
    """The packet could not be built from the sources it cites."""


class DecisionResetRefused(RuntimeError):
    """A rebuild would have destroyed a recorded decision."""


_ANSWERED = ("SUBMITTED", "ACCEPTED", "REJECTED", "SUPERSEDED")


def refuse_destructive_rebuild(existing: str | None, rebuilt: str) -> None:
    """Refuse a rebuild over an answered decision. Same rule as FOCUS-001's builder.

    There is no `--force` and no archival escape here: an OD-19 packet is generated
    from committed inputs, so a PENDING rebuild that differs is a legitimate
    regeneration, and an answered one is never overwritten at all.
    """
    if existing is None:
        return
    status = str(json.loads(existing).get("status", "UNKNOWN"))
    if status in _ANSWERED:
        raise DecisionResetRefused(
            f"the existing record is {status}: a reviewer has answered this question, "
            "and rebuilding would replace their decision and its attribution with a "
            "blank template. A superseding answer is recorded as a new "
            "decision_version beside the old one, never over it."
        )


def _load_question(question_id: str) -> dict[str, Any]:
    spec = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    for entry in spec["questions"]:
        if entry["id"] == question_id:
            return dict(entry)
    known = [e["id"] for e in spec["questions"]]
    raise PacketBuildError(f"{question_id!r} is not in {QUESTIONS.name}. Known: {known}")


def _source_path(policy_id: str, version: str) -> Path:
    stem = policy_id.replace("42 CFR ", "CFR-").replace(".", "_")
    path = CMS / f"{stem}-{version}.md"
    if not path.exists():
        raise PacketBuildError(f"no source document at {path.relative_to(REPO)}")
    return path


def _locate(text: str, provision: dict[str, Any]) -> str:
    """Pull one provision out of the source, verbatim, bounded explicitly.

    `starts_with` anchors the opening; the quote ends at the paragraph break unless
    `through` names a later sentence to include. Nothing is inferred about where a
    provision stops - the C08 excerpt over-ran precisely because its end was left to
    a character count.
    """
    start = text.find(provision["starts_with"])
    if start < 0:
        raise PacketBuildError(
            f"provision {provision['label']!r} does not appear in the source: "
            f"{provision['starts_with']!r}"
        )

    if "through" in provision:
        end = text.find(provision["through"], start)
        if end < 0:
            raise PacketBuildError(
                f"provision {provision['label']!r}: closing text not found after its "
                f"opening - {provision['through']!r}"
            )
        end += len(provision["through"])
    else:
        end = text.find("\n", start)
        if end < 0:
            end = len(text)

    quote = text[start:end].strip()
    if not quote:
        raise PacketBuildError(f"provision {provision['label']!r} located but empty")
    return quote


def _criteria_for(policy_id: str, version: str) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in CRITERIA.read_text(encoding="utf-8").splitlines() if line]
    found = [r for r in rows if r["policy_id"] == policy_id and r["policy_version"] == version]
    if not found:
        raise PacketBuildError(f"no transcribed criteria for {policy_id} rev {version}")
    return sorted(found, key=lambda r: r["criterion_id"])


def _signals(policy_id: str, version: str) -> dict[str, Any]:
    inventory = json.loads(LOGIC.read_text(encoding="utf-8"))
    entry = next(
        (
            e
            for e in inventory["policies"]
            if e["policy_id"] == policy_id and e["policy_version"] == version
        ),
        None,
    )
    if entry is None:
        raise PacketBuildError(f"{policy_id} rev {version} is not in the logic inventory")
    return entry


def _other_blockers(policy_id: str, version: str) -> tuple[str, ...]:
    report = json.loads(ADMISSIBILITY.read_text(encoding="utf-8"))
    candidate = next(
        (
            c
            for c in report["assessment"]
            if c["policy_id"] == policy_id and c["policy_version"] == version
        ),
        None,
    )
    if candidate is None:
        raise PacketBuildError(f"{policy_id} rev {version} is not in the admissibility report")
    return tuple(c for c in candidate["failed_checks"] if c not in RESOLVED_BY_THIS_DECISION)


def _render(
    question: dict[str, Any],
    *,
    quotes: list[tuple[dict[str, Any], str]],
    criteria: list[dict[str, Any]],
    signals: dict[str, Any],
    other_blockers: tuple[str, ...],
    source: Path,
    source_sha: str,
) -> str:
    lines: list[str] = []
    add = lines.append

    add(f"# {question['id']} — Reviewer Packet")
    add("")
    add(f"**{question['title']}**, revision `{question['policy_version']}`.")
    add("")
    add(
        "One question about how a regulation's requirements combine. It needs a "
        "qualified reader of coverage regulation, and there is no engineering answer "
        "to it."
    )
    add("")
    add(
        "Nothing in this packet recommends an outcome. Options appear in the order "
        "their provisions appear in the regulation, and each states what it costs — "
        "not so the cheapest looks best. **Only one option makes this policy "
        "adjudicable, and that is not a reason to choose it.**"
    )
    add("")
    add("---")
    add("")

    add("## 1. The question")
    add("")
    for para in question["question"].strip().split("\n"):
        add(f"> {para.strip()}")
    add("")

    add("## 2. Why this policy has no declared logic")
    add("")
    add(
        f"A lexical scan found {sum(len(v) for v in signals['signals'].values())} "
        f"provisions carrying structural wording across "
        f"{len(signals['signals'])} categories. **Signals are search terms for a "
        "reviewer, not classifications** — the scanner cannot read meaning, and its "
        "silence would not mean a policy is conjunctive."
    )
    add("")
    add("| wording | provisions |")
    add("|---|---|")
    for kind, refs in sorted(signals["signals"].items()):
        add(f"| {kind} | {', '.join(f'`{r}`' for r in refs)} |")
    add("")
    add(
        f"`{signals['provisions_awaiting_review']}` of "
        f"`{signals['provisions_total']}` provisions in this version are awaiting "
        "review. This packet asks only about the ones that bear on how the "
        "**transcribed criteria** combine."
    )
    add("")

    add("## 3. The transcribed criteria")
    add("")
    add(
        "These five are what the system can currently test. Everything else in the "
        "regulation is text the retriever can return but no criterion asserts."
    )
    add("")
    add("| id | type | section | authoritative text |")
    add("|---|---|---|---|")
    for c in criteria:
        add(
            f"| `{c['criterion_id'].rsplit('_', 1)[-1]}` | {c['criterion_type']} | "
            f'{c["source_section"]} | *"{c["authoritative_text"]}"* |'
        )
    add("")
    for c in criteria:
        add(f"**`{c['criterion_id'].rsplit('_', 1)[-1]}`** — {c['normalized_interpretation']}")
        add("")

    add("## 4. The provisions to read")
    add("")
    add(
        f"Quoted verbatim from `{source.relative_to(REPO)}` (sha256 "
        f"`{source_sha[:12]}…`, eCFR, revision {question['policy_version']}). Each is "
        "located in the source at build time, so this packet cannot drift from the "
        "regulation it cites."
    )
    add("")
    for provision, quote in quotes:
        add(f"### {provision['label']}")
        add("")
        for para in quote.split("\n"):
            add(f"> {para.strip()}")
        add("")
        add(provision["note"].strip())
        add("")

    add("## 5. The options")
    add("")
    for option in question["options"]:
        add(f"- `{option['id']}` — {option['summary'].strip()}")
    add("")

    add("## 6. What each one costs")
    add("")
    for option in question["options"]:
        add(f"### `{option['id']}`")
        add("")
        add(option["consequence"].strip())
        add("")

    add("## 7. What else blocks this policy")
    add("")
    if other_blockers:
        add(
            "Answering this question would **not** be enough. These admissibility "
            "conditions also fail and are unaffected by it:"
        )
        add("")
        for blocker in other_blockers:
            add(f"- `{blocker}`")
    else:
        add(
            "**Nothing.** Read from the admissibility gate rather than assumed empty, "
            "so a reviewer who answers this does not then discover a second blocker "
            "at the moment the slice is attempted."
        )
    add("")

    add("---")
    add("")
    add("## Recording your answer")
    add("")
    add(
        "Through `scripts/ingest_focus_decision.py`, the same two-act path FOCUS-001 "
        "used: a submission, then a separate acceptance. See "
        "[FOCUS-001-submission-instructions.md](FOCUS-001-submission-instructions.md) "
        "for the field-by-field detail; only the record path changes."
    )
    add("")
    add(
        "**If none of the readings fits, use `OTHER` and state yours.** Its "
        "consequence is deliberately not precomputed — modelling an unstated reading "
        "would mean inventing one, and the placeholder would then be mistaken for an "
        "analysis."
    )
    add("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", required=True, help="an id from od19_questions.yaml")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    import hashlib

    question = _load_question(args.question)
    policy_id, version = question["policy_id"], question["policy_version"]

    source = _source_path(policy_id, version)
    raw = source.read_text(encoding="utf-8")
    source_sha = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    quotes = [(p, _locate(raw, p)) for p in question["provisions"]]
    criteria = _criteria_for(policy_id, version)
    signals = _signals(policy_id, version)
    other_blockers = _other_blockers(policy_id, version)

    options = tuple(o["id"] for o in question["options"])
    slug = args.question.replace(".", "_").replace("-", "_").lower()
    out_packet = REPO / f"docs/review/{args.question}.md"
    out_decision = REPO / f"data/review/{slug}_decision.json"

    gate = DecisionGate.pending(
        focus_id=args.question,
        question=" ".join(question["question"].split()),
        policy_id=policy_id,
        policy_version=version,
        permitted_decisions=options,
        affected_criteria=tuple(c["criterion_id"] for c in criteria),
        source_references=(
            str(out_packet.relative_to(REPO)),
            f"{policy_id} — {source.relative_to(REPO)}",
            str(question.get("source_url", "https://www.ecfr.gov/current/title-42")),
        ),
    )

    record = {
        **{k: v for k, v in asdict(gate).items() if k != "notes"},
        "status": gate.status.value,
        "reviewer_identity": None,
        "reviewer_qualification": None,
        "submitted_at": gate.review_timestamp,
        "separation_of_duties": gate.separation_of_duties.value,
        "is_resolved": gate.is_resolved,
        "blocks_production": gate.blocks_production,
        "source_document_sha256": source_sha,
        "other_blockers_after_this_decision": list(other_blockers),
        "note": (
            "This is a DOMAIN decision about how a regulation's requirements combine. "
            "No lexical scan, similarity score or model output may answer it. The "
            "signals recorded in the logic inventory are search terms for a reviewer, "
            "not classifications - the scanner cannot read meaning."
        ),
    }

    packet = _render(
        question,
        quotes=quotes,
        criteria=criteria,
        signals=signals,
        other_blockers=other_blockers,
        source=source,
        source_sha=source_sha,
    )

    print(f"  question        {args.question}")
    print(f"  policy          {policy_id} rev {version}")
    print(f"  criteria        {len(criteria)}")
    print(f"  provisions      {len(quotes)} located verbatim")
    print(f"  options         {list(options)}")
    print(f"  other blockers  {list(other_blockers) or 'none'}")
    print(f"  status          {gate.status.value}\n")

    if not args.write:
        print("  (dry run; pass --write)")
        return 0

    rebuilt = json.dumps(record, indent=2, sort_keys=True, default=str) + "\n"
    existing = out_decision.read_text(encoding="utf-8") if out_decision.exists() else None
    try:
        refuse_destructive_rebuild(existing, rebuilt)
    except DecisionResetRefused as exc:
        print(f"  REFUSED: {exc}", file=sys.stderr)
        return 1

    out_packet.write_text(packet, encoding="utf-8")
    out_decision.write_text(rebuilt, encoding="utf-8")
    print(f"  written to {out_packet.relative_to(REPO)} and {out_decision.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
