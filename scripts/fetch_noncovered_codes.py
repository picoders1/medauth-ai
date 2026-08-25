"""Verify codes that exist and are deliberately NOT covered by this corpus. R-97.

    uv run python scripts/fetch_noncovered_codes.py --write

gold_v1's `POLICY_NOT_APPLICABLE` cases carry `R0075` - a code the corpus genuinely
links to 42 CFR 410.33 - and encode their non-applicability only in the clinical
narrative ("Requested service: unlisted procedure 99199"). Deterministic resolution
reads the structured request, correctly resolves, and the gold label of decision-rule
1 becomes unreachable from the input. That is R-97.

gold_v2 fixes it by giving those cases a procedure code the corpus does not link.
The code has to be **real**, or the fix trades one fabrication for another: a case
asserting a code that does not exist would be non-applicable for the wrong reason,
and the first person to check would find the dataset inventing HCPCS.

So the codes are verified against the same authoritative source the covered ones use
- NLM Clinical Tables, which is authoritative for code **existence and description**
and is never treated as evidence of coverage.

## Why a separate file

`scripts/fetch_code_metadata.py` regenerates `code_metadata.jsonl` from the linkage
and would delete anything not linked. These codes are defined by *not* being linked,
so they live beside it and the two invariants stay separate:

    code_metadata.jsonl            every LINKED code exists
    noncovered_code_metadata.jsonl these codes exist and are NOT linked

The second invariant is asserted here at write time and again by a test, because a
code quietly acquiring a link later would silently make eighteen gold_v2 cases
applicable and their labels wrong.

## Copyright

HCPCS Level II codes are CMS-maintained and public domain, and this API returns their
descriptors. CPT codes are AMA-copyrighted and are absent from it, so no CPT
descriptor can be redistributed here even by accident (ADR-003). That is also why the
narrative's `99199` is not adopted as the structured code: it is CPT.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

REPO = Path(__file__).resolve().parents[1]
HCPCS = "https://clinicaltables.nlm.nih.gov/api/hcpcs/v3/search"
LINKAGE = REPO / "data/linkage/policy_code_links.yaml"
OUT = REPO / "data/linkage/noncovered_code_metadata.jsonl"

#: Chosen to be plainly outside this corpus - which covers diagnostic testing,
#: portable x-ray, IDTF supervision and related services under 42 CFR 410. An
#: ambulance transport, a pair of crutches, an orthosis and a personal-care service
#: are not near-misses; a reviewer reading one of these cases should find "no policy
#: here governs this" obvious rather than arguable.
CANDIDATES: tuple[str, ...] = ("A0428", "E0114", "L3806", "T1019")


def lookup(code: str) -> dict[str, Any] | None:
    response = httpx.get(
        HCPCS,
        params={"terms": code, "maxList": 5},
        timeout=25.0,
        headers={"user-agent": "medauth-ai/0.1 (research)"},
    )
    response.raise_for_status()
    payload = response.json()
    for returned, description in payload[3] or []:
        if returned.upper() == code.upper():
            return {"code": returned, "description": description}
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    linkage = yaml.safe_load(LINKAGE.read_text(encoding="utf-8"))
    linked = {(str(link["code"]), str(link["code_system"])) for link in linkage["links"]}

    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    for code in CANDIDATES:
        if (code, "HCPCS") in linked:
            # The whole point of this file is that these codes resolve to nothing.
            problems.append(f"{code} IS linked in policy_code_links.yaml")
            print(f"  HCPCS  {code:<8} REFUSED - it is linked, so it is not non-covered")
            continue
        found = lookup(code)
        if found is None:
            problems.append(f"{code} does not exist in the authoritative source")
            print(f"  HCPCS  {code:<8} NOT FOUND - a fabricated code is not a fix")
            continue
        rows.append(
            {
                "code": found["code"],
                "code_system": "HCPCS",
                "description": found["description"],
                "source": "NLM Clinical Tables",
                "source_url": HCPCS,
                "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "authority": "code existence and description only; NOT coverage",
                "role": (
                    "deliberately NOT linked in this corpus; used to construct "
                    "gold_v2 POLICY_NOT_APPLICABLE cases whose applicability is "
                    "derivable from structured input alone (R-97)"
                ),
            }
        )
        print(f"  HCPCS  {found['code']:<8} {found['description'][:56]}")
        time.sleep(0.2)

    if problems:
        print(f"\n  refusing: {problems}", file=sys.stderr)
        return 1

    if args.write:
        OUT.write_text(
            "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8"
        )
        print(f"\n  {len(rows)} non-covered codes verified -> {OUT.relative_to(REPO)}")
    else:
        print("\n  (dry run; pass --write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
