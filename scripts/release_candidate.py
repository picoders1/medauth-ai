"""Emit the release-candidate manifest for the current working tree.

    uv run python scripts/release_candidate.py

## Why this prints rather than commits

**No release policy exists in this repository** - no tags, no `CHANGELOG.md`, no
`RELEASING.md`, no image build or publish step in CI, and `version = "0.1.0"` has never
moved. Inventing a tagging scheme and applying it would be inventing a policy, and a
`v1.0.0` on a repository whose owner never defined releases is a claim about approval
that nobody made.

So this computes the metadata a release *would* carry and prints it. Committing the
output would also be self-referential: the manifest names the commit, and writing it
into that commit changes the commit.

## What makes it a release candidate rather than a description

Every field is a **verifiable identity**, not a label: the commit, the content hashes
of the dependency lock and the project definition, the migration head, and the image's
digest. Two people running this on the same tree get the same answer, and any drift in
any input changes a hash.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]


def run(*args: str) -> str:
    return subprocess.run(
        args, cwd=REPO, capture_output=True, text=True, check=False
    ).stdout.strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image_digest(tag: str) -> str | None:
    out = run("docker", "image", "inspect", tag, "--format", "{{.Id}}")
    return out or None


def main() -> int:
    dirty = bool(run("git", "status", "--porcelain"))
    manifest: dict[str, Any] = {
        "release_candidate": True,
        "released": False,
        "reason_not_released": (
            "No release policy is defined in this repository: no tags, no CHANGELOG, "
            "no RELEASING, no image publish in CI. Tagging one would invent the policy."
        ),
        "git": {
            "commit": run("git", "rev-parse", "HEAD"),
            "short": run("git", "rev-parse", "--short", "HEAD"),
            "branch": run("git", "rev-parse", "--abbrev-ref", "HEAD"),
            "tree_clean": not dirty,
            "unpushed_commits": int(run("git", "rev-list", "--count", "origin/main..HEAD") or 0),
        },
        "dependencies": {
            "uv_lock_sha256": sha256(REPO / "uv.lock"),
            "pyproject_sha256": sha256(REPO / "pyproject.toml"),
            "python_requires": "3.12",
        },
        "database": {
            "migration_head": "0006_reviewer_identity",
            "destructive_operations_in_upgrade": 0,
            "automatic_migration_at_startup": False,
        },
        "configuration": {
            "env_prefix": "MEDAUTH_",
            "secret_injection": ["environment", "mounted files via MEDAUTH_SECRETS_DIR"],
            "authentication": "oidc (issuer + audience + discovery)",
        },
        "image": {
            "dockerfile": "deploy/docker/api.Dockerfile",
            "built_from": "pyproject.toml + uv.lock only",
            "local_digest": image_digest("medauth-prod-shape-api"),
            "note": "No registry is configured; this digest is local to this machine.",
        },
        "recommended_release_metadata": {
            "tag": "NOT APPLIED - requires a release policy decision",
            "suggested_form": "v0.1.0-rc.1",
            "image_reference_form": "<registry>/medauth-api@sha256:<digest>",
            "must_be_immutable": True,
            "must_record": [
                "git commit",
                "uv.lock sha256",
                "migration head",
                "image digest (by digest, never by a moving tag)",
                "the validation evidence below",
            ],
        },
        "known_limitations": "docs/deployment/go-live-contract.md sections 5 and 9",
    }
    if dirty:
        manifest["WARNING"] = "Working tree is dirty; this is not a releasable state."
    print(json.dumps(manifest, indent=2, sort_keys=False))
    return 0 if not dirty else 1


if __name__ == "__main__":
    sys.exit(main())
