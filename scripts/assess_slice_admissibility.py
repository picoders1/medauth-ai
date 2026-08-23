"""Which policy version, if any, is admissible for the first AI vertical slice?

Seven conditions, each checked against a committed artefact rather than asserted.
A policy is admissible only if it passes all seven - the conjunction is the point,
because a slice that fails one is a slice where the first AI experiment would be
measuring something other than what it claims.

     1. semantics DECLARED                  the logic was read off the regulation
     2. criteria span-verified              every criterion locates in the source
     3. no unresolved criterion dependency  nothing invokes a rule it lacks (R-51)
     4. temporally resolvable               a date of service selects a version
     5. coverage status established or N/A  a regulation needs none; an NCD does
     6. no ENGINEERING_INFERRED linkage     applicability never rests on resemblance
     7. citation provenance complete        source url, section and span per criterion
     8. retrieval scope constructible       a scope can be built and it is non-empty
     9. evaluation provenance sufficient    a scorable query targets this version
    10. production semantics executable     the runtime would actually run it
    11. domain decisions resolved           no open decision gate blocks this policy

There is no "close enough". A slice failing one condition is a slice where the first
AI experiment measures something other than what it claims, and the report says
READY or BLOCKED with nothing between them.

This is a **test**, not a verdict. Re-running it after a reviewer closes a blocker
changes the answer without anyone rewriting a document, which is the only way a
readiness claim stays true.

Writes `data/review/slice_admissibility.json`.

    uv run python scripts/assess_slice_admissibility.py --write
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from app.core.identity import PolicyIdentity, PolicyType
from app.policy.logic_loader import load_policy_logic_dir
from app.policy.models import LinkProvenance

REPO = Path(__file__).resolve().parents[1]
INVENTORY = REPO / "data/policy_logic/inventory.json"
LOGIC_DIR = REPO / "data/policy_logic"
CRITERIA = REPO / "data/criteria/inventory.jsonl"
VERIFICATION = REPO / "data/criteria/verification.json"
DEPENDENCIES = REPO / "data/review/policy_dependencies.json"
COVERAGE = REPO / "data/coverage/registry.yaml"
PROVENANCE = REPO / "data/review/evaluation_provenance.json"
FOCUS_DECISION = REPO / "data/review/focus_001_decision.json"
CORPUS_REGISTRY = REPO / "data/cms/registry.yaml"
LINKAGE_FILES = (
    REPO / "data/linkage/policy_code_links.yaml",
    REPO / "data/linkage/ncd_code_links.yaml",
)
OUT = REPO / "data/review/slice_admissibility.json"

LEGACY = {"AUTHORITATIVE": "SOURCE_STATED", "INFERRED": "ENGINEERING_INFERRED"}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _ncd_versions(registry: dict[str, Any]) -> list[dict[str, str]]:
    """NCD documents flattened to (policy_id, revision_id) rows, matching the CFR
    registry's shape so both corpora can be checked the same way."""
    return [
        {"policy_id": document["policy_id"], "revision_id": str(version["version"])}
        for document in registry["documents"]
        for version in document["versions"]
    ]


def _declared_logic() -> set[tuple[str, str]]:
    """Policy versions with a declared-logic file the loader can actually read.

    Loaded rather than globbed: a file that exists and fails to parse would make a
    policy look executable while the runtime refuses it, which is the gap between
    `semantics_declared` and `production_semantics_executable`.
    """
    known = frozenset(c["criterion_id"] for c in _jsonl(CRITERIA))
    return set(load_policy_logic_dir(LOGIC_DIR, known_criteria=known))


