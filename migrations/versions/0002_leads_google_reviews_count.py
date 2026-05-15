"""Add google_reviews_count column to leads.

Promotes review count from raw_metadata JSONB to a typed, indexed column so
the scheduler can ORDER BY it efficiently (highest-review restaurants first).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "leads",
        sa.Column("google_reviews_count", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_leads_google_reviews_count",
        "leads",
        [sa.text("google_reviews_count DESC NULLS LAST")],
    )


def downgrade() -> None:
    op.drop_index("ix_leads_google_reviews_count", table_name="leads")
    op.drop_column("leads", "google_reviews_count")
