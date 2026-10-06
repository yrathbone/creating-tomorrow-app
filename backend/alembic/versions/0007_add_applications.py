"""Add applications table (simple job application tracker)

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-06

"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("career_profile_id", sa.Integer, sa.ForeignKey("career_profiles.id"), nullable=False),
        sa.Column("scan_history_id", sa.Integer, sa.ForeignKey("scan_histories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("resume_version_id", sa.Integer, sa.ForeignKey("resume_versions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("job_title", sa.String, nullable=False),
        sa.Column("company", sa.String, nullable=True),
        sa.Column("applied_on", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False, server_default="applied"),
        sa.Column("notes", sa.String, nullable=True),
        sa.Column("status_updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("applications")
