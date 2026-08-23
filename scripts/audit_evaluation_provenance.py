"""Can every evaluation query prove its own provenance chain?

    query -> intended policy -> policy version -> criterion -> evidence chunk

A query that cannot prove that chain is not a hard query, it is an unusable one:
whatever it measures, it is not what its label says. This audits both retrieval sets
against the corpus as it stands now and classifies every query. **Nothing is
silently repaired.**

Four classifications, per the Phase 7 brief:

    VALID_AUTHORITATIVE   the chain rests on a source-stated relationship
    VALID_HUMAN_CURATED   the chain rests on a curated judgement, admissible
    INVALID_INFERRED      the chain rests on an ENGINEERING_INFERRED link, which
                          production resolution refuses - so the query cannot
                          resolve in production and measures nothing there
    REQUIRES_REVIEW       the chain is broken for some other reason: an unknown
                          criterion, an unresolvable policy version, a code in no
                          linkage file

Writes `data/review/evaluation_provenance.json`.

    uv run python scripts/audit_evaluation_provenance.py --write
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from app.core.identity import PolicyIdentity
from app.policy.models import LinkProvenance

REPO = Path(__file__).resolve().parents[1]
CRITERIA = REPO / "data/criteria/inventory.jsonl"
INVENTORY = REPO / "data/policy_logic/inventory.json"
LINKAGE_FILES = (
    REPO / "data/linkage/policy_code_links.yaml",
    REPO / "data/linkage/ncd_code_links.yaml",
)
SETS = {
    "retrieval_v1": REPO / "eval/datasets/retrieval/questions.yaml",
    "retrieval_v2": REPO / "eval/datasets/retrieval_v2/questions.yaml",
    "retrieval_v3": REPO / "eval/datasets/retrieval_v3/questions.yaml",
}

#: A query may be used in a model comparison only if its chain is provable. The two
#: VALID_* values are the whole of that permission; everything else is a query whose
#: intended evidence cannot be justified, and scoring one measures something other
#: than what its label says.
SCORABLE = frozenset({"VALID_AUTHORITATIVE", "VALID_HUMAN_CURATED"})
OUT = REPO / "data/review/evaluation_provenance.json"

LEGACY = {"AUTHORITATIVE": "SOURCE_STATED", "INFERRED": "ENGINEERING_INFERRED"}


def _links() -> dict[str, list[dict[str, Any]]]:
    """code -> the links that carry it, with provenance resolved."""
    found: dict[str, list[dict[str, Any]]] = {}
    for path in LINKAGE_FILES:
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        default = str(
            spec.get("default_provenance", spec.get("evidence_class_default", "HUMAN_CURATED"))
        )
        for link in spec["links"]:
            raw = str(link.get("provenance", link.get("evidence_class", default)))
            found.setdefault(str(link["code"]), []).append(
                {
                    "policy_id": link["policy_id"],
                    "policy_version": str(link["policy_version"]),
                    "linkage_type": link["linkage_type"],
                    "provenance": LEGACY.get(raw, raw),
                    "source_file": path.name,
                }
            )
    return found


def _classify(
    question: dict[str, Any],
    links: dict[str, list[dict[str, Any]]],
    criteria: set[str],
    versions: set[tuple[str, str]],
) -> dict[str, Any]:
    expect = question.get("expect") or {}
    code = str(question["procedure_code"])
    reasons: list[str] = []

    # A query deliberately recorded as unreachable is not a provenance failure -
    # it is a documented corpus gap (OD-15), and conflating the two would make the
    # audit report a defect where the project already recorded a limitation.
    if question.get("unreachable_by_resolution"):
        return {
            "classification": "REQUIRES_REVIEW",
            "reasons": [
                "recorded as unreachable by resolution (OD-15): the target declares "
                "no covered procedure, so no code can resolve to it"
            ],
            "link_provenances": [],
        }

    # A NEGATIVE query has no expected policy by design: it names a code that
    # resolves and asserts that nothing in the resolved scope answers it. Its
    # provenance chain is `query -> code -> resolved scope -> nothing relevant`,
    # which is shorter than the positive chain and is not a broken version of it.
    # Judging it against the positive chain reported six perfectly good queries as
    # defects.
    if question.get("expect_no_relevant"):
        candidates = links.get(code, [])
        admissible = [
            link
            for link in candidates
            if link["linkage_type"] == "COVERED_PROCEDURE"
            and link["provenance"] != LinkProvenance.ENGINEERING_INFERRED.value
        ]
        if not admissible:
            return {
                "classification": "INVALID_INFERRED" if candidates else "REQUIRES_REVIEW",
                "reasons": [
                    f"negative query: code {code} does not resolve through any "
                    "admissible link, so the query cannot reach a scope to be "
                    "negative about"
                ],
                "link_provenances": sorted({c["provenance"] for c in candidates}),
            }
        return {
            "classification": "VALID_HUMAN_CURATED",
            "reasons": [],
            "link_provenances": sorted({link["provenance"] for link in admissible}),
        }

    candidates = links.get(code, [])
    if not candidates:
        reasons.append(f"procedure code {code} appears in no linkage file")

    target = (expect.get("policy_id"), str(expect.get("revision_id") or ""))
    matching = [
        link
        for link in candidates
        if (link["policy_id"], link["policy_version"]) == target
        and link["linkage_type"] == "COVERED_PROCEDURE"
    ]
    if candidates and not matching:
        # Two different failures wear the same shape here, and separating them tells
        # a maintainer which thing to fix. Wrong POLICY means the query was authored
        # against a code that reaches a different policy entirely; wrong VERSION
        # means the policy is right and the revision is not.
        reached_policies = {c["policy_id"] for c in candidates}
        if target[0] not in reached_policies:
            return {
                "classification": "INVALID_POLICY_SCOPE",
                "reasons": [
                    f"code {code} reaches {sorted(reached_policies)}, not "
                    f"{target[0]!r}; the query cannot retrieve the policy it names"
                ],
                "link_provenances": sorted({c["provenance"] for c in candidates}),
            }
        return {
            "classification": "INVALID_VERSION",
            "reasons": [
                f"code {code} reaches {target[0]!r} at "
                f"{sorted({c['policy_version'] for c in candidates if c['policy_id'] == target[0]})}"
                f", not version {target[1]!r}"
            ],
            "link_provenances": sorted({c["provenance"] for c in candidates}),
        }

    if target[0] and target not in versions:
        return {
            "classification": "INVALID_VERSION",
            "reasons": [f"{target} is not a policy version in the logic inventory"],
            "link_provenances": sorted({link["provenance"] for link in matching}),
        }

    criterion_id = expect.get("criterion_id")
    if criterion_id and criterion_id not in criteria:
        reasons.append(f"criterion {criterion_id} is not in the inventory")

    provenances = sorted({link["provenance"] for link in matching})
    if matching and all(p == LinkProvenance.ENGINEERING_INFERRED.value for p in provenances):
        return {
            "classification": "INVALID_INFERRED",
            "reasons": [
                *reasons,
                "every link supporting this query is ENGINEERING_INFERRED, which "
                "production resolution refuses; the query cannot resolve in "
                "production and measures nothing there",
            ],
            "link_provenances": provenances,
        }

    if reasons:
        return {
            "classification": "REQUIRES_REVIEW",
            "reasons": reasons,
            "link_provenances": provenances,
        }

    classification = (
        "VALID_AUTHORITATIVE"
        if LinkProvenance.SOURCE_STATED.value in provenances
        else "VALID_HUMAN_CURATED"
    )
    return {"classification": classification, "reasons": [], "link_provenances": provenances}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    criteria = {
        json.loads(line)["criterion_id"]
        for line in CRITERIA.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    versions = {
        (row["policy_id"], row["policy_version"])
        for row in json.loads(INVENTORY.read_text(encoding="utf-8"))["policies"]
    }
    links = _links()

    report: dict[str, Any] = {
        "sets": {},
        "note": (
            "A query classified INVALID_INFERRED is NOT repaired here and NOT removed "
            "from its set. The historical set and its committed report stay exactly as "
            "they were - they record what was measured at the time. A corrected "
            "measurement needs a NEW dataset version; overwriting the old one would "
            "destroy the record of what the earlier numbers meant."
        ),
    }

    for name, path in SETS.items():
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        entries = []
        for question in spec["questions"]:
            verdict = _classify(question, links, criteria, versions)
            expect = question.get("expect") or {}
            entries.append(
                {
                    "id": question["id"],
                    "category": question.get("category", "UNSPECIFIED"),
                    "procedure_code": question["procedure_code"],
                    "chain": {
                        "intended_policy": expect.get("policy_id"),
                        "policy_version": expect.get("revision_id"),
                        "policy_identity": (
                            str(
                                PolicyIdentity.infer(
                                    expect["policy_id"], str(expect["revision_id"])
                                )
                            )
                            if expect.get("policy_id") and expect.get("revision_id")
                            else None
                        ),
                        "criterion": expect.get("criterion_id"),
                        "evidence_target": expect.get("section_path")
                        or [r["section_path"] for r in expect.get("relevance", [])],
                    },
                    **verdict,
                }
            )
        counts = Counter(e["classification"] for e in entries)
        scorable = sum(counts[c] for c in SCORABLE)
        report["sets"][name] = {
            "dataset": str(path.relative_to(REPO)),
            "queries": len(entries),
            "by_classification": dict(sorted(counts.items())),
            "scorable": scorable,
            "unscorable": len(entries) - scorable,
            # A set is contaminated if ANY query in it cannot prove its chain.
            # Not "mostly clean": a comparison run over a set containing unscorable
            # queries reports a rate whose denominator includes measurements that
            # mean nothing.
            "contaminated": scorable != len(entries),
            "usable_in_production_evaluation": scorable,
            "entries": entries,
        }

    for name, block in report["sets"].items():
        state = "CONTAMINATED" if block["contaminated"] else "CLEAN"
        print(f"  {name}  ({block['queries']} queries)  -> {state}")
        for classification, count in block["by_classification"].items():
            mark = "scorable" if classification in SCORABLE else "NOT scorable"
            print(f"    {classification:<22} {count:3d}  ({mark})")
        print(f"    scorable               {block['scorable']:3d}\n")

    if args.write:
        OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"  written to {OUT.relative_to(REPO)}")
    else:
        print("  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