def _linkage() -> dict[tuple[str, str], list[str]]:
    """Provenances present per policy version, across both linkage files."""
    found: dict[tuple[str, str], list[str]] = {}
    for path in LINKAGE_FILES:
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        default = str(
            spec.get("default_provenance", spec.get("evidence_class_default", "HUMAN_CURATED"))
        )
        for link in spec["links"]:
            raw = str(link.get("provenance", link.get("evidence_class", default)))
            key = (link["policy_id"], str(link["policy_version"]))
            found.setdefault(key, []).append(LEGACY.get(raw, raw))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    criteria = _jsonl(CRITERIA)
    verification = json.loads(VERIFICATION.read_text(encoding="utf-8"))
    dependencies = json.loads(DEPENDENCIES.read_text(encoding="utf-8"))["dependencies"]
    linkage = _linkage()
    ncd_registry = yaml.safe_load(COVERAGE.read_text(encoding="utf-8"))
    cfr_registry = yaml.safe_load(CORPUS_REGISTRY.read_text(encoding="utf-8"))
    declared_logic = _declared_logic()
    ingested = {
        (d["policy_id"], str(d["revision_id"]))
        for d in (*cfr_registry["documents"], *_ncd_versions(ncd_registry))
    }

    # A query may support a slice only if it is scorable AND sits in a set whose
    # provenance is clean. A scorable query inside a contaminated set is still a
    # query whose report cannot be trusted as a whole.
    provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))["sets"]
    supported_by_evaluation: set[tuple[str, str]] = set()
    for block in provenance.values():
        if block["contaminated"]:
            continue
        for entry in block["entries"]:
            if entry["classification"].startswith("VALID") and entry["chain"]["intended_policy"]:
                supported_by_evaluation.add(
                    (entry["chain"]["intended_policy"], str(entry["chain"]["policy_version"]))
                )

    # Open domain decisions, keyed by the policy they block. A gate resolves ONLY
    # when a reviewer's decision has been accepted - `is_resolved` is written by the
    # gate type and nothing here can compute it.
    focus = json.loads(FOCUS_DECISION.read_text(encoding="utf-8"))
    open_gates: dict[tuple[str, str], list[str]] = {}
    if not focus["is_resolved"]:
        open_gates.setdefault((focus["policy_id"], focus["policy_version"]), []).append(
            f"{focus['focus_id']} is {focus['status']}"
        )
    ncd_versions = {
        (d["policy_id"], str(v["version"]))
        for d in ncd_registry["documents"]
        for v in d["versions"]
    }

    candidates: list[dict[str, Any]] = []
    for row in inventory["policies"]:
        policy_id, version = row["policy_id"], row["policy_version"]
        identity = PolicyIdentity.infer(policy_id, version)
        own = [
            c for c in criteria if c["policy_id"] == policy_id and c["policy_version"] == version
        ]
        blocked = [
            c["criterion_id"]
            for c in own
            if c["criterion_id"] in dependencies
            and not dependencies[c["criterion_id"]]["independently_adjudicable"]
        ]
        provenances = set(linkage.get((policy_id, version), []))
        incomplete_citations = [
            c["criterion_id"]
            for c in own
            if not (c.get("source_url") and c.get("source_section") and c.get("source_span"))
        ]

        admissible_links = provenances - {LinkProvenance.ENGINEERING_INFERRED.value}
        blocking_gates = open_gates.get((policy_id, version), [])

        checks = {
            "semantics_declared": row["logic_form"] == "DECLARED",
            # `failures` is a LIST of failures, not a count - reading it as a count
            # made every policy fail this check, which looked like a corpus problem
            # and was a reader problem. `passed` is the record's own verdict.
            "criteria_span_verified": (
                bool(own) and verification["passed"] and not verification["failures"]
            ),
            "no_unresolved_dependency": not blocked,
            "temporally_resolvable": (
                (policy_id, version) not in ncd_versions
                or any(
                    v["temporal_status"] == "DATED"
                    for d in ncd_registry["documents"]
                    if d["policy_id"] == policy_id
                    for v in d["versions"]
                    if str(v["version"]) == version
                )
            ),
            "coverage_status_established_or_not_required": (
                identity.policy_type is not PolicyType.NCD
            ),
            "no_engineering_inferred_linkage": (
                LinkProvenance.ENGINEERING_INFERRED.value not in provenances
            ),
            "citation_provenance_complete": bool(own) and not incomplete_citations,
            # A scope needs an ingested document AND at least one link production
            # would accept. Either alone builds a scope that retrieves nothing.
            "retrieval_scope_constructible": (
                (policy_id, version) in ingested and bool(admissible_links)
            ),
            "evaluation_provenance_sufficient": (policy_id, version) in supported_by_evaluation,
            # Distinct from `semantics_declared`: a declaration exists, and the
            # runtime must also be able to load and execute it. A declared policy
            # whose file fails to load is declared on paper only.
            "production_semantics_executable": row["logic_form"] == "DECLARED"
            and (policy_id, version) in declared_logic,
            "domain_decisions_resolved": not blocking_gates,
        }
        # Sorted, so the committed artefact is deterministic. Insertion order
        # survives a round trip through JSON for a list but not for a dict, so an
        # unsorted list here and a sorted `checks` there compare unequal for no
        # reason a reader could guess.
        failures = sorted(name for name, ok in checks.items() if not ok)
        candidates.append(
            {
                "policy_identity": str(identity),
                "policy_id": policy_id,
                "policy_version": version,
                "logic_form": row["logic_form"],
                "criteria": len(own),
                "checks": checks,
                "admissible": not failures,
                "failed_checks": failures,
                "blocked_criteria": blocked,
                "link_provenances": sorted(provenances),
            }
        )

    admissible = [c for c in candidates if c["admissible"]]
    status = "READY" if admissible else "BLOCKED"
    # The nearest miss, so a blocker is named rather than "nothing qualifies".
    nearest = min(candidates, key=lambda c: (len(c["failed_checks"]), c["policy_identity"]))

    report = {
        "status": status,
        "candidates": len(candidates),
        "admissible": [c["policy_identity"] for c in admissible],
        "designated_slice": admissible[0]["policy_identity"] if admissible else None,
        "nearest_candidate": nearest["policy_identity"],
        "nearest_candidate_blockers": nearest["failed_checks"],
        "assessment": candidates,
        "note": (
            "Admissibility is the CONJUNCTION of seven conditions, each read from a "
            "committed artefact. No slice is designated unless one passes all seven; "
            "a nearest candidate is reported so the remaining blocker is named rather "
            "than left as 'nothing qualifies'. Re-run after a reviewer closes a "
            "blocker - the answer changes without anyone editing a document."
        ),
    }

    width = max(len(c["policy_identity"]) for c in candidates)
    print(f"  {'policy':<{width}}  admissible  failed checks")
    for c in candidates:
        mark = "YES" if c["admissible"] else "no "
        print(
            f"  {c['policy_identity']:<{width}}  {mark:^10}  {', '.join(c['failed_checks']) or '-'}"
        )
    print()
    print(f"  STATUS: {status}")
    if admissible:
        print(f"  DESIGNATED SLICE: {report['designated_slice']}")
    else:
        print(f"  NO ADMISSIBLE SLICE. Nearest: {nearest['policy_identity']}")
        for blocker in nearest["failed_checks"]:
            print(f"    blocker: {blocker}")
        if nearest["blocked_criteria"]:
            print(f"    blocked criteria: {', '.join(nearest['blocked_criteria'])}")

    if args.write:
        OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n  written to {OUT.relative_to(REPO)}")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
