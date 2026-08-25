"""Break each safety rule on purpose, and prove a test notices.

A passing test suite says the code does what the tests check. It says nothing about
whether the tests would notice if the code stopped doing it. Those are different
claims, and the gap between them is where a vacuous test lives.

This project has found three vacuous safety tests by hand:

- one asserted a query set was non-empty, and survived a mutation that broke 11 of
  12 entries
- one checked that a remedy string said "never retried", and survived a mutation
  that added a real retry loop while changing the prose
- one checked for the substring `"Path("`, which does not match
  `from pathlib import Path`

Each was found by injecting a mutation manually, once. **Nothing re-ran them**, so
they were evidence about an afternoon rather than a guarantee. This harness makes
that repeatable.

## Why not a mutation-testing framework

`mutmut` and `cosmic-ray` generate mutations blindly across a whole module and take
tens of minutes to hours. That is a good fit for finding weak spots in code you have
not thought about, and a poor fit here: the mutations that matter are the ones a
future maintainer would plausibly write while "simplifying" a safety check, and they
are enumerable. Nine of them run in about a minute.

The trade is deliberate: **no coverage claim** over the mutation space, in exchange
for a check fast enough to run every time. A framework can be added later without
replacing this - it answers a different question.

    uv run python scripts/mutation_guard.py           # all
    uv run python scripts/mutation_guard.py --list
    uv run python scripts/mutation_guard.py -k gate

## The invariant this file itself must satisfy

**It must never leave the repository mutated.** Every mutation is applied, tested and
reverted under `try/finally`, the original bytes are held in memory, and the run ends
by verifying the working tree matches what it started with. A harness that could
corrupt the tree while proving the tree is safe would be its own worst finding.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class Mutation:
    """One safety rule, broken one way, with the test that must notice.

    `old` must appear EXACTLY ONCE in the file. A substring occurring twice would
    mutate an arbitrary one of them, and the harness would report on a line nobody
    chose - so a non-unique anchor is a hard error rather than a first-match.
    """

    name: str
    rule: str
    path: str
    old: str
    new: str
    tests: str
    keyword: str = ""


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        name="production-gate-removed",
        rule="a blocked production gate must stop the slice being constructed",
        path="app/graph/slice.py",
        old="        gate.require()",
        new="        pass  # MUTATION: gate removed",
        tests="tests/integration/test_first_vertical_slice.py",
        keyword="blocked_gate_prevents or no_model_call_happens",
    ),
    Mutation(
        name="gate-accepts-anything-truthy",
        rule="a truthy stand-in must not pass as a GateDecision",
        path="app/graph/slice.py",
        old="        if not isinstance(gate, GateDecision):",
        new="        if False:  # MUTATION: any truthy value accepted",
        tests="tests/integration/test_first_vertical_slice.py",
        keyword="truthy_stand_in",
    ),
    Mutation(
        name="focus-001-pending-ignored",
        rule="an unresolved domain decision must block production",
        path="app/production_gate.py",
        old='        if not record.get("is_resolved"):',
        new="        if False:  # MUTATION: pending decision ignored",
        tests="tests/unit/test_phase9_contracts.py tests/evaluation/test_phase8_gate.py",
        keyword="pending_decision or gate_follows_the_decision",
    ),
    Mutation(
        name="unreadable-artefact-permits",
        rule="an unreadable gate artefact must block, never permit",
        path="app/production_gate.py",
        old="        return None\n    return loaded if isinstance(loaded, dict) else None",
        new="        return {}  # MUTATION: unreadable reads as permission\n    return loaded if isinstance(loaded, dict) else None",
        tests="tests/unit/test_phase9_contracts.py",
        keyword="unreadable_artefact",
    ),
    Mutation(
        name="review-required-executes",
        rule="a policy whose semantics nobody reviewed must not adjudicate",
        path="app/decision/table.py",
        old="    if semantics.status is SemanticsStatus.REVIEW_REQUIRED:",
        new="    if False:  # MUTATION: REVIEW_REQUIRED executes",
        tests="tests/unit/test_fail_closed_semantics.py",
        keyword="distinguishable or review_required",
    ),
    Mutation(
        name="invalid-citation-accepted",
        rule="a citation failure must stop the case",
        path="app/graph/slice.py",
        old="        if not report.passed:",
        new="        if False:  # MUTATION: citation failures ignored",
        tests="tests/integration/test_first_vertical_slice.py",
        keyword="does_not_verify or another_policy or another_version",
    ),
    Mutation(
        name="tampered-chunk-trusted",
        rule="a chunk whose hash no longer matches must not be cited",
        path="app/guardrail/citations.py",
        old="        if not chunk.is_intact():",
        new="        if False:  # MUTATION: tampered chunks trusted",
        tests="tests/integration/test_first_vertical_slice.py",
        keyword="does_not_verify or injection_in_retrieved",
    ),
    Mutation(
        name="fabricated-evidence-trusted",
        rule="an evidence id the model invented must not support a verdict",
        path="app/adjudication/assess.py",
        old="    cited = tuple(eid for eid in answer.evidence_ids if eid in known)",
        new="    cited = tuple(answer.evidence_ids)  # MUTATION: invented ids trusted",
        tests="tests/integration/test_first_vertical_slice.py",
        keyword="citing_evidence_it_was_not_given or unevidenced_refusal",
    ),
    Mutation(
        name="self-acceptance-permitted",
        rule="a reviewer must not accept their own decision without the ADR-026 exemption",
        path="app/review/ingest.py",
        old="    if gate.reviewer is not None and accepted_by == gate.reviewer.reviewer_id:",
        new="    if False:  # MUTATION: self-acceptance permitted",
        tests="tests/evaluation/test_focus_packet_integrity.py",
        keyword="default_is_still_refusal or three_declarations",
    ),
    Mutation(
        # Adding 403 to `_RETRYABLE` is NOT this mutation, and the difference is
        # instructive: the terminal 403 branch runs BEFORE `_RETRYABLE` is consulted,
        # so widening that set changes nothing. Mutating dead code proves nothing,
        # and the harness reported it as SURVIVED until the anchor was corrected.
        name="firewall-block-retried",
        rule="a 403 must never be retried",
        path="app/llm/client.py",
        old="                if status == 403:",
        new="                if False:  # MUTATION: 403 falls through to the retry path",
        tests="tests/unit/test_firewall_gateway.py",
        keyword="never_retried or block_is_classified",
    ),
    Mutation(
        name="gold-v1-protection-removed",
        rule="the frozen gold set must be asserted against its manifest",
        path="data/gold/manifests/gold_v1.manifest.json",
        old='"gold": "ca990b804cf8fd38950bb1dc84e9e1f2a100d5cb579d124109b2d13387f2d0c9"',
        new='"gold": "0000000000000000000000000000000000000000000000000000000000000000"',
        tests="tests/evaluation",
        keyword="gold",
    ),
)


def _run(mutation: Mutation) -> tuple[bool, str]:
    """Apply, test, revert. Returns (test suite failed?, detail)."""
    path = REPO / mutation.path
    original = path.read_bytes()
    text = original.decode("utf-8")

    occurrences = text.count(mutation.old)
    if occurrences != 1:
        return False, f"anchor appears {occurrences} times in {mutation.path}; expected exactly 1"

    try:
        path.write_text(text.replace(mutation.old, mutation.new, 1), encoding="utf-8")
        command = [
            "uv",
            "run",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            *mutation.tests.split(),
        ]
        if mutation.keyword:
            command += ["-k", mutation.keyword]
        result = subprocess.run(command, cwd=REPO, capture_output=True, text=True)
        detail = (result.stdout or result.stderr).strip().splitlines()
        summary = detail[-1] if detail else "no output"
        # A mutation must make a test FAIL. Exit code 5 means no test was selected,
        # which is a broken keyword rather than a caught mutation - reported as a
        # failure of the harness, not as a pass.
        if result.returncode == 5:
            return False, f"no tests selected by -k {mutation.keyword!r}"
        return result.returncode != 0, summary
    finally:
        path.write_bytes(original)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="show the mutation set and exit")
    parser.add_argument("-k", dest="filter", default="", help="run mutations matching a substring")
    args = parser.parse_args()

    if args.list:
        for mutation in MUTATIONS:
            print(f"  {mutation.name:32} {mutation.rule}")
        return 0

    selected = [m for m in MUTATIONS if args.filter in m.name]
    if not selected:
        print(f"no mutation matches {args.filter!r}", file=sys.stderr)
        return 1

    before = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True
    ).stdout

    print(f"  {len(selected)} mutation(s); each must make a test fail\n")
    survived: list[Mutation] = []
    for mutation in selected:
        caught, detail = _run(mutation)
        mark = "CAUGHT  " if caught else "SURVIVED"
        print(f"  {mark}  {mutation.name:32} {detail[:60]}")
        if not caught:
            survived.append(mutation)

    after = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True
    ).stdout
    if before != after:
        print("\n  FATAL: the working tree changed. A mutation was not reverted.", file=sys.stderr)
        return 2
    print("\n  working tree unchanged")

    if survived:
        print(
            f"\n  {len(survived)} SURVIVED - the rule is not defended by a test:", file=sys.stderr
        )
        for mutation in survived:
            print(f"    {mutation.name}: {mutation.rule}", file=sys.stderr)
        return 1

    print(f"  all {len(selected)} mutations caught")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
