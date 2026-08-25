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
        name="contradiction-never-reaches-row-5",
        rule="a detected contradiction must reach decision-table row 5",
        path="app/guardrail/contradiction.py",
        old="        if report.state is ContradictionState.CONTRADICTION",
        new="        if False  # MUTATION: row 5 unreachable again (R-89)",
        tests="tests/unit/test_contradiction.py tests/integration/test_first_vertical_slice.py",
        keyword="row_5 or contradiction_stops",
    ),
    Mutation(
        name="undetermined-treated-as-contradiction",
        rule="UNDETERMINED must be non-decisive - it must not stop a case",
        path="app/guardrail/contradiction.py",
        old="        if report.state is ContradictionState.CONTRADICTION",
        new="        if report.state is not ContradictionState.CONTRADICTION  # MUTATION",
        tests="tests/unit/test_contradiction.py",
        keyword="row_5 or undetermined_does_not_reach",
    ),
    Mutation(
        name="contradiction-detector-silenced",
        rule="structural conflicts must be detected, not assumed absent",
        path="app/guardrail/contradiction.py",
        old="    if findings:",
        new="    if False:  # MUTATION: detector never reports a conflict",
        tests="tests/unit/test_contradiction.py",
        keyword="opposite_verdicts or twice_differently or same_span",
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
        old="        eid for eid in answer.evidence_ids if is_wellformed_evidence_id(eid) and eid in known",
        new="        eid for eid in answer.evidence_ids  # MUTATION: invented ids trusted",
        tests="tests/integration/test_first_vertical_slice.py",
        keyword="citing_evidence_it_was_not_given or unevidenced_refusal",
    ),
    Mutation(
        # NOT the shape check in `assess.py`. That one is redundant with membership -
        # every forged id is also absent from the set - so removing it survives, and
        # a mutation that survives because the rule is defended twice is not a
        # finding. The load-bearing guard is the one that keeps a malformed id OUT of
        # the known set, because a set whose members fail their own validator would
        # make the shape check meaningless.
        name="evidence-id-entry-guard-removed",
        rule="an evidence entry must not be constructible with a malformed id",
        path="app/adjudication/evidence_block.py",
        old="        if not is_wellformed_evidence_id(self.evidence_id):",
        new="        if False:  # MUTATION: malformed ids admitted to the known set",
        tests="tests/integration/test_first_vertical_slice.py",
        keyword="entry_cannot_be_built",
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
    # -- Phase 15: policy applicability (R-93) ------------------------------
    Mutation(
        # THE R-93 mutation. Removing the refusal is exactly the Phase-14 runtime:
        # applicability still runs, still records its finding, and nothing acts on
        # it - which is the shape the defect actually had. A mutation that deleted
        # the whole stage would also break the audit-trail assertions, and would
        # then be caught by a test that is not the regression.
        name="applicability-stage-removed",
        rule="a policy that does not govern the case must not be adjudicated",
        path="app/graph/slice.py",
        old="        if not finding.permits_adjudication:",
        new="        if False:  # MUTATION: an inapplicable policy is adjudicated anyway",
        tests="tests/integration/test_case_0073_regression.py",
        keyword="inapplicable_policy_cannot_produce_a_denial or no_refusing_state",
    ),
    Mutation(
        # A PRODUCTION runner with no resolver IS the Phase-14 runtime. Without this
        # guard the fix is present and skippable, and skipping it needs no edit to
        # any file that mentions applicability.
        name="production-runs-without-a-resolver",
        rule="production must not assume the policy it was handed governs the case",
        path="app/graph/slice.py",
        old="        if mode in PRODUCTION_MODES and applicability is None:",
        new="        if False:  # MUTATION: PRODUCTION without an ApplicabilityPort",
        tests="tests/integration/test_case_0073_regression.py",
        keyword="without_a_resolver_cannot_be_constructed",
    ),
    Mutation(
        # NOT the `ResolutionState(...)` in `run()`. That one is reachable only when
        # the state IS RESOLVED - the refusal above returns first - so replacing it
        # with the Phase-14 literal `ResolutionState(RESOLVED, 1)` is genuinely
        # equivalent and SURVIVES. A mutation that survives because the rule is
        # defended upstream is not a finding, and the harness reported it as
        # SURVIVED until the anchor was moved here. Measured, not assumed.
        #
        # This one is load-bearing: the refusal path is where a non-RESOLVED state
        # is turned into a row of the table. Hardcoding RESOLVED here makes every
        # refusal fall through to the totality guard, and a reviewer is told
        # "unclassified" about a case the system understood perfectly well.
        name="refusal-reports-a-generic-row",
        rule="a refusal must name the applicability row, not fall through to UNCLASSIFIED",
        path="app/graph/slice.py",
        old="            GuardrailState.PASSED,\n            ResolutionState(status=finding.state, version_count=finding.version_count),",
        new="            GuardrailState.PASSED,\n            ResolutionState(status=ResolutionStatus.RESOLVED, version_count=1),  # MUTATION",
        tests="tests/integration/test_case_0073_regression.py",
        keyword="inapplicable_policy_cannot_produce_a_denial or names_the_policy_reason",
    ),
    Mutation(
        # Collapsing the six states into "resolved or not" is the simplification a
        # maintainer would actually write, and it makes TEMPORALLY_UNRESOLVED,
        # INSUFFICIENT_INFORMATION and RESOLUTION_ERROR all read as coverage answers.
        name="only-resolved-is-checked-by-identity",
        rule="every non-RESOLVED state must refuse, not just NOT_APPLICABLE",
        path="app/core/types.py",
        old="        return self is ResolutionStatus.RESOLVED",
        new="        return self is not ResolutionStatus.NONE_APPLICABLE  # MUTATION",
        tests="tests/unit/test_policy_applicability.py tests/integration/test_case_0073_regression.py",
        keyword="only_resolved_permits or no_refusing_state",
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
    # -- closure audit: controls that were documented but not called ----------
    Mutation(
        # The defect the audit found, reproduced exactly. Before this commit the
        # runner did not consult the gate at all and every test was green.
        name="official-gate-not-consulted-by-the-runner",
        rule="a runner that writes an official artefact must ask the gate first",
        path="scripts/score_frozen_410_33.py",
        old="        OfficialEvaluationGate.require()",
        new="        pass  # MUTATION",
        tests="tests/evaluation/test_schema_boundary.py",
        keyword="gate",
    ),
    Mutation(
        # The SECOND runner, not a repeat. Wiring one entry point and leaving the
        # other is the realistic half-fix, and the discovery-based test is what makes
        # it visible - a hand-maintained list of runners would not have this one on
        # it either.
        #
        # This mutation also pins the presence check against its own first draft,
        # which searched the source for the string "OfficialEvaluationGate" and was
        # satisfied by the surviving IMPORT line. That draft SURVIVED this mutation.
        # The check reads the call out of the AST now. Measured, not assumed.
        name="official-gate-not-consulted-by-the-live-runner",
        rule="every runner writing an official artefact must ask the gate, not just one",
        path="scripts/run_frozen_410_33_evaluation.py",
        old="        OfficialEvaluationGate.require()",
        new="        pass  # MUTATION",
        tests="tests/evaluation/test_schema_boundary.py",
        keyword="gate",
    ),
    Mutation(
        # The simplification a maintainer would actually write: "the gold split is
        # the frozen one, everything else is fine to tune on."
        name="only-gold-is-frozen",
        rule="validation and the retrieval benchmarks are frozen too, not just gold",
        path="eval/schema.py",
        old="TUNABLE_PARTITIONS: frozenset[Partition] = frozenset({Partition.DEVELOPMENT})",
        new=(
            "TUNABLE_PARTITIONS: frozenset[Partition] = frozenset(  # MUTATION\n"
            "    set(Partition) - {Partition.GOLD}\n"
            ")"
        ),
        tests="tests/evaluation/test_schema_boundary.py",
        keyword="tunable",
    ),
    Mutation(
        # Restores the default that granted a free scoring to any dataset that
        # declared no budget.
        name="undeclared-scoring-budget-defaults-to-one",
        rule="a dataset that declares no scoring allowance has not been granted one",
        path="eval/schema.py",
        old="    if allowed is None:",
        new="    if False:  # MUTATION",
        tests="tests/evaluation/test_schema_boundary.py",
        keyword="undeclared",
    ),
    # -- R-86 closure: the two termination conditions Part F named -----------
    Mutation(
        # The exact defect the closure work found, restored. Without this condition a
        # response that closes its document and then pads to the ceiling is a SUCCESS,
        # six of them return PASS at 0/12, and the official evaluation opens on a
        # provider path that still never terminates.
        name="closure-ignores-completion-ceiling-exhaustion",
        rule="a trial that stopped by exhausting the ceiling has not terminated",
        path="eval/r86_closure.py",
        old='    if shape.finish_reason == "length":',
        new="    if False:  # MUTATION",
        tests="tests/evaluation/test_r86_attribution.py",
        keyword="ceiling_exhaustion",
    ),
    Mutation(
        name="closure-ignores-the-r86-whitespace-shape",
        rule="a whitespace-dominated response at the ceiling is the R-86 shape, not a success",
        path="eval/r86_closure.py",
        old="    if shape.looks_like_whitespace_runaway:",
        new="    if False:  # MUTATION",
        tests="tests/evaluation/test_r86_attribution.py",
        keyword="closes_then_pads",
    ),
    Mutation(
        # The gate reverted to asking the taxonomy alone, which is what it did before.
        name="revalidation-counts-failures-by-taxonomy-alone",
        rule="the closure gate must apply r86-closure.v1, not 'did the call raise'",
        path="scripts/r86_revalidate.py",
        old="            failures = sum(1 for v in verdicts if not v.succeeded)",
        new=(
            "            failures = sum(  # MUTATION\n"
            "                1 for o in observations if not o.satisfied_schema\n"
            "            )"
        ),
        tests="tests/evaluation/test_r86_attribution.py",
        keyword="closure_rule",
    ),
    Mutation(
        # A seal quietly updated to agree with today. Both the digest check and the
        # historical-attribution check must notice.
        name="sealed-attribution-rewritten-to-todays-answer",
        rule="a seal records what was known when it was taken and is never rewritten",
        path="data/escalations/r86-reproducer.manifest.json",
        old='"attribution": "INDETERMINATE"',
        new='"attribution": "PROVIDER_SIDE"',
        tests="tests/evaluation/test_r86_attribution.py",
        keyword="seal",
    ),
    Mutation(
        # The state the repository was actually in: the constraint lived only in the
        # migration, `alembic check` reported it as one to REMOVE, and the next
        # --autogenerate would have emitted a migration dropping the rule that stops
        # an UNDATED version carrying dates.
        name="temporal-constraint-declared-only-in-the-migration",
        rule="a constraint a migration creates must exist in the ORM metadata too",
        path="app/policy/models.py",
        old='            name="temporal_status_matches_dates",',
        new='            name="mutated_away",  # MUTATION',
        tests="tests/unit/test_schema_metadata.py",
        keyword="constraint",
    ),
    Mutation(
        name="a-frozen-manifest-can-be-refrozen",
        rule="a freeze that can be re-taken is not a freeze",
        path="scripts/phase16_prerun_gate.py",
        old='        if (OUT / "manifest.json").is_file():',
        new="        if False:  # MUTATION",
        tests="tests/evaluation/test_schema_boundary.py",
        keyword="refrozen",
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
