"""Fetch authoritative code metadata from the NLM Clinical Tables API.

    uv run python scripts/fetch_code_metadata.py

The NLM API is authoritative for **code existence and description**. It is not, and
is never treated as, evidence that a code is covered by any policy - that linkage is
curated separately and labelled as curated (see data/linkage/).

A note on the copyright boundary, which the source enforces rather than this code:
HCPCS Level II codes (letter + four digits) are CMS-maintained and public domain,
and the API returns their descriptors. CPT codes (five digits) are AMA-copyrighted
and are simply **absent** from this API, so the project cannot redistribute a CPT
descriptor even by accident (ADR-003).
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
ICD10 = "https://clinicaltables.nlm.nih.gov/api/icd10cm/v3/search"


def lookup(url: str, code: str) -> dict[str, Any] | None:
    response = httpx.get(
        url,
        params={"terms": code, "maxList": 5},
        timeout=25.0,
        headers={"user-agent": "medauth-ai/0.1 (research)"},
    )
    response.raise_for_status()
    payload = response.json()
    for returned_code, description in payload[3] or []:
        if returned_code.upper() == code.upper():
            return {"code": returned_code, "description": description}
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linkage", default="data/linkage/policy_code_links.yaml")
    parser.add_argument("--out", default="data/linkage/code_metadata.jsonl")
    args = parser.parse_args()

    linkage = yaml.safe_load((REPO / args.linkage).read_text(encoding="utf-8"))
    wanted: dict[tuple[str, str], None] = {}
    for link in linkage["links"]:
        wanted[(str(link["code"]), str(link["code_system"]))] = None

    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for code, system in sorted(wanted):
        url = HCPCS if system == "HCPCS" else ICD10
        found = lookup(url, code)
        if found is None:
            missing.append(f"{system} {code}")
            print(f"  {system:<8} {code:<10} NOT FOUND in the authoritative source")
        else:
            rows.append(
                {
                    "code": found["code"],
                    "code_system": system,
                    "description": found["description"],
                    "source": "NLM Clinical Tables",
                    "source_url": url,
                    "retrieved_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "authority": "code existence and description only; NOT coverage",
                }
            )
            print(f"  {system:<8} {found['code']:<10} {found['description'][:52]}")
        time.sleep(0.2)

    if missing:
        # A curated link to a code that does not exist is a curation error, and it
        # would otherwise surface much later as a resolution that never fires.
        print(f"\n  {len(missing)} code(s) do not exist: {missing}", file=sys.stderr)
        return 1

    out = REPO / args.out
    out.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n", encoding="utf-8")
    print(f"\n  {len(rows)} codes verified against NLM -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
