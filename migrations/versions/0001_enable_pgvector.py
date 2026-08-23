"""Enable the pgvector extension.

Phase 0 creates no tables. It establishes only that the one datastore chosen in
ADR-005 can actually hold vectors, so that a Phase 1 migration adding
``policy_chunks.embedding`` cannot fail on a missing extension.

Deliberately not idempotent-by-accident: ``IF NOT EXISTS`` is explicit, and the
downgrade does **not** drop the extension. Dropping it would cascade away every
vector column in the database, which is not something a schema rollback should be
able to do silently.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_enable_pgvector"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    # Intentionally a no-op. See the module docstring.
    pass
