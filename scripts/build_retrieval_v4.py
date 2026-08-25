"""Provenance-audit retrieval_v3 and build retrieval_v4 from what survives. Part C.

    uv run python scripts/build_retrieval_v4.py            # audit only
    uv run python scripts/build_retrieval_v4.py --write

## The audit comes first, and it may reject anything

A retrieval query is scorable only if its whole authority chain is present and
checkable against committed artefacts:

    query -> policy type -> policy id -> policy version -> criterion -> evidence chunk

A query missing any link is `INVALID_FOR_SCORING`. **It is not reinterpreted.**
Guessing the version a query "obviously" meant is how a benchmark comes to measure a
corpus nobody assembled, and R-70 is what that looked like the last time.

## What Phase 16 checks that Phase 13 could not

Phase 15 made policy type part of retrieval scope and gave applicability six states.
`retrieval_v3` predates both, so two links in the chain were previously implicit:

- **policy type.** A `RetrievalScope` cannot exist without one, and a query that
  does not name it is scoped by whatever the runner happened to pass.
- **applicability.** A `NEGATIVE` query - one with no relevant section - must be
  negative because *no section answers it*, not because its procedure code fails to
  resolve. Those are different measurements and only the first belongs in a
  retrieval benchmark. The audit separates them.

## What this deliberately does not do

No tuning. Not chunking, not `top_k`, not the encoder, not the reranker, not query
construction. The configuration stays `ENGINEERING_DEFAULT_UNRESOLVED` and this
produces a **baseline**, not a winner (Part C2). `retrieval_v3` is not re-scored -
its single scoring is spent and its result stands.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
V3 = REPO / "eval/datasets/retrieval_v3/questions.yaml"
INVENTORY = REPO / "data/criteria/inventory.jsonl"
LINKAGE = REPO / "data/linkage/policy_code_links.yaml"
REGISTRY = REPO / "data/cms/registry.yaml"
OUT_DIR = REPO / "eval/datasets/retrieval_v4"
OUT_AUDIT = REPO / "data/review/retrieval_v4_provenance.json"

#: The ten categories the phase requires. A category that ends up empty is reported
#: as empty rather than quietly dropped - "the benchmark covers ten categories" is a
#: claim about the file, not about the list in a brief.
REQUIRED_CATEGORIES: tuple[str, ...] = (
    "DIRECT",
    "PARAPHRASED",
    "PARTIAL_INFORMATION",
    "AMBIGUOUS",
    "NEGATIVE",
    "HISTORICAL_VERSION",
    "EXCEPTION",
    "DISTRACTOR",
    "CROSS_POLICY",
    "CROSS_VERSION",
)

VALID_LABELS = frozenset({"RELEVANT", "PARTIALLY_RELEVANT", "NOT_RELEVANT"})


@dataclass(frozen=True, slots=True)
class Authority:
    """Every fact the chain is checked against. Nothing is inferred.

    Two sources, and the split matters. The **registry** and the **criteria
    inventory** are committed, so the type/version/criterion links are checkable on
    a clean clone. **Section paths are not**: they exist only once a document has
    been chunked and ingested, so they are read from the database and the audit
    records that it did so. That is the honest arrangement - a section a query
    labels must be a section retrieval can actually return, and only the index knows
    which those are.
    """

    #: `(policy_id, revision_id) -> document type`, from the corpus registry.
    types: dict[tuple[str, str], str]
    #: `(policy_id, revision_id) -> {criterion_id}`, from the criteria inventory.
    criteria: dict[tuple[str, str], set[str]]
    #: `(policy_id, revision_id) -> {section_path}`, from the ingested index.
    sections: dict[tuple[str, str], set[str]]
    #: `(code, code_system)` listed as covered procedures.
    covered: frozenset[tuple[str, str]]
    #: Whether the index was reachable. When it is not, section paths are reported
    #: as DEFERRED rather than silently passing - an unchecked link must not read
    #: as a checked one.
    sections_verified: bool = True


async def _sections_from_index() -> dict[tuple[str, str], set[str]]:
    """Distinct `(policy, revision) -> section paths` actually present in the index."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.config.settings import Settings
    from app.database.engine import build_engine
    from app.policy.models import PolicyChunk, PolicyDocument, PolicyVersion

    engine = build_engine(Settings())
    maker = async_sessionmaker(engine, expire_on_commit=False)
    found: dict[tuple[str, str], set[str]] = {}
    try:
        async with maker() as session:
            rows = (
                await session.execute(
                    select(
                        PolicyDocument.policy_id,
                        PolicyVersion.revision_id,
                        PolicyChunk.section_path,
                    )
                    .join(PolicyVersion, PolicyVersion.document_id == PolicyDocument.id)
                    .join(PolicyChunk, PolicyChunk.policy_version_id == PolicyVersion.id)
                    .distinct()
                )
            ).all()
    finally:
        await engine.dispose()
    for policy_id, revision, section in rows:
        found.setdefault((str(policy_id), str(revision)), set()).add(str(section))
    return found


