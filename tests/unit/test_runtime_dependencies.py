"""Everything `app/` imports must be declared, not inherited from something else.

**Regression.** `app/api/reviewer_ui.py` imports `Jinja2Templates` at module scope and
`app/api/main.py` imports that router, so jinja2 is a hard runtime requirement of the
application. It was never declared in `pyproject.toml`. It worked locally only because
`torch` - an *optional* `retrieval` extra, excluded from the production image - happened
to pull it in.

The image is built with `uv export --no-dev`, so the container got no jinja2 and
**could not start at all**: uvicorn failed at import. Nobody saw it because nobody had
rebuilt the image since the reviewer UI landed; the running container was three days
stale and still served the previous code.

A dependency satisfied by somebody else's transitive graph is not a dependency you
have. It disappears the moment they drop it, and it is absent anywhere the extra is
not installed - which is precisely where the application actually runs.

Two tests, because they catch different things. The first scans `app/` for undeclared
third-party imports. It could not have caught jinja2: nothing under `app/` imports
jinja2 - `reviewer_ui.py` imports `fastapi.templating`, which itself fails to load
without it. The second names jinja2 directly for that reason.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[2]
APP = REPO / "app"


def _top_level_imports() -> set[str]:
    """Every top-level module `app/` imports, from the AST rather than by importing."""
    names: set[str] = set()
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def _declared_distributions() -> set[str]:
    """Distributions named directly in pyproject - runtime and optional extras."""
    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    project = data["project"]
    requirements = list(project.get("dependencies", []))
    for extra in (project.get("optional-dependencies") or {}).values():
        requirements.extend(extra)
    declared: set[str] = set()
    for requirement in requirements:
        # "sqlalchemy[asyncio]>=2.0.35,<3.0" -> "sqlalchemy"
        name = requirement.split(";")[0].strip()
        for separator in ("[", ">", "<", "=", "!", "~", " "):
            name = name.split(separator)[0]
        declared.add(name.strip().lower().replace("_", "-"))
    return declared


def test_every_third_party_import_under_app_is_declared() -> None:
    """A transitive dependency is not a declared one, and the image proves it."""
    stdlib = set(sys.stdlib_module_names)
    first_party = {"app"}
    distributions = packages_distributions()

    declared = _declared_distributions()
    undeclared: list[str] = []
    for module in sorted(_top_level_imports()):
        if module in stdlib or module in first_party or module.startswith("_"):
            continue
        providers = {d.lower().replace("_", "-") for d in distributions.get(module, [])}
        if not providers:
            # Not importable in this environment at all - a different failure, and the
            # test suite would already be red. Nothing to assert here.
            continue
        if not providers & declared:
            undeclared.append(f"{module} (provided by {sorted(providers)})")

    assert not undeclared, (
        "app/ imports these at runtime but pyproject.toml declares none of them, so "
        "`uv export --no-dev` omits them and the production image cannot import the "
        "application: " + "; ".join(undeclared)
    )


def test_jinja2_specifically_is_declared() -> None:
    """The one that broke the image, and the test above cannot see it.

    **No module under `app/` imports jinja2.** `reviewer_ui.py` imports
    `fastapi.templating`, and *that* module raises `ImportError("jinja2 must be
    installed to use Jinja2Templates")` at import time if jinja2 is absent. So the
    requirement is real and unconditional, and an import scan of our own source will
    never find it - verified: removing the declaration leaves the test above green.

    Which is the general lesson, not a quirk. A dependency can be mandatory for us
    while appearing nowhere in our imports, because a library we do import needs it to
    load. The scan above catches the direct case; this catches the one that actually
    happened. A third class - a library that imports something lazily at call time -
    neither will catch, and only running the built image will.
    """
    assert "jinja2" in _declared_distributions(), (
        "jinja2 is a runtime import of app/api/reviewer_ui.py; undeclared, the "
        "container fails at startup with `jinja2 must be installed to use "
        "Jinja2Templates`"
    )
