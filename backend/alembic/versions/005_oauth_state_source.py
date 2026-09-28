"""Remember which source an OAuth login should refresh.

Revision ID: 005_oauth_state_source
Revises: 004_content_address
Create Date: 2026-09-28
"""

from __future__ import annotations

from alembic import op

revision = "005_oauth_state_source"
down_revision = "004_content_address"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE oauth_states ADD COLUMN IF NOT EXISTS source_id UUID REFERENCES data_sources(id)")


def downgrade() -> None:
    op.execute("ALTER TABLE oauth_states DROP COLUMN IF EXISTS source_id")
