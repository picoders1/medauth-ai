"""Decide whether `phase16-evaluation-001` may execute, and record the decision.

    uv run python scripts/phase16_authorisation.py --write

Parts C, E, I, J and R. Runs **every** precondition even after one has already
failed, and writes the verdict beside the frozen manifest without touching it.

## Why it does not stop at the first STOP

A gate that short-circuits reports one blocker per attempt, and closing them one at a
time is how a phase spends four runs learning what it could have learned in one. It
also hides the shape of the situation: "the provider path is the only thing wrong" is
a materially different statement from "the provider path is wrong and so are three
other things", and only an exhaustive check can tell them apart.

## Why the manifest is not edited

`eval/reports/phase16-410-33/manifest.json` is frozen. An authorisation decision is
*about* it, not part of it, and rewriting a frozen manifest to record that it was
refused would make the freeze conditional on the outcome. The verdict is a sibling
file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "eval/reports/phase16-410-33/manifest.json"
RECHECK = REPO / "eval/reports/r86-gate-recheck/results.json"
GOLD_V1 = REPO / "data/gold/cases/gold_v1.jsonl"
GOLD_V1_MANIFEST = REPO / "data/gold/manifests/gold_v1.manifest.json"
GOLD_V2 = REPO / "data/gold/cases/gold_v2.jsonl"
GOLD_V2_MANIFEST = REPO / "data/gold/manifests/gold_v2.manifest.json"
BASELINE = REPO / "eval/reports/retrieval-v4-baseline/results.json"
OUT = MANIFEST.parent / "AUTHORISATION.json"


@dataclass
class Check:
    name: str
    part: str
    passed: bool
    detail: str


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        return "unknown"


def provider_gate(manifest: dict[str, Any]) -> list[Check]:
    """Part C. The recheck's verdict, read rather than recomputed.

    Recomputing it here would put the pre-registered rule in two places, and a rule
    that must not move should not have a second copy that can.
    """
    if not RECHECK.is_file():
        return [
            Check(
                "provider_gate",
                "C",
                False,
                "no gate recheck exists; run scripts/r86_gate_recheck.py",
            )
        ]
    recheck = json.loads(RECHECK.read_text())
    gate = recheck["gate"]
    checks = [
        Check(
            "provider_gate",
            "C",
            gate["result"] == "PASS",
            f"{gate['result']}: {gate['why']}",
        ),
        # The recheck is only evidence if it ran under the registered conditions.
        # A PASS obtained after drift would be a different experiment's number.
        Check(
            "recheck_conditions_unchanged",
            "A",
            recheck["registered_conditions"]["unchanged"],
            "the reproducer ran under the registered conditions"
            if recheck["registered_conditions"]["unchanged"]
            else f"drift: {recheck['registered_conditions']['drift']}",
        ),
        # And only if it is about THIS experiment's rule.
        Check(
            "validity_rule_matches_manifest",
            "C",
            gate["rule_id"] == manifest["experiment_validity_rule"]["id"],
            f"gate rule {gate['rule_id']}, manifest rule "
            f"{manifest['experiment_validity_rule']['id']}",
        ),
        Check(
            "threshold_unchanged",
            "C",
            float(gate["acceptance_threshold"])
            == float(manifest["experiment_validity_rule"]["max_failure_rate"]),
            f"acceptance threshold {gate['acceptance_threshold']} matches the frozen "
            f"{manifest['experiment_validity_rule']['max_failure_rate']}",
        ),
    ]
    return checks


def gold_integrity(manifest: dict[str, Any]) -> list[Check]:
    """Part I. gold_v1 byte-identical, gold_v2 unmoved since the freeze."""
    v1 = _sha(GOLD_V1)
    v1_recorded = json.loads(GOLD_V1_MANIFEST.read_text())["sha256"]["gold"]
    v2 = _sha(GOLD_V2)
    v2_manifest = json.loads(GOLD_V2_MANIFEST.read_text())
    frozen = manifest["source_digests"]

    checks = [
        Check("gold_v1_immutable", "I", v1 == v1_recorded, f"gold_v1 {v1[:16]}"),
        Check(
            "gold_v2_matches_its_manifest",
            "I",
            v2 == v2_manifest["sha256"]["gold"],
            f"gold_v2 {v2[:16]}, {v2_manifest['case_count']} cases",
        ),
        Check(
            "gold_v2_unmoved_since_the_experiment_freeze",
            "I",
            f"sha256:{v2}" == frozen["gold_v2"],
            f"frozen {frozen['gold_v2'][7:23]}, now {v2[:16]}",
        ),
        Check(
            "gold_v2_budget_unspent",
            "I",
            v2_manifest["scoring_budget"]["scorings_spent"] == 0,
            f"scorings spent {v2_manifest['scoring_budget']['scorings_spent']} of "
            f"{v2_manifest['scoring_budget']['allowed_scorings']}",
        ),
    ]

    # Structured applicability provenance, re-derived rather than read. A case
    # asserting its own state proves only that the file agrees with itself.
    import yaml

    linkage = yaml.safe_load((REPO / "data/linkage/policy_code_links.yaml").read_text())
    covered = {
        (str(link["code"]), str(link["code_system"]))
        for link in linkage["links"]
        if str(link.get("link_type", "COVERED_PROCEDURE")) == "COVERED_PROCEDURE"
    }
    cases = [json.loads(line) for line in GOLD_V2.read_text().splitlines() if line.strip()]
    mismatched = [
        case["case_id"]
        for case in cases
        if (
            (
                str(case["input"]["requested_service"]["procedure_code"]),
                str(case["input"]["requested_service"]["code_system"]),
            )
            in covered
        )
        != (case["expected"]["applicability"]["state"] == "RESOLVED")
    ]
    narrative_only = [
        case["case_id"]
        for case in cases
        if case["expected"]["applicability"]["state"] != "RESOLVED"
        and case["input"]["requested_service"]["procedure_code"]
        not in case["input"]["clinical_note"]
    ]
    checks += [
        Check(
            "structured_applicability_provenance",
            "I",
            not mismatched,
            f"{len(cases)} cases re-derived from input plus linkage"
            if not mismatched
            else f"{len(mismatched)} do not follow: {mismatched[:5]}",
        ),
        Check(
            "no_narrative_only_ground_truth",
            "I",
            not narrative_only,
            "no not-applicable case relies on prose"
            if not narrative_only
            else f"{len(narrative_only)} rely on prose: {narrative_only[:5]}",
        ),
    ]
    return checks


def configuration_unchanged(manifest: dict[str, Any]) -> list[Check]:
    """Part E and J. Every frozen value, against the live one.

    A run under a changed configuration would be scored against a manifest that no
    longer describes it - which is the failure a manifest exists to prevent.
    """
    from app.adjudication.assess import ASSESSMENT_PROMPT_ID
    from app.config.settings import Settings
    from app.intake.extract import INTAKE_PROMPT_ID
    from app.llm.wiring import structured_model_for

    settings = Settings()
    structured = structured_model_for(settings)

    def digest(value: str) -> str:
        return f"sha256:{hashlib.sha256(value.encode()).hexdigest()[:12]}"

    live_applicability = digest(
        (REPO / "app/policy/applicability.py").read_text()
        + (REPO / "app/policy/live_applicability.py").read_text()
    )
    live_gateway = digest(
        f"{settings.llm_base_url}|{settings.llm_timeout_seconds}|"
        f"{settings.llm_max_attempts}|{settings.llm_fail_closed}|"
        f"{settings.llm_streaming_enabled}|{structured}"
    )

    checks = [
        Check(
            "prompt_versions",
            "E",
            manifest["prompts"]
            == {"intake": INTAKE_PROMPT_ID, "adjudication": ASSESSMENT_PROMPT_ID},
            f"{INTAKE_PROMPT_ID}, {ASSESSMENT_PROMPT_ID}",
        ),
        Check(
            "model_digest",
            "E",
            manifest["model"]["digest"] == digest(structured),
            f"frozen {manifest['model']['digest']}, live {digest(structured)}",
        ),
        Check(
            "applicability_version",
            "E",
            manifest["applicability"]["digest"] == live_applicability,
            f"frozen {manifest['applicability']['digest']}, live {live_applicability}",
        ),
        Check(
            "gateway_configuration_digest",
            "E",
            manifest["gateway"]["configuration_digest"] == live_gateway,
            f"frozen {manifest['gateway']['configuration_digest']}, live {live_gateway}",
        ),
        Check(
            "retrieval_configuration",
            "J",
            manifest["retrieval"]["status"] == "ENGINEERING_DEFAULT_UNRESOLVED",
            f"{manifest['retrieval']['status']}, top_k={manifest['retrieval']['top_k']}, "
            f"rerank_top_n={manifest['retrieval']['rerank_top_n']}",
        ),
    ]

    # Part J: the retrieval baseline this experiment would be interpreted against.
    # A baseline scored under a different configuration is SYSTEM_CONFIGURATION_DRIFT
    # and is a stop condition of its own.
    if BASELINE.is_file():
        baseline = json.loads(BASELINE.read_text())
        configuration = baseline["configuration"]
        matches = (
            configuration["embedding_model"] == manifest["retrieval"]["embedding_model"]
            and configuration["reranker_model"] == manifest["retrieval"]["reranker_model"]
            and configuration["top_k"] == manifest["retrieval"]["top_k"]
            and configuration["rerank_top_n"] == manifest["retrieval"]["rerank_top_n"]
        )
        checks.append(
            Check(
                "retrieval_baseline_matches_the_frozen_configuration",
                "J",
                matches,
                f"retrieval_v4 baseline R@1 "
                f"{baseline['arm']['recall_at_1']['successes']}/"
                f"{baseline['arm']['recall_at_1']['total']} under the same configuration"
                if matches
                else "SYSTEM_CONFIGURATION_DRIFT: the baseline was scored under a "
                "different retrieval configuration from the one frozen here",
            )
        )
    else:
        checks.append(
            Check("retrieval_baseline_matches_the_frozen_configuration", "J", False, "no baseline")
        )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    manifest = json.loads(MANIFEST.read_text())
    checks = provider_gate(manifest) + gold_integrity(manifest) + configuration_unchanged(manifest)
    authorised = all(c.passed for c in checks)
    blockers = [c.name for c in checks if not c.passed]

    for check in checks:
        print(
            f"  [{'PASS' if check.passed else 'STOP'}] ({check.part}) {check.name:44} {check.detail}"
        )

    verdict = {
        "experiment": manifest["experiment"],
        "decided_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "authorised": authorised,
        "status": "AUTHORISED_TO_RUN" if authorised else "NOT_AUTHORISED",
        "blockers": blockers,
        "blocking_part": "C - provider gate" if "provider_gate" in blockers else None,
        "checks": [
            {"name": c.name, "part": c.part, "passed": c.passed, "detail": c.detail} for c in checks
        ],
        "manifest_digest": f"sha256:{_sha(MANIFEST)}",
        "manifest_untouched": (
            "The frozen manifest is not edited by this decision. An authorisation is "
            "ABOUT a manifest, not part of one; rewriting it to record a refusal "
            "would make the freeze conditional on the outcome."
        ),
        "consequence": (
            "The official evaluation did NOT run. gold_v2's single scoring is "
            "unspent, and every metric the run would have produced is absent rather "
            "than estimated."
            if not authorised
            else "The official evaluation may execute exactly as frozen."
        ),
        "not_permitted_responses": [
            "lowering the acceptance threshold",
            "changing the reproducer's request shape",
            "excluding the failing cell",
            "running anyway and labelling the result degraded",
        ],
    }

    print()
    if authorised:
        print("  AUTHORISED")
    else:
        print(f"  NOT AUTHORISED: {blockers}")
        print(
            "\n  The official evaluation does not run. gold_v2's scoring stays "
            "unspent,\n  and no metric is estimated in place of one that was not "
            "measured."
        )

    if args.write:
        OUT.write_text(json.dumps(verdict, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n  written to {OUT.relative_to(REPO)}")
    return 0 if authorised else 1


if __name__ == "__main__":
    raise SystemExit(main())
