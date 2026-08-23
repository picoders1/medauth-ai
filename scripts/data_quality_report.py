"""Measure the data foundation and write a committed report.

    uv run python scripts/data_quality_report.py

Every number is counted from the artefacts on disk. No targets, no thresholds, no
"expected" values - a target here would invite tuning the dataset to meet it, which
is the one thing an evaluation set must never be shaped by.
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

from app.policy.acquire import LocalDirectorySource
from app.policy.chunk import chunk_sections
from app.policy.parse import parse_document
from app.policy.validate import validate_document

REPO = Path(__file__).resolve().parents[1]


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _pct(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator} ({numerator / denominator:.1%})" if denominator else "0/0"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="tests/fixtures/cms")
    parser.add_argument("--out", default="eval/reports")
    args = parser.parse_args()

    data = REPO / "data"
    criteria = _jsonl(data / "criteria" / "inventory.jsonl")
    cases = _jsonl(data / "synthetic" / "cases" / "cases.jsonl")
    gold = _jsonl(data / "gold" / "cases" / "gold_v1.jsonl")
    gold_manifest = json.loads((data / "gold" / "manifests" / "gold_v1.manifest.json").read_text())
    retrieval = yaml.safe_load(
        (REPO / "eval" / "datasets" / "retrieval" / "questions.yaml").read_text()
    )

    # ------------------------------------------------------- corpus ingestion
    acquired = list(LocalDirectorySource(REPO / args.corpus, synthetic=True).documents())
    parsed_ok, rejected, chunk_total, sections_total = 0, [], 0, 0
    versions: set[tuple[str, str]] = set()
    for item in acquired:
        try:
            document = parse_document(item.raw, item.source)
            validate_document(document, strict=True)
        except Exception as exc:
            rejected.append((Path(item.source.uri).name, f"{type(exc).__name__}: {exc}"[:110]))
            continue
        parsed_ok += 1
        sections_total += len(document.sections)
        chunk_total += len(chunk_sections(document.sections))
        versions.add((document.identity.policy_id, document.identity.revision_id))

    # ------------------------------------------------------------- provenance
    criteria_with_span = sum(1 for c in criteria if c["source_span"][1] > c["source_span"][0])
    criteria_with_chunk = sum(1 for c in criteria if c["source_chunk_refs"])
    criteria_with_page = sum(1 for c in criteria if c["source_page"] >= 1)

    linked_criteria = {c["criterion_id"] for c in criteria}
    case_criterion_refs = {
        entry["criterion_id"] for case in cases for entry in case["expected"]["criteria"]
    }
    dangling = case_criterion_refs - linked_criteria

    criterion_states = Counter(
        entry["state"] for case in cases for entry in case["expected"]["criteria"]
    )
    gold_states = Counter(entry["state"] for case in gold for entry in case["expected"]["criteria"])

    retrieval_questions = retrieval["questions"]
    retrieval_linked = [q for q in retrieval_questions if q["expect"].get("criterion_id")]
    retrieval_excluded = [q for q in retrieval_questions if q.get("unreachable_by_resolution")]

    lines = [
        "# Data Foundation Quality Report",
        "",
        "Counted from the artefacts on disk. **No targets are stated**, because a target",
        "here would invite shaping the dataset to meet it.",
        "",
        "> **The corpus is CMS-SHAPED, not CMS.** CMS is unreachable from this network",
        "> (a geographic edge block, not a crawl policy). Every artefact below carries",
        "> `provenance: synthetic`, and the first link of the credibility chain -",
        "> AUTHORITATIVE POLICY - is therefore **unfilled**. What is verified here is the",
        "> machinery, not the authority of the data it operates on.",
        "",
        "## Provenance",
        "",
        "| | |",
        "|---|---|",
        f"| generated_at | `{datetime.now(UTC).isoformat(timespec='seconds')}` |",
        f"| corpus | `{args.corpus}` |",
        "| corpus_kind | `synthetic` |",
        f"| criteria_sha256 | `{hashlib.sha256((data / 'criteria' / 'inventory.jsonl').read_bytes()).hexdigest()[:16]}` |",
        f"| cases_sha256 | `{hashlib.sha256((data / 'synthetic' / 'cases' / 'cases.jsonl').read_bytes()).hexdigest()[:16]}` |",
        f"| gold_sha256 | `{gold_manifest['sha256']['gold'][:16]}` |",
        f"| gold_set_version | `{gold_manifest['gold_set_version']}` |",
        f"| retrieval_set_version | `{retrieval['version']}` |",
        "",
        "## Corpus",
        "",
        "| metric | value |",
        "|---|---|",
        f"| documents acquired | {len(acquired)} |",
        f"| extraction success | {_pct(parsed_ok, len(acquired))} |",
        f"| documents rejected | {len(rejected)} |",
        f"| distinct policy versions | {len(versions)} |",
        f"| sections detected | {sections_total} |",
        f"| chunks produced | {chunk_total} |",
        "",
    ]
    if rejected:
        lines += ["Rejected, with reasons (nothing is silently discarded):", ""]
        lines += [f"- `{name}` - {reason}" for name, reason in rejected]
        lines += [""]
    else:
        lines += ["No document was rejected or quarantined.", ""]

    lines += [
        "## Criteria provenance",
        "",
        "| metric | value |",
        "|---|---|",
        f"| criteria in inventory | {len(criteria)} |",
        f"| with a verified source span | {_pct(criteria_with_span, len(criteria))} |",
        f"| with a source page | {_pct(criteria_with_page, len(criteria))} |",
        f"| linked to retrievable chunks | {_pct(criteria_with_chunk, len(criteria))} |",
        f"| duplicate criterion ids | {len(criteria) - len(linked_criteria)} |",
        "",
        "Every criterion was **span-verified against the section it declares**. A",
        "declaration whose text could not be located there is rejected at parse time,",
        "not stored with weaker provenance.",
        "",
        "## Cases",
        "",
        "| metric | value |",
        "|---|---|",
        f"| cases generated | {len(cases)} |",
        f"| duplicate case ids | {len(cases) - len({c['case_id'] for c in cases})} |",
        f"| dangling criterion references | {len(dangling)} |",
        f"| cases with a policy link | {_pct(sum(1 for c in cases if c['expected']['policy_id']), len(cases))} |",
        "| labels recomputable from criterion states | verified by test |",
        "",
        "### Category distribution (all cases)",
        "",
        "| category | n |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in sorted(Counter(c["category"] for c in cases).items())]
    lines += [
        "",
        "### Decision distribution (all cases)",
        "",
        "| decision | n |",
        "|---|---|",
    ]
    lines += [
        f"| {k} | {v} |"
        for k, v in sorted(Counter(c["expected"]["decision"] for c in cases).items())
    ]
    lines += [
        "",
        "### Criterion-state distribution",
        "",
        "| state | all cases | gold |",
        "|---|---|---|",
    ]
    for state in sorted(set(criterion_states) | set(gold_states)):
        lines.append(
            f"| {state} | {criterion_states.get(state, 0)} | {gold_states.get(state, 0)} |"
        )

    missing_all = sum(1 for c in cases if c["expected"]["missing_information"])
    missing_gold = sum(1 for c in gold if c["expected"]["missing_information"])
    lines += [
        "",
        "### Missing-information distribution",
        "",
        "| | all cases | gold |",
        "|---|---|---|",
        f"| cases naming missing information | {missing_all} | {missing_gold} |",
        f"| expected NEEDS_INFO | "
        f"{sum(1 for c in cases if c['expected']['decision'] == 'NEEDS_INFO')} | "
        f"{sum(1 for c in gold if c['expected']['decision'] == 'NEEDS_INFO')} |",
        "",
        "## Partitions",
        "",
        "| partition | n | may be used for |",
        "|---|---|---|",
        f"| development | {gold_manifest['counts']['development']} | prompt, retrieval, threshold and model selection |",
        f"| validation | {gold_manifest['counts']['validation']} | intermediate checks within a phase |",
        f"| gold | {gold_manifest['counts']['gold']} | **nothing but a budgeted final scoring** |",
        "",
        f"Disjointness and completeness are asserted by test. Gold scorings spent: "
        f"**{gold_manifest['scoring_budget']['scorings_spent']}** of "
        f"{gold_manifest['scoring_budget']['allowed_scorings']}.",
        "",
        "## Retrieval evaluation set",
        "",
        "| metric | value |",
        "|---|---|",
        f"| queries | {len(retrieval_questions)} |",
        f"| linked to a criterion | {_pct(len(retrieval_linked), len(retrieval_questions))} |",
        f"| criteria with at least one query | "
        f"{_pct(len({q['expect']['criterion_id'] for q in retrieval_linked}), len(criteria))} |",
        f"| excluded, with stated reason | {len(retrieval_excluded)} |",
        "",
        "## What this report does NOT establish",
        "",
        "- **Not that the policies are authoritative.** They are CMS-shaped documents",
        "  written for this project. Every downstream artefact inherits that.",
        "- **Not label quality in a clinical sense.** Labels are computed from criterion",
        "  states by `decide()`. They are consistent by construction, not expert judgement.",
        "- **Not that measured performance will transfer.** Constructed cases state each",
        "  fact once, unambiguously, where a reader expects it. Real submissions do not.",
        "- **Not inter-annotator agreement.** One labeller, and that labeller is a program.",
        "  Agreement was not measured because there is nothing to measure it between.",
        "",
    ]

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = REPO / args.out / f"{stamp}__data-foundation"
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"  report: {(out / 'report.md').relative_to(REPO)}")
    print(
        f"  documents {len(acquired)} | criteria {len(criteria)} | cases {len(cases)} | gold {len(gold)}"
    )
    print(
        f"  rejected {len(rejected)} | dangling refs {len(dangling)} | retrieval queries {len(retrieval_questions)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
