"""Persist tenant/user authz epochs and shared rate-limit buckets.

Revision ID: 008_authz_epoch
Revises: 007_saas_platform
Create Date: 2026-09-28
"""

from __future__ import annotations

from alembic import op

revision = "008_authz_epoch"
down_revision = "007_saas_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS authz_epoch INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS authz_epoch INTEGER NOT NULL DEFAULT 0")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS rate_limit_buckets (
            bucket_key TEXT NOT NULL,
            window_started_at TIMESTAMPTZ NOT NULL,
            hit_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (bucket_key, window_started_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rate_limit_buckets_window ON rate_limit_buckets (window_started_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rate_limit_buckets")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS authz_epoch")
    op.execute("ALTER TABLE tenants DROP COLUMN IF EXISTS authz_epoch")