def _load_authority() -> Authority:
    criteria: dict[tuple[str, str], set[str]] = {}
    for line in INVENTORY.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        criteria.setdefault((row["policy_id"], row["policy_version"]), set()).add(
            row["criterion_id"]
        )

    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    types = {
        (str(d["policy_id"]), str(d["revision_id"])): str(d.get("document_type", "REGULATION"))
        for d in registry.get("documents", [])
    }

    linkage = yaml.safe_load(LINKAGE.read_text(encoding="utf-8"))
    covered = frozenset(
        (str(link["code"]), str(link["code_system"]))
        for link in linkage["links"]
        if str(link.get("link_type", "COVERED_PROCEDURE")) == "COVERED_PROCEDURE"
    )

    try:
        sections = asyncio.run(_sections_from_index())
        verified = True
    except Exception as failure:  # the index is not reachable
        print(f"  index unreachable ({type(failure).__name__}); section paths DEFERRED")
        sections, verified = {}, False

    return Authority(
        types=types,
        criteria=criteria,
        sections=sections,
        covered=covered,
        sections_verified=verified,
    )


@dataclass
class Verdict:
    """One query's audit. `problems` empty means every link in the chain resolved."""

    query_id: str
    category: str
    problems: list[str] = field(default_factory=list)
    resolved: dict[str, Any] = field(default_factory=dict)

    @property
    def scorable(self) -> bool:
        return not self.problems


