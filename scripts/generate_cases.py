"""Build the criteria inventory and the synthetic case corpus.

    uv run python scripts/generate_cases.py --corpus tests/fixtures/cms

Deterministic: the same corpus and seed rebuild both artefacts byte-for-byte, which
is what makes a dataset version mean anything.

Order is fixed - criteria are extracted and verified first, and cases are built
from them. Generating patients first and then hunting for a policy that fits would
produce labels that are opinions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from app.core.errors import MedauthError
from app.policy.acquire import LocalDirectorySource
from app.policy.chunk import chunk_sections
from app.policy.parse import parse_document
from app.policy.transcription import load_transcriptions, verify_transcription
from app.policy.validate import validate_document
from eval.casegen import (
    SCHEMA_VERSION,
    CaseCategory,
    CasePlan,
    PolicyRef,
    build_cases,
    corpus_digest,
)

REPO = Path(__file__).resolve().parents[1]

#: Cases per category, per policy version. Chosen so every category has enough
#: instances to survive a stratified partition with a usable gold count, not to
#: hit a round total.
PER_POLICY: dict[CaseCategory, int] = {
    CaseCategory.CLEARLY_SATISFIES: 6,
    CaseCategory.CLEARLY_FAILS: 6,
    CaseCategory.EXCLUSION_PRESENT: 4,
    CaseCategory.MISSING_DOCUMENTATION: 6,
    CaseCategory.INSUFFICIENT_EVIDENCE: 4,
    CaseCategory.BORDERLINE: 4,
    CaseCategory.CONFLICTING_EVIDENCE: 3,
}
#: Cases whose requested procedure resolves to no policy at all. Row 1 of the
#: decision table must return NEEDS_INFO for every one of them - never a denial.
NOT_APPLICABLE_TOTAL = 24


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="data/cms")
    parser.add_argument("--seed", type=int, default=20260823)
    parser.add_argument("--out", default="data")
    args = parser.parse_args()

    corpus_dir = REPO / args.corpus
    out = REPO / args.out
    templates_path = out / "synthetic" / "case_templates.yaml"
    templates = yaml.safe_load(templates_path.read_text(encoding="utf-8"))

    # Criteria come from the VERIFIED inventory, never re-derived here. A case can
    # therefore only cite a criterion that passed the span-verification gate.
    inventory_path = out / "criteria" / "inventory.jsonl"
    if not inventory_path.is_file():
        print("run scripts/verify_criteria.py first", file=sys.stderr)
        return 1
    verified_rows = [
        json.loads(line) for line in inventory_path.read_text().splitlines() if line.strip()
    ]
    verified_keys = {(r["policy_id"], r["policy_version"]) for r in verified_rows}

    # Acquired documents carry no criteria - a regulation is transcribed, not
    # self-declaring. Attach the CURATED, ALREADY-VERIFIED criteria here, so a case
    # can only ever be built on criteria that passed the gate.
    transcriptions = load_transcriptions(REPO / "data/criteria/transcriptions")

    linkage = yaml.safe_load((REPO / "data/linkage/policy_code_links.yaml").read_text())
    procedures: dict[tuple[str, str], list[str]] = {}
    diagnoses: dict[tuple[str, str], list[str]] = {}
    for link in linkage["links"]:
        key = (link["policy_id"], link["policy_version"])
        if link["linkage_type"] in {"COVERED_PROCEDURE", "EXCLUDED"}:
            procedures.setdefault(key, []).append(link["code"])
        else:
            diagnoses.setdefault(key, []).append(link["code"])

    # ---------------------------------------------------------------- criteria
    documents = list(LocalDirectorySource(corpus_dir, synthetic=True).documents())
    plans: list[CasePlan] = []
    policy_rows: list[dict[str, Any]] = []

    for acquired in documents:
        parsed = parse_document(acquired.raw, acquired.source)
        validate_document(parsed, strict=True)
        identity = parsed.identity
        chunks = chunk_sections(parsed.sections)

        policy_rows.append(
            {
                "policy_id": identity.policy_id,
                "document_type": identity.document_type.value,
                "revision_id": identity.revision_id,
                "criteria": len(
                    transcriptions[(identity.policy_id, identity.revision_id)].declarations
                )
                if (identity.policy_id, identity.revision_id) in transcriptions
                else 0,
                "chunks": len(chunks),
            }
        )

        key = (identity.policy_id, identity.revision_id)
        if key not in verified_keys or key not in procedures:
            continue
        if transcriptions[key].policy_role == "EXCLUSION_OVERLAY":
            # Real, authoritative, and still not a basis for a standalone decision:
            # it declares no required criteria, so every case would land on the
            # decision table's totality guard. Its criteria remain available for
            # retrieval and for attachment to a primary policy.
            print(f"  skipping {key[0]} for case generation: EXCLUSION_OVERLAY")
            continue
        criteria = verify_transcription(
            transcriptions[key],
            parsed.sections,
            document_policy_id=identity.policy_id,
            document_revision_id=identity.revision_id,
        )

        plans.append(
            CasePlan(
                policy=PolicyRef(
                    policy_id=identity.policy_id,
                    revision_id=identity.revision_id,
                    document_title=identity.title,
                    jurisdiction=identity.jurisdiction,
                    effective_date=identity.effective_date,
                    end_date=identity.end_date,
                    # From the CURATED linkage, not from the document: 42 CFR
                    # states conditions and does not enumerate procedure codes.
                    procedure_code=procedures[key][0],
                    code_system="HCPCS",
                    diagnosis_codes=tuple(diagnoses.get(key, ())),
                    criteria=criteria,
                ),
                counts=dict(PER_POLICY),
            )
        )

    if not plans:
        print("no policy version declared usable criteria", file=sys.stderr)
        return 1

    # Not-applicable cases are spread across policies so they do not all inherit
    # one policy's date window.
    per_plan = NOT_APPLICABLE_TOTAL // len(plans)
    remainder = NOT_APPLICABLE_TOTAL - per_plan * len(plans)
    for index, plan in enumerate(plans):
        plan.counts[CaseCategory.POLICY_NOT_APPLICABLE] = per_plan + (1 if index < remainder else 0)

    cases = build_cases(
        plans,
        templates["templates"],
        seed=args.seed,
        distractors=templates.get("distractors", []),
    )
    records = [case.to_record() for case in cases]

    # ------------------------------------------------------------------ write
    (out / "criteria").mkdir(parents=True, exist_ok=True)
    (out / "synthetic" / "cases").mkdir(parents=True, exist_ok=True)

    cases_path = out / "synthetic" / "cases" / "cases.jsonl"
    cases_path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in records) + "\n", encoding="utf-8"
    )

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "generator_seed": args.seed,
        "case_schema_version": SCHEMA_VERSION,
        "template_version": templates["version"],
        "corpus": args.corpus,
        "corpus_kind": "synthetic",
        "policy_versions": policy_rows,
        "criteria_count": len(verified_rows),
        "criteria_sha256": _sha256(REPO / "data/criteria/inventory.jsonl"),
        "case_count": len(records),
        "cases_sha256": _sha256(cases_path),
        "corpus_digest": corpus_digest(records),
        "category_distribution": dict(Counter(r["category"] for r in records)),
        "decision_distribution": dict(Counter(r["expected"]["decision"] for r in records)),
        "temporal_distribution": dict(Counter(r["temporal_class"] for r in records)),
    }
    (out / "synthetic" / "manifests").mkdir(parents=True, exist_ok=True)
    (out / "synthetic" / "manifests" / "cases.manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"  criteria      {len(verified_rows)} (verified; written by verify_criteria.py)")
    print(f"  cases         {len(records)} -> {cases_path.relative_to(REPO)}")
    print(f"  categories    {manifest['category_distribution']}")
    print(f"  decisions     {manifest['decision_distribution']}")
    print(f"  temporal      {manifest['temporal_distribution']}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except MedauthError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        sys.exit(1)