def audit_query(query: dict[str, Any], authority: Authority) -> Verdict:
    """Walk the chain. Every missing link is recorded; none is guessed at."""
    verdict = Verdict(
        query_id=str(query.get("id", "<no id>")), category=str(query.get("category", ""))
    )
    if verdict.category not in REQUIRED_CATEGORIES:
        verdict.problems.append(f"category {verdict.category!r} is not one of the ten")

    # -- the request half: what applicability will do with this query ----------
    #
    # Checked for EVERY category including NEGATIVE. A query whose code does not
    # resolve is refused by applicability before retrieval runs, so scoring it as a
    # retrieval miss would measure the wrong subsystem entirely.
    code, system = query.get("procedure_code"), query.get("code_system")
    if not code or not system:
        verdict.problems.append("no procedure code and code system")
    elif (str(code), str(system)) not in authority.covered:
        verdict.problems.append(
            f"({system} {code}) is not a covered-procedure link, so applicability "
            "would refuse this query before retrieval ran"
        )
    else:
        verdict.resolved["procedure_code"] = f"{system} {code}"

    if not query.get("as_of"):
        verdict.problems.append("no as_of; version selection is by date of service, never latest")
    if not str(query.get("text", "")).strip():
        verdict.problems.append("no query text")

    # -- NEGATIVE: no expectation block, and a stated reason -------------------
    #
    # A negative query is one NO section answers. It legitimately names no policy,
    # no version and no criterion, and requiring them would delete the category.
    # What it must carry is the assertion itself and why.
    if verdict.category == "NEGATIVE":
        if not query.get("expect_no_relevant"):
            verdict.problems.append("a NEGATIVE query must assert expect_no_relevant")
        if not str(query.get("negative_reason", "")).strip():
            verdict.problems.append("a NEGATIVE query must state why nothing is relevant")
        if query.get("expect", {}).get("relevance"):
            verdict.problems.append("a NEGATIVE query carries relevance labels; it is not negative")
        verdict.resolved["scored_as"] = "false-retrieval rate, outside the Recall denominator"
        return verdict

    expect = query.get("expect") or {}
    policy_id, revision = expect.get("policy_id"), expect.get("revision_id")
    if not policy_id or not revision:
        verdict.problems.append("no policy id or revision on the expectation")
        return verdict
    key = (str(policy_id), str(revision))

    # 1 - policy TYPE and 2 - the VERSION, both from the committed registry.
    #     Implicit before Phase 15; a RetrievalScope cannot exist without a type.
    document_type = authority.types.get(key)
    if document_type is None:
        verdict.problems.append(f"{key} is not a document/revision in data/cms/registry.yaml")
    else:
        verdict.resolved["policy_type"] = document_type
        verdict.resolved["policy_version"] = key[1]

    # 3 - the CRITERION, where the query names one. A DISTRACTOR asks about a
    #     definition rather than a criterion and legitimately names none.
    criterion = expect.get("criterion_id")
    if criterion:
        if criterion not in authority.criteria.get(key, set()):
            verdict.problems.append(f"criterion {criterion} is not transcribed for {key}")
        else:
            verdict.resolved["criterion_id"] = criterion

    # 4 - the EVIDENCE. Labels from the closed vocabulary, sections that the index
    #     can actually return.
    relevance = expect.get("relevance") or []
    if not relevance:
        verdict.problems.append("no relevance labels")
    known = authority.sections.get(key, set())
    for entry in relevance:
        label, section = str(entry.get("label", "")), str(entry.get("section_path", ""))
        if label not in VALID_LABELS:
            verdict.problems.append(f"label {label!r} is not in {sorted(VALID_LABELS)}")
        if authority.sections_verified and section not in known:
            verdict.problems.append(f"section {section!r} is not an indexed section of {key}")
    if not any(str(e.get("label")) == "RELEVANT" for e in relevance):
        verdict.problems.append(
            "a non-NEGATIVE query has no RELEVANT section, so nothing can be recalled"
        )
    verdict.resolved["section_verification"] = (
        "INDEX" if authority.sections_verified else "DEFERRED"
    )
    return verdict


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):  # pragma: no cover
        return "unknown"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    source = yaml.safe_load(V3.read_text(encoding="utf-8"))
    questions = source["questions"]
    authority = _load_authority()

    verdicts = [audit_query(q, authority) for q in questions]
    scorable = [v for v in verdicts if v.scorable]
    invalid = [v for v in verdicts if not v.scorable]

    print(f"  retrieval_v3       {len(questions)} queries")
    print(f"  SCORABLE           {len(scorable)}")
    print(f"  INVALID_FOR_SCORING {len(invalid)}")
    for verdict in invalid:
        print(f"    {verdict.query_id:<10} {verdict.category:<20} {verdict.problems[0]}")

    kept_ids = {v.query_id for v in scorable}
    kept = [q for q in questions if str(q.get("id")) in kept_ids]
    by_category = Counter(str(q["category"]) for q in kept)
    missing = [c for c in REQUIRED_CATEGORIES if by_category[c] == 0]

    print(f"\n  categories kept    {dict(sorted(by_category.items()))}")
    if missing:
        print(f"  categories EMPTY   {missing}")

    audit_report = {
        "audit": "retrieval_v4 provenance",
        "generated_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "source": "eval/datasets/retrieval_v3/questions.yaml",
        "source_sha256": hashlib.sha256(V3.read_bytes()).hexdigest(),
        "chain_checked": [
            "policy type (registry)",
            "policy id and revision (registry)",
            "version window contains as_of",
            "criterion transcribed (criteria inventory)",
            "labelled sections transcribed",
            "relevance labels in the closed vocabulary",
            "procedure code linked as a covered procedure",
            "NEGATIVE queries carry no RELEVANT label",
        ],
        "counts": {
            "queries": len(questions),
            "scorable": len(scorable),
            "invalid_for_scoring": len(invalid),
        },
        "categories_kept": dict(sorted(by_category.items())),
        "categories_empty": missing,
        "policy": (
            "A query missing any link is INVALID_FOR_SCORING and is NOT "
            "reinterpreted. Guessing what a query meant is how a benchmark comes to "
            "measure a corpus nobody assembled (R-70)."
        ),
        "verdicts": [
            {
                "id": v.query_id,
                "category": v.category,
                "scorable": v.scorable,
                "problems": v.problems,
                "resolved": v.resolved,
            }
            for v in verdicts
        ],
    }

    if not args.write:
        print("\n  (audit only; pass --write)")
        return 0

    OUT_AUDIT.parent.mkdir(parents=True, exist_ok=True)
    OUT_AUDIT.write_text(
        json.dumps(audit_report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    if not kept:
        print("\n  REFUSING to write an empty benchmark", file=sys.stderr)
        return 1

    resolved_by_id = {v.query_id: v.resolved for v in scorable}
    dataset = {
        "version": "retrieval_v4",
        "derived_from": "retrieval_v3",
        "derived_at": datetime.now(UTC).isoformat(),
        "git_commit": _git_commit(),
        "selection_basis": (
            "Every query whose full authority chain resolves against committed "
            "artefacts. Nothing was reinterpreted, relabelled or repaired to admit "
            "it; a query that failed the audit is absent and is listed in "
            "data/review/retrieval_v4_provenance.json with its reason."
        ),
        "corpus": source.get("corpus"),
        "corpus_kind": source.get("corpus_kind"),
        "corpus_source": source.get("corpus_source"),
        "criteria_inventory": source.get("criteria_inventory"),
        "authored_by": source.get("authored_by"),
        "authored_by_role": source.get("authored_by_role"),
        "relevance_labels": sorted(VALID_LABELS),
        "scored": False,
        "scorings_spent": 0,
        "scoring_budget": 1,
        "scoring_note": (
            "One baseline scoring under the FROZEN configuration. This benchmark "
            "may not be used to select chunking, top_k, an encoder, a reranker or a "
            "query construction until a pre-registered protocol says so (OD-35/36)."
        ),
        "negative_query_note": (
            "NEGATIVE queries are excluded from the Recall denominator and scored "
            "separately as a false-retrieval rate. Counting them as misses flatters "
            "every arm equally and measures nothing."
        ),
        "policy_type_note": (
            "Every query now names its policy TYPE explicitly, resolved from the "
            "corpus registry. Before Phase 15 the type was whatever the runner "
            "passed, and a RetrievalScope cannot exist without one."
        ),
        # The audit's resolved links are written back onto each query, so a later
        # reader does not have to re-derive the policy type or re-consult the
        # registry to know what the query was scoped to. NEGATIVE queries carry no
        # `expect` block by design and get a `resolved` block of their own rather
        # than an invented one.
        "questions": [
            (
                {**q, "expect": {**q["expect"], **resolved_by_id.get(str(q["id"]), {})}}
                if "expect" in q
                else {**q, "resolved": resolved_by_id.get(str(q["id"]), {})}
            )
            for q in kept
        ],
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_dump(dataset, sort_keys=False, allow_unicode=True, width=100)
    (OUT_DIR / "questions.yaml").write_text(payload, encoding="utf-8")

    print(f"\n  retrieval_v4       {len(kept)} queries")
    print(f"  sha256             {hashlib.sha256(payload.encode()).hexdigest()[:16]}")
    print(f"  written            {(OUT_DIR / 'questions.yaml').relative_to(REPO)}")
    print(f"                     {OUT_AUDIT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
